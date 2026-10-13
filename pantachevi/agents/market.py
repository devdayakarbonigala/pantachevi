from __future__ import annotations

from ..data import stubs
from ..models import AgentReport, Field_
from ..rules import rule_is_sample, rule_value


def market_report(field: Field_, prices: dict | None = None) -> AgentReport:
    prices = prices or stubs.stub_prices(field.mandi)
    now = prices["price_now_per_quintal"]
    before = prices["price_7d_ago_per_quintal"]
    change = round((now - before) / before * 100, 1)

    up = rule_value("market", "favourable_trend_pct")
    down = rule_value("market", "unfavourable_trend_pct")

    if change >= up:
        status = "favourable"
        summary = f"{prices['mandi']} price is up {change}% in 7 days (Rs {now:,} per quintal). Good time to pick and sell."
    elif change <= down:
        status = "unfavourable"
        summary = f"{prices['mandi']} price is down {abs(change)}% in 7 days (Rs {now:,} per quintal). Consider holding."
    else:
        status = "caution"
        summary = f"{prices['mandi']} price is flat ({change:+}% in 7 days, Rs {now:,} per quintal)."

    return AgentReport(
        agent="market",
        status=status,
        summary=summary,
        evidence={
            "price_now_per_quintal": now,
            "change_7d_pct": change,
            "mandi": prices["mandi"],
            "data_source": prices.get("source", "unknown"),
        },
        confidence=0.5 if prices.get("source") == "stub" else 0.75,
        uses_sample_rules=rule_is_sample("market", "favourable_trend_pct")
        or rule_is_sample("market", "unfavourable_trend_pct"),
    )
