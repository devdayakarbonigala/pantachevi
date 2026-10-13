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

DISCLAIMER_TE = (
    "PantaChevi ఒక సలహా సాధనం మాత్రమే, వ్యవసాయ నిపుణుల సలహాకు ప్రత్యామ్నాయం కాదు. "
    "'నమూనా' అని గుర్తించిన పిచికారీ, కోత నియమాలను ఇంకా నిజమైన మూలంతో సరిచూడలేదు."
)

AGENT_TE = {"weather": "వాతావరణం", "crop_stage": "పంట దశ", "market": "మార్కెట్"}
STATUS_TE = {"favourable": "అనుకూలం", "unfavourable": "అననుకూలం", "caution": "జాగ్రత్త"}

SPRAY_WORDS = ("spray", "pesticide", "fungicide", "insecticide", "పిచికారీ", "మందు", "స్ప్రే")
PICK_WORDS = ("pick", "harvest", "sell", "price", "mandi", "hold", "కోత", "కోయ", "అమ్మ", "ధర", "మార్కెట్", "యార్డ్")

DISCLAIMER = (
    "PantaChevi is a decision aid, not a replacement for an agricultural expert. "
    "Spray and harvest rules marked 'sample' have not been checked against a real source yet."
)


def detect_intent(question: str) -> str:
    q = question.lower()
    if any(w in q for w in SPRAY_WORDS):
        return "spray"
    if any(w in q for w in PICK_WORDS):
        return "pick"
    return "plan"


def _by_agent(reports: list[AgentReport]) -> dict[str, AgentReport]:
    return {r.agent: r for r in reports}


def _conflict(reports: list[AgentReport]) -> tuple[bool, str | None, str | None]:
    # An agent with no data (for example no mandi price entered) is silent, not a dissent.
    reports = [r for r in reports if r.evidence.get("has_data", True)]
    statuses = {r.status for r in reports}
    if len(statuses) <= 1:
        return False, None, None
    parts = [f"{r.agent.replace('_', ' ')} says {r.status}" for r in reports]
    parts_te = [f"{AGENT_TE.get(r.agent, r.agent)} {STATUS_TE[r.status]}" for r in reports]
    return True, "The agents disagree: " + ", ".join(parts) + ".", "ఏజెంట్ల అభిప్రాయాలు వేరుగా ఉన్నాయి: " + ", ".join(parts_te) + "."


Pair = tuple[str, str]  # (English, Telugu)


def _spray_part(r: dict[str, AgentReport]) -> tuple[Pair, list[Pair], Pair | None]:
    weather, stage = r["weather"], r["crop_stage"]
    weather_ok = weather.status == "favourable"
    stage_ok = bool(stage.evidence.get("spray_allowed"))
    if weather_ok and stage_ok:
        return (
            ("Spray tomorrow.", "రేపు పిచికారీ చేయండి."),
            [(weather.summary, weather.summary_te or ""), (stage.summary, stage.summary_te or "")],
            None,
        )
    reasons: list[Pair] = []
    if not weather_ok:
        reasons.append((weather.summary, weather.summary_te or ""))
    if not stage_ok:
        reasons.append((stage.summary, stage.summary_te or ""))
    follow = ("Re-check the forecast in 2 days.", "2 రోజుల్లో వాతావరణ సూచనను మళ్లీ చూడండి.") if not weather_ok else None
    return ("Skip the spray.", "పిచికారీ వద్దు."), reasons, follow


def _pick_part(r: dict[str, AgentReport]) -> tuple[Pair, list[Pair]]:
    stage, market = r["crop_stage"], r["market"]
    days = int(stage.evidence["days_to_first_pick"])
    when = "now" if days == 0 else f"in {days} days"
    when_te = "ఇప్పుడే" if days == 0 else f"{days} రోజుల్లో"
    reason = [(market.summary, market.summary_te or "")]
    if market.status == "favourable":
        return (f"Start picking {when}.", f"కోత {when_te} మొదలుపెట్టండి."), reason
    if market.status == "unfavourable":
        return (
            (f"Picking opens {when}. Consider holding the harvest after that.",
             f"కోత {when_te} మొదలవుతుంది. ఆ తర్వాత కోసిన కాయల అమ్మకం కొంత ఆపి చూడండి."),
            reason,
        )
    return (f"Picking opens {when}.", f"కోత {when_te} మొదలవుతుంది."), reason


def reconcile(intent: str, reports: list[AgentReport]) -> Verdict:
    r = _by_agent(reports)
    conflict, detail, detail_te = _conflict(reports)

    if intent == "spray":
        spray_action, reasons, follow = _spray_part(r)
        action = [spray_action]
        reasons = list(reasons)
        # Only add the picking advice when the picking window is close enough to matter.
        if int(r["crop_stage"].evidence["days_to_first_pick"]) <= 14:
            pick_action, pick_reasons = _pick_part(r)
            action.append(pick_action)
            reasons += pick_reasons
    elif intent == "pick":
        pick_action, reasons = _pick_part(r)
        action, follow = [pick_action], None
    else:
        spray_action, spray_reasons, follow = _spray_part(r)
        pick_action, pick_reasons = _pick_part(r)
        action = [spray_action, pick_action]
        reasons = spray_reasons + pick_reasons

    return Verdict(
        action=" ".join(a[0] for a in action),
        reason=" ".join(x[0] for x in reasons),
        conflict=conflict,
        conflict_detail=detail,
        follow_up=follow[0] if follow else None,
        action_te=" ".join(a[1] for a in action),
        reason_te=" ".join(x[1] for x in reasons),
        conflict_detail_te=detail_te,
        follow_up_te=follow[1] if follow else None,
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
        disclaimer_te=DISCLAIMER_TE,
    )
