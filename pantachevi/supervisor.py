"""Supervisor: runs the three agents in parallel and reconciles their reports
into one verdict with a reason.

Day-1 build: the reconciliation is deterministic rules, so every verdict can be
traced to a report. The Bedrock + Strands version will replace `reconcile`
only for wording and for questions the rules do not cover; the agent reports
and the Decision shape stay the same.
"""

from __future__ import annotations

import asyncio
from datetime import date

from .agents.crop_stage import crop_stage_report
from .agents.market import market_report
from .agents.weather import weather_report
from .models import AgentReport, Decision, Field_, Verdict
from .rules import all_rules_verified

DISCLAIMER = (
    "PantaChevi is a decision aid, not a replacement for an agricultural expert. "
    "Spray and harvest rules marked 'sample' have not been checked against a real source yet."
)


def detect_intent(question: str) -> str:
    q = question.lower()
    if any(w in q for w in ("spray", "pesticide", "fungicide", "insecticide")):
        return "spray"
    if any(w in q for w in ("pick", "harvest", "sell", "price", "mandi", "hold")):
        return "pick"
    return "plan"


def _by_agent(reports: list[AgentReport]) -> dict[str, AgentReport]:
    return {r.agent: r for r in reports}


def _conflict(reports: list[AgentReport]) -> tuple[bool, str | None]:
    # An agent with no data (for example no mandi price entered) is silent, not a dissent.
    reports = [r for r in reports if r.evidence.get("has_data", True)]
    statuses = {r.status for r in reports}
    if len(statuses) <= 1:
        return False, None
    parts = [f"{r.agent.replace('_', ' ')} says {r.status}" for r in reports]
    return True, "The agents disagree: " + ", ".join(parts) + "."


def _spray_part(r: dict[str, AgentReport]) -> tuple[str, list[str], str | None]:
    weather, stage = r["weather"], r["crop_stage"]
    weather_ok = weather.status == "favourable"
    stage_ok = bool(stage.evidence.get("spray_allowed"))
    if weather_ok and stage_ok:
        return "Spray tomorrow.", [weather.summary, stage.summary], None
    reasons = []
    if not weather_ok:
        reasons.append(weather.summary)
    if not stage_ok:
        reasons.append(stage.summary)
    follow = "Re-check the forecast in 2 days." if not weather_ok else None
    return "Skip the spray.", reasons, follow


def _pick_part(r: dict[str, AgentReport]) -> tuple[str, list[str]]:
    stage, market = r["crop_stage"], r["market"]
    days = int(stage.evidence["days_to_first_pick"])
    when = "now" if days == 0 else f"in {days} days"
    if market.status == "favourable":
        return f"Start picking {when}.", [market.summary]
    if market.status == "unfavourable":
        return f"Picking opens {when}. Consider holding the harvest after that.", [market.summary]
    return f"Picking opens {when}.", [market.summary]


def reconcile(intent: str, reports: list[AgentReport]) -> Verdict:
    r = _by_agent(reports)
    conflict, detail = _conflict(reports)

    if intent == "spray":
        spray_action, spray_reasons, follow = _spray_part(r)
        action, reasons = spray_action, list(spray_reasons)
        # Only add the picking advice when the picking window is close enough to matter.
        if int(r["crop_stage"].evidence["days_to_first_pick"]) <= 14:
            pick_action, pick_reasons = _pick_part(r)
            action = f"{spray_action} {pick_action}"
            reasons += pick_reasons
    elif intent == "pick":
        action, reasons = _pick_part(r)
        follow = None
    else:
        spray_action, spray_reasons, follow = _spray_part(r)
        pick_action, pick_reasons = _pick_part(r)
        action = f"{spray_action} {pick_action}"
        reasons = spray_reasons + pick_reasons

    return Verdict(
        action=action,
        reason=" ".join(reasons),
        conflict=conflict,
        conflict_detail=detail,
        follow_up=follow,
    )


async def decide(field: Field_, question: str, today: date | None = None, store=None) -> Decision:
    from .store import get_store

    store = store or await asyncio.to_thread(get_store)
    reports = list(
        await asyncio.gather(
            asyncio.to_thread(weather_report, field),
            asyncio.to_thread(crop_stage_report, field, today),
            asyncio.to_thread(market_report, field, store),
        )
    )
    intent = detect_intent(question)
    return Decision(
        field_id=field.id,
        question=question,
        intent=intent,
        reports=reports,
        verdict=reconcile(intent, reports),
        rules_verified=all_rules_verified(),
        disclaimer=DISCLAIMER,
    )
