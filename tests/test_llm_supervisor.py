"""Bedrock supervisor: switch, validation and fallback, all against a fake client.
No AWS call is made here, so these tests prove the plumbing, not the live model."""

import asyncio
import json
from datetime import date, timedelta

import pytest

from pantachevi.llm_supervisor import (
    SupervisorError,
    expected_spray_call,
    parse_model_text,
    supervisor_mode,
)
from pantachevi.models import AgentReport
from pantachevi.store import MemoryStore
from pantachevi.supervisor import decide

TODAY = date(2026, 10, 15)


def _good(spray="skip", **over):
    body = {
        "action": "Skip the spray.",
        "reason": "Rain is expected.",
        "follow_up": "Check again in 2 days.",
        "action_te": "పిచికారీ వద్దు.",
        "reason_te": "వర్షం వచ్చే అవకాశం ఉంది.",
        "follow_up_te": "2 రోజుల్లో మళ్లీ చూడండి.",
        "spray": spray,
    }
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


def _field_store():
    s = MemoryStore()
    return s, s.get_field("guntur-demo-01") or s.get_field(s.list_field_ids()[0])


def _run(converse, monkeypatch, mode="bedrock", model="test-model", question="Should I spray tomorrow?"):
    monkeypatch.setenv("PANTACHEVI_SUPERVISOR", mode)
    if model:
        monkeypatch.setenv("PANTACHEVI_BEDROCK_MODEL_ID", model)
    else:
        monkeypatch.delenv("PANTACHEVI_BEDROCK_MODEL_ID", raising=False)
    s, f = _field_store()
    return asyncio.run(decide(f, question, TODAY, store=s, converse=converse))


def _rules_spray(monkeypatch):
    monkeypatch.setenv("PANTACHEVI_SUPERVISOR", "rules")
    s, f = _field_store()
    d = asyncio.run(decide(f, "Should I spray tomorrow?", TODAY, store=s))
    return expected_spray_call(d.intent, d.reports), d


def test_default_is_rules(monkeypatch):
    monkeypatch.delenv("PANTACHEVI_SUPERVISOR", raising=False)
    assert supervisor_mode() == "rules"
    monkeypatch.setenv("PANTACHEVI_SUPERVISOR", "nonsense")
    assert supervisor_mode() == "rules"


def test_rules_mode_never_calls_the_model(monkeypatch):
    def boom(*a):
        raise AssertionError("model must not be called in rules mode")

    d = _run(boom, monkeypatch, mode="rules")
    assert d.supervisor == "rules" and d.supervisor_note is None


def test_bedrock_verdict_used_when_valid(monkeypatch):
    want, rules = _rules_spray(monkeypatch)
    seen = {}

    def fake(model_id, system, user):
        seen["model"], seen["user"] = model_id, json.loads(user)
        return _good(spray=want, action="MODEL ACTION")

    d = _run(fake, monkeypatch)
    assert d.supervisor == "bedrock" and d.supervisor_note is None
    assert d.verdict.action == "MODEL ACTION"
    assert seen["model"] == "test-model"
    assert {r["agent"] for r in seen["user"]["reports"]} == {"weather", "crop_stage", "market"}
    # conflict facts come from the rules, not the model
    assert d.verdict.conflict == rules.verdict.conflict
    assert d.verdict.conflict_detail == rules.verdict.conflict_detail


def test_fenced_json_is_accepted():
    out = parse_model_text("```json\n" + _good() + "\n```")
    assert out.action == "Skip the spray."


@pytest.mark.parametrize("bad", ["no json here", "{not json}", json.dumps({"action": "x"})])
def test_unusable_replies_raise(bad):
    with pytest.raises(SupervisorError):
        parse_model_text(bad)


def test_empty_telugu_is_rejected():
    with pytest.raises(SupervisorError):
        parse_model_text(_good(action_te="  "))


def test_spray_disagreement_falls_back(monkeypatch):
    want, rules = _rules_spray(monkeypatch)
    wrong = "go" if want == "skip" else "skip"
    d = _run(lambda *a: _good(spray=wrong), monkeypatch)
    assert d.supervisor == "rules"
    assert "disagrees with the rules" in d.supervisor_note
    assert d.verdict.action == rules.verdict.action


def test_client_error_falls_back(monkeypatch):
    def denied(*a):
        raise RuntimeError("AccessDeniedException")

    d = _run(denied, monkeypatch)
    assert d.supervisor == "rules"
    assert "RuntimeError" in d.supervisor_note
    assert d.verdict.action  # still a complete rule-based verdict


def test_missing_model_id_falls_back(monkeypatch):
    d = _run(lambda *a: _good(), monkeypatch, model=None)
    assert d.supervisor == "rules"
    assert "PANTACHEVI_BEDROCK_MODEL_ID" in d.supervisor_note


def test_pick_question_expects_no_spray_call(monkeypatch):
    d = _run(lambda *a: _good(spray="none"), monkeypatch, question="When should I pick and sell?")
    assert d.intent == "pick" and d.supervisor == "bedrock"


def test_expected_spray_call_follows_reports():
    ok = AgentReport(agent="weather", status="favourable", summary="dry", confidence=0.9)
    stage = AgentReport(agent="crop_stage", status="favourable", summary="ok", confidence=0.9,
                        evidence={"spray_allowed": True})
    bad = AgentReport(agent="crop_stage", status="unfavourable", summary="too soon", confidence=0.9,
                      evidence={"spray_allowed": False})
    assert expected_spray_call("spray", [ok, stage]) == "go"
    assert expected_spray_call("spray", [ok, bad]) == "skip"
    assert expected_spray_call("pick", [ok, bad]) == "none"
