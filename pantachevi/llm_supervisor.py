"""Optional LLM supervisor on Amazon Bedrock (Converse API).

The rule-based verdict is always computed first. In bedrock mode the model is
given the three agent reports plus that draft and asked to write the final
verdict (English and Telugu). The result is accepted only if it passes checks;
otherwise the caller keeps the rule-based verdict and records why.

Checks (a model cannot flip the safety-relevant parts):
  * the JSON parses and has non-empty action/reason in both languages
  * its spray call (go / skip / none) matches what the rules derived from the reports
  * the `conflict` flag and its detail are taken from the rules, never from the model

Configuration, all from the environment (no secrets in the repo):
  PANTACHEVI_SUPERVISOR        rules (default) or bedrock
  PANTACHEVI_BEDROCK_MODEL_ID  model or inference profile ID, required in bedrock mode
  AWS_REGION                   Bedrock region (default us-east-1)
  AWS credentials              the usual boto3 chain, or AWS_BEARER_TOKEN_BEDROCK
  PANTACHEVI_BEDROCK_TIMEOUT   seconds, default 12
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Callable

from pydantic import BaseModel, ValidationError

from .models import AgentReport, Verdict

log = logging.getLogger("pantachevi.llm")

SPRAY_CALLS = ("go", "skip", "none")

SYSTEM_PROMPT = """You are the supervisor of PantaChevi, a decision aid for chilli farmers in Guntur, India.
Three agents (weather, crop_stage, market) have reported. Write one short verdict for the farmer.

Rules:
- Use only the facts in the reports. Do not invent numbers, dates, prices or products.
- Never name a pesticide or give a dose.
- A report with evidence has_data=false is silent, not a dissent.
- Reports marked uses_sample_rules=true rest on unverified sample values; do not sound more certain than the reports.
- Be brief: action is one or two sentences, reason is one or two sentences.
- Write the Telugu fields in simple spoken Telugu a farmer would use. They must say the same thing as the English.
- "spray" must be "go" if the verdict tells the farmer to spray, "skip" if it tells them not to, "none" if spraying is not discussed.

Reply with one JSON object and nothing else, with exactly these keys:
action, reason, follow_up, action_te, reason_te, follow_up_te, spray
follow_up and follow_up_te may be null."""


class LLMVerdict(BaseModel):
    action: str
    reason: str
    action_te: str
    reason_te: str
    follow_up: str | None = None
    follow_up_te: str | None = None
    spray: str


class SupervisorError(Exception):
    """The LLM verdict could not be used. The message goes into the decision's note."""


def supervisor_mode() -> str:
    mode = os.environ.get("PANTACHEVI_SUPERVISOR", "rules").strip().lower()
    return mode if mode in ("rules", "bedrock") else "rules"


def expected_spray_call(intent: str, reports: list[AgentReport]) -> str:
    """What the rules say about spraying, so the model cannot contradict it."""
    if intent == "pick":
        return "none"
    r = {x.agent: x for x in reports}
    ok = r["weather"].status == "favourable" and bool(r["crop_stage"].evidence.get("spray_allowed"))
    return "go" if ok else "skip"


def build_user_message(question: str, intent: str, reports: list[AgentReport], draft: Verdict) -> str:
    payload = {
        "question": question,
        "intent": intent,
        "reports": [r.model_dump(mode="json", exclude={"summary_te"}) for r in reports],
        "rule_based_draft": {"action": draft.action, "reason": draft.reason, "follow_up": draft.follow_up},
    }
    return json.dumps(payload, ensure_ascii=False)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_model_text(text: str) -> LLMVerdict:
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise SupervisorError("model reply contained no JSON object")
    try:
        data = json.loads(cleaned[start : end + 1])
        verdict = LLMVerdict(**data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise SupervisorError(f"model reply did not match the expected shape: {exc.__class__.__name__}") from exc
    if verdict.spray not in SPRAY_CALLS:
        raise SupervisorError("model gave an unknown spray call")
    for name in ("action", "reason", "action_te", "reason_te"):
        if not getattr(verdict, name).strip():
            raise SupervisorError(f"model left '{name}' empty")
    return verdict


def _bedrock_converse(model_id: str, system: str, user: str) -> str:
    """Real call. boto3 is imported here so rules mode needs no AWS packages."""
    import boto3
    from botocore.config import Config

    timeout = float(os.environ.get("PANTACHEVI_BEDROCK_TIMEOUT", "12"))
    client = boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(read_timeout=timeout, connect_timeout=5, retries={"max_attempts": 1}),
    )
    resp = client.converse(
        modelId=model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": 700, "temperature": 0.2},
    )
    blocks = resp["output"]["message"]["content"]
    return "".join(b.get("text", "") for b in blocks)


Converse = Callable[[str, str, str], str]


def llm_verdict(
    question: str,
    intent: str,
    reports: list[AgentReport],
    draft: Verdict,
    converse: Converse | None = None,
) -> Verdict:
    """Return the model-written verdict, or raise SupervisorError / the client's exception."""
    model_id = os.environ.get("PANTACHEVI_BEDROCK_MODEL_ID", "").strip()
    if not model_id:
        raise SupervisorError("PANTACHEVI_BEDROCK_MODEL_ID is not set")
    text = (converse or _bedrock_converse)(model_id, SYSTEM_PROMPT, build_user_message(question, intent, reports, draft))
    out = parse_model_text(text)
    want = expected_spray_call(intent, reports)
    if out.spray != want:
        raise SupervisorError(f"model spray call '{out.spray}' disagrees with the rules ('{want}')")
    return Verdict(
        action=out.action.strip(),
        reason=out.reason.strip(),
        follow_up=(out.follow_up or "").strip() or None,
        action_te=out.action_te.strip(),
        reason_te=out.reason_te.strip(),
        follow_up_te=(out.follow_up_te or "").strip() or None,
        # the disagreement between agents is a fact about the reports, not model opinion
        conflict=draft.conflict,
        conflict_detail=draft.conflict_detail,
        conflict_detail_te=draft.conflict_detail_te,
    )
