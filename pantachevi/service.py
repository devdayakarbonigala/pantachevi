"""Operations shared by the MCP tools and the REST API: read a field's state,
register a field, log an activity. Errors are returned as {"error": ...} dicts
(never raised) so an MCP client and the web page get a readable message."""

from __future__ import annotations

import re
from datetime import date

from pydantic import ValidationError

from .models import Field_
from .rules import rule_value
from .store import Activity, PriceObservation, Store

FIELD_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")


def field_state(store: Store, field_id: str, today: date | None = None) -> dict:
    field = store.get_field(field_id)
    if field is None:
        return {"error": f"Unknown field_id '{field_id}'. Known fields: {store.list_field_ids()}"}
    today = today or date.today()
    since = (today - field.last_spray_date).days if field.last_spray_date else None
    return {
        "field": field.model_dump(mode="json"),
        "days_after_sowing": (today - field.sowing_date).days,
        "days_since_last_spray": since,
        "recent_activities": [a.model_dump(mode="json") for a in store.list_activities(field_id)],
    }


def register_field(
    store: Store,
    field_id: str,
    farmer: str,
    variety: str,
    village: str,
    lat: float,
    lng: float,
    sowing_date: date,
    mandi: str = "Guntur",
    today: date | None = None,
) -> dict:
    today = today or date.today()
    if not FIELD_ID_RE.match(field_id):
        return {"error": "field_id must be 3 to 40 characters: lowercase letters, digits and hyphens."}
    if store.get_field(field_id) is not None:
        return {"error": f"Field '{field_id}' already exists."}
    if sowing_date > today:
        return {"error": "sowing_date cannot be in the future."}
    try:
        field = Field_(id=field_id, farmer=farmer.strip(), variety=variety.strip(),
                       village=village.strip(), lat=lat, lng=lng, sowing_date=sowing_date,
                       mandi=mandi.strip())
    except ValidationError as exc:
        return {"error": f"Invalid field: {exc.errors()[0]['msg']}"}
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return {"error": "lat must be within -90..90 and lng within -180..180."}
    if not all((field.farmer, field.variety, field.village, field.mandi)):
        return {"error": "farmer, variety, village and mandi cannot be empty."}
    store.upsert_field(field)
    return field_state(store, field_id, today)


def log_activity(
    store: Store,
    field_id: str,
    kind: str,
    on_date: date | None = None,
    product: str | None = None,
    notes: str | None = None,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    field = store.get_field(field_id)
    if field is None:
        return {"error": f"Unknown field_id '{field_id}'. Known fields: {store.list_field_ids()}"}
    if kind not in ("spray", "pick", "note"):
        return {"error": "kind must be one of: spray, pick, note."}
    on_date = on_date or today
    if on_date > today:
        return {"error": "on_date cannot be in the future. Log it when it happens."}
    if on_date < field.sowing_date:
        return {"error": f"on_date is before this field was sown ({field.sowing_date})."}

    warnings: list[str] = []
    if kind == "spray" and field.last_spray_date is not None:
        gap = (on_date - field.last_spray_date).days
        min_gap = rule_value("crop_stage", "min_days_between_sprays")
        if 0 <= gap < min_gap:
            warnings.append(
                f"This spray is only {gap} days after the previous one (minimum gap {min_gap:g} days). "
                "Logged anyway because it records what happened."
            )
    try:
        saved = store.add_activity(
            Activity(field_id=field_id, kind=kind, on_date=on_date,
                     product=(product or None), notes=(notes or None))
        )
    except ValidationError as exc:
        return {"error": f"Invalid activity: {exc.errors()[0]['msg']}"}

    result = field_state(store, field_id, today)
    result["logged"] = saved.model_dump(mode="json")
    result["warnings"] = warnings
    return result


MIN_PRICE = 1_000      # Rs per quintal; below this is almost certainly a typo
MAX_PRICE = 100_000
JUMP_WARN_PCT = 30


def log_price(
    store: Store,
    mandi: str,
    price_per_quintal: int,
    on_date: date | None = None,
    note: str | None = None,
    today: date | None = None,
) -> dict:
    """Record a mandi price typed in by the farmer. Same mandi and date replaces the earlier entry."""
    from .data.prices import get_prices

    today = today or date.today()
    mandi = (mandi or "").strip()
    if not mandi:
        return {"error": "mandi cannot be empty."}
    if not (MIN_PRICE <= price_per_quintal <= MAX_PRICE):
        return {"error": f"price_per_quintal must be between Rs {MIN_PRICE:,} and Rs {MAX_PRICE:,} per quintal."}
    on_date = on_date or today
    if on_date > today:
        return {"error": "on_date cannot be in the future."}
    if (today - on_date).days > 30:
        return {"error": "on_date is more than 30 days ago. Enter a recent price."}

    earlier = [p for p in store.list_prices(mandi) if p.on_date < on_date]
    warnings: list[str] = []
    if earlier:
        prev = earlier[0]
        jump = (price_per_quintal - prev.price_per_quintal) / prev.price_per_quintal * 100
        if abs(jump) >= JUMP_WARN_PCT:
            warnings.append(
                f"This is {jump:+.0f}% against Rs {prev.price_per_quintal:,} on {prev.on_date}. "
                "Saved, but please check for a typing mistake."
            )
    try:
        saved = store.upsert_price(
            PriceObservation(mandi=mandi, on_date=on_date, price_per_quintal=price_per_quintal, note=note or None)
        )
    except ValidationError as exc:
        return {"error": f"Invalid price entry: {exc.errors()[0]['msg']}"}
    return {
        "logged": saved.model_dump(mode="json"),
        "market_view": get_prices(store, mandi, today),
        "recent_prices": [p.model_dump(mode="json") for p in store.list_prices(mandi, 7)],
        "warnings": warnings,
    }


def delete_price(store: Store, mandi: str, on_date: date, today: date | None = None) -> dict:
    """Remove one typed price (for a wrong entry). Returns the remaining recent prices."""
    from .data.prices import get_prices

    today = today or date.today()
    mandi = (mandi or "").strip()
    if not store.delete_price(mandi, on_date):
        return {"error": f"No price entered for {mandi!r} on {on_date}."}
    return {
        "deleted": {"mandi": mandi, "on_date": on_date.isoformat()},
        "market_view": get_prices(store, mandi, today),
        "recent_prices": [p.model_dump(mode="json") for p in store.list_prices(mandi, 7)],
    }
