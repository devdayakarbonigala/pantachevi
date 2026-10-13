from __future__ import annotations

from ..data.prices import get_prices
from ..models import AgentReport, Field_
from ..rules import rule_is_sample, rule_value
from ..store import Store


def _uses_sample() -> bool:
    return rule_is_sample("market", "favourable_trend_pct") or rule_is_sample("market", "unfavourable_trend_pct")


def market_report(field: Field_, store: Store | None = None, prices: dict | None = None) -> AgentReport:
    if prices is None:
        from ..store import get_store

        prices = get_prices(store or get_store(), field.mandi)
    mandi = prices.get("mandi", field.mandi)
    source = prices.get("source", "unknown")

    if source == "none":
        latest = prices.get("latest_entry_date")
        why = f"The latest price entered was on {latest}, which is too old." if latest else "No price has been entered."
        why_te = f"చివరిగా {latest} న నమోదైన ధర చాలా పాతది." if latest else "ధర ఏదీ నమోదు కాలేదు."
        return AgentReport(
            agent="market",
            status="caution",
            summary=f"No recent {mandi} price. {why} Enter today's price per quintal to include the market in the call.",
            summary_te=f"{mandi} ధర ఇటీవల నమోదు కాలేదు. {why_te} కాల్‌లో మార్కెట్‌ను చేర్చడానికి ఈరోజు క్వింటాల్ ధర నమోదు చేయండి.",
            evidence={"data_source": "none", "mandi": mandi, "has_data": False},
            confidence=0.1,
            uses_sample_rules=_uses_sample(),
        )

    now = prices["price_now_per_quintal"]
    before = prices.get("price_7d_ago_per_quintal")
    age = prices.get("age_days")
    entered = "entered today" if not age else f"entered {age} day{'s' if age != 1 else ''} ago"
    entered_te = "ఈరోజు నమోదు" if not age else f"{age} రోజుల క్రితం నమోదు"

    if before is None:
        return AgentReport(
            agent="market",
            status="caution",
            summary=f"{mandi} price is Rs {now:,} per quintal ({entered}). There is no earlier price to show a trend.",
            summary_te=f"{mandi} ధర క్వింటాల్‌కు ₹{now:,} ({entered_te}). పోలిక కోసం ముందటి ధర లేదు, కాబట్టి ధోరణి చెప్పలేను.",
            evidence={"price_now_per_quintal": now, "mandi": mandi, "data_source": source, "has_data": True},
            confidence=0.4,
            uses_sample_rules=_uses_sample(),
        )

    days = prices.get("baseline_days") or 7
    change = round((now - before) / before * 100, 1)
    up = rule_value("market", "favourable_trend_pct")
    down = rule_value("market", "unfavourable_trend_pct")

    if change >= up:
        status = "favourable"
        summary = f"{mandi} price is up {change}% in {days} days (Rs {now:,} per quintal, {entered}). Good time to pick and sell."
        summary_te = f"{mandi} ధర {days} రోజుల్లో {change}% పెరిగింది (క్వింటాల్‌కు ₹{now:,}, {entered_te}). కోసి అమ్మడానికి మంచి సమయం."
    elif change <= down:
        status = "unfavourable"
        summary = f"{mandi} price is down {abs(change)}% in {days} days (Rs {now:,} per quintal, {entered}). Consider holding."
        summary_te = f"{mandi} ధర {days} రోజుల్లో {abs(change)}% తగ్గింది (క్వింటాల్‌కు ₹{now:,}, {entered_te}). అమ్మకం కొంత ఆపి చూడండి."
    else:
        status = "caution"
        summary = f"{mandi} price is flat ({change:+}% in {days} days, Rs {now:,} per quintal, {entered})."
        summary_te = f"{mandi} ధర దాదాపు స్థిరంగా ఉంది ({days} రోజుల్లో {change:+}%, క్వింటాల్‌కు ₹{now:,}, {entered_te})."

    return AgentReport(
        agent="market",
        status=status,
        summary=summary,
        summary_te=summary_te,
        evidence={
            "price_now_per_quintal": now,
            "change_7d_pct": change,
            "trend_days": days,
            "mandi": mandi,
            "data_source": source,
            "has_data": True,
        },
        confidence=0.75 if (age or 0) <= 1 else 0.6,
        uses_sample_rules=_uses_sample(),
    )
