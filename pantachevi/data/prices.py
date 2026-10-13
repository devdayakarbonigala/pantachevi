"""Mandi prices typed in by a farmer or trader, read back for the market agent.

Rules, all chosen here and not agronomic facts:
  - the newest entry is "now"; it counts only if it is at most MAX_AGE_DAYS old
  - the trend baseline is the entry nearest to 7 days before "now", and it must
    be 4 to 10 days earlier; otherwise there is no trend to report
"""

from __future__ import annotations

from datetime import date

from ..store import Store

MAX_AGE_DAYS = 3
BASELINE_TARGET_DAYS = 7
BASELINE_MIN_DAYS = 4
BASELINE_MAX_DAYS = 10


def get_prices(store: Store, mandi: str, today: date | None = None) -> dict:
    """Return the dict the market agent reads. `source` is "none" when no usable price exists."""
    today = today or date.today()
    rows = store.list_prices(mandi)
    if not rows or (today - rows[0].on_date).days > MAX_AGE_DAYS:
        latest = rows[0].on_date.isoformat() if rows else None
        return {"source": "none", "mandi": mandi, "latest_entry_date": latest}

    now = rows[0]
    candidates = [
        r for r in rows[1:]
        if BASELINE_MIN_DAYS <= (now.on_date - r.on_date).days <= BASELINE_MAX_DAYS
    ]
    base = min(candidates, key=lambda r: abs((now.on_date - r.on_date).days - BASELINE_TARGET_DAYS), default=None)
    return {
        "source": "farmer-entered",
        "mandi": mandi,
        "price_now_per_quintal": now.price_per_quintal,
        "price_now_date": now.on_date.isoformat(),
        "age_days": (today - now.on_date).days,
        "price_7d_ago_per_quintal": base.price_per_quintal if base else None,
        "baseline_days": (now.on_date - base.on_date).days if base else None,
    }
