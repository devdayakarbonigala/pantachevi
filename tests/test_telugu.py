import re
from datetime import date, timedelta

import pytest

from pantachevi import service
from pantachevi.models import Field_
from pantachevi.store import MemoryStore
from pantachevi.supervisor import decide, detect_intent

TELUGU = re.compile(r"[ఀ-౿]")
TODAY = date(2026, 10, 13)


def numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text)


def run(coro):
    import asyncio
    return asyncio.run(coro)


def make(days_old=60, spray_days_ago=None, prices=(), mandi="Tenali"):
    s = MemoryStore()
    service.register_field(s, "t-1", "R", "Teja", "V", 16.3, 80.4, TODAY - timedelta(days=days_old),
                           mandi=mandi, today=TODAY)
    if spray_days_ago is not None:
        service.log_activity(s, "t-1", "spray", TODAY - timedelta(days=spray_days_ago), today=TODAY)
    for ago, price in prices:
        service.log_price(s, mandi, price, TODAY - timedelta(days=ago), today=TODAY)
    return s


SCENARIOS = {
    "demo": dict(days_old=98, spray_days_ago=6, prices=((7, 15000), (0, 16200)), mandi="Guntur (demo)"),
    "clear": dict(days_old=40, prices=((7, 15000), (0, 16200))),
    "price_falling": dict(days_old=98, prices=((7, 15000), (0, 13000))),
    "flat": dict(days_old=60, prices=((7, 15000), (0, 15100))),
    "no_price": dict(days_old=60),
    "one_price": dict(days_old=60, prices=((0, 15000),)),
    "stale_price": dict(days_old=60, prices=((6, 15000),)),
}


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("question", ["Should I spray tomorrow?", "pick and sell?", "What should I do this week?"])
def test_every_english_text_has_a_telugu_twin_with_the_same_numbers(name, question, monkeypatch):
    monkeypatch.setenv("PANTACHEVI_WEATHER", "stub")
    s = make(**SCENARIOS[name])
    field = s.get_field("t-1")
    d = run(decide(field, question, today=TODAY, store=s))
    pairs = [(r.summary, r.summary_te) for r in d.reports]
    v = d.verdict
    pairs += [(v.action, v.action_te), (v.reason, v.reason_te), (d.disclaimer, d.disclaimer_te)]
    if v.conflict:
        pairs.append((v.conflict_detail, v.conflict_detail_te))
    if v.follow_up:
        pairs.append((v.follow_up, v.follow_up_te))
    for en, te in pairs:
        assert te and TELUGU.search(te), f"missing Telugu for: {en}"
        assert "{" not in te and "}" not in te and "None" not in te, te
        # Same figures in both languages (ignore the fixed "7" etc. only if absent in both).
        assert sorted(numbers(en)) == sorted(numbers(te)) or not numbers(en), (en, te)
    assert (v.conflict_detail_te is None) == (v.conflict_detail is None)
    assert (v.follow_up_te is None) == (v.follow_up is None)


def test_demo_verdict_in_telugu(monkeypatch):
    monkeypatch.setenv("PANTACHEVI_WEATHER", "stub")
    s = make(**SCENARIOS["demo"])
    d = run(decide(s.get_field("t-1"), "Should I spray tomorrow?", today=TODAY, store=s))
    assert d.verdict.action_te == "పిచికారీ వద్దు. కోత 7 రోజుల్లో మొదలుపెట్టండి."
    assert d.verdict.follow_up_te == "2 రోజుల్లో వాతావరణ సూచనను మళ్లీ చూడండి."
    assert "వాతావరణం అననుకూలం" in d.verdict.conflict_detail_te


@pytest.mark.parametrize("text,intent", [
    ("రేపు పిచికారీ చేయాలా?", "spray"),
    ("మందు కొట్టొచ్చా", "spray"),
    ("ఎప్పుడు కోత కోయాలి, ధర ఎలా ఉంది?", "pick"),
    ("అమ్మాలా వద్దా", "pick"),
    ("మార్కెట్ యార్డ్ ధర", "pick"),
    ("ఈ వారం ఏం చేయాలి?", "plan"),
    ("Should I spray tomorrow?", "spray"),
])
def test_telugu_questions_are_understood(text, intent):
    assert detect_intent(text) == intent


def test_endpoint_returns_both_languages(client):
    d = client.post("/api/advice", json={"field_id": "demo-1", "question": "రేపు పిచికారీ చేయాలా?"}).json()
    assert d["intent"] == "spray" and TELUGU.search(d["verdict"]["action_te"])
    assert d["verdict"]["action"].startswith("Skip the spray")
