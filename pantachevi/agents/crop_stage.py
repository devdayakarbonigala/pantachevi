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

    blockers, blockers_te = [], []
    if days_to_pick < phi:
        blockers.append(
            f"picking opens in {days_to_pick} days, inside the {phi:g}-day pre-harvest interval"
        )
        blockers_te.append(f"కోత {days_to_pick} రోజుల్లో మొదలవుతుంది, ఇది కోతకు ముందు {phi:g} రోజుల వ్యవధిలో ఉంది")
    if since_spray is not None and since_spray < min_gap:
        blockers.append(f"last spray was only {since_spray} days ago (minimum gap {min_gap:g} days)")
        blockers_te.append(f"చివరి పిచికారీ {since_spray} రోజుల క్రితమే జరిగింది (కనీస వ్యవధి {min_gap:g} రోజులు)")

    if blockers:
        status = "unfavourable"
        summary = f"Day {age} after sowing. Spraying is blocked: " + "; ".join(blockers) + "."
        summary_te = f"నాటిన {age}వ రోజు. పిచికారీ చేయకూడదు: " + "; ".join(blockers_te) + "."
    elif days_to_pick <= 14:
        status = "caution"
        summary = f"Day {age} after sowing, picking opens in {days_to_pick} days. Spraying is allowed now."
        summary_te = f"నాటిన {age}వ రోజు, కోత {days_to_pick} రోజుల్లో మొదలవుతుంది. ఇప్పుడు పిచికారీ చేయవచ్చు."
    else:
        status = "favourable"
        summary = f"Day {age} after sowing, picking opens in {days_to_pick} days. Spraying is allowed."
        summary_te = f"నాటిన {age}వ రోజు, కోత {days_to_pick} రోజుల్లో మొదలవుతుంది. పిచికారీ చేయవచ్చు."

    return AgentReport(
        agent="crop_stage",
        status=status,
        summary=summary,
        summary_te=summary_te,
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
