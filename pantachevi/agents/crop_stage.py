from __future__ import annotations

from datetime import date

from ..models import AgentReport, Field_
from ..rules import rule_is_sample, rule_value


def crop_stage_report(field: Field_, today: date | None = None) -> AgentReport:
    today = today or date.today()
    first_pick_day = rule_value("crop_stage", "days_to_first_pick")
    phi = rule_value("crop_stage", "pre_harvest_interval_days")
    min_gap = rule_value("crop_stage", "min_days_between_sprays")

    age = (today - field.sowing_date).days
    days_to_pick = max(int(first_pick_day) - age, 0)
    since_spray = (today - field.last_spray_date).days if field.last_spray_date else None

    blockers = []
    if days_to_pick < phi:
        blockers.append(
            f"picking opens in {days_to_pick} days, inside the {phi:g}-day pre-harvest interval"
        )
    if since_spray is not None and since_spray < min_gap:
        blockers.append(f"last spray was only {since_spray} days ago (minimum gap {min_gap:g} days)")

    if blockers:
        status = "unfavourable"
        summary = f"Day {age} after sowing. Spraying is blocked: " + "; ".join(blockers) + "."
    elif days_to_pick <= 14:
        status = "caution"
        summary = f"Day {age} after sowing, picking opens in {days_to_pick} days. Spraying is allowed now."
    else:
        status = "favourable"
        summary = f"Day {age} after sowing, picking opens in {days_to_pick} days. Spraying is allowed."

    return AgentReport(
        agent="crop_stage",
        status=status,
        summary=summary,
        evidence={
            "days_after_sowing": age,
            "days_to_first_pick": days_to_pick,
            "days_since_last_spray": since_spray,
            "spray_allowed": not blockers,
        },
        confidence=0.7,
        uses_sample_rules=any(
            rule_is_sample("crop_stage", n)
            for n in ("days_to_first_pick", "pre_harvest_interval_days", "min_days_between_sprays")
        ),
    )
