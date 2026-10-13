import asyncio
from datetime import date, timedelta

from pantachevi.agents.crop_stage import crop_stage_report
from pantachevi.agents.market import market_report
from pantachevi.agents.weather import weather_report
from pantachevi.data import stubs
from pantachevi.models import Field_
from pantachevi.supervisor import decide, detect_intent

TODAY = date(2026, 10, 13)


def field(**kw) -> Field_:
    base = dict(
        id="t", farmer="t", variety="Teja", village="x", lat=16.3, lng=80.4,
        sowing_date=TODAY - timedelta(days=98),
        last_spray_date=TODAY - timedelta(days=6), mandi="Guntur",
    )
    base.update(kw)
    return Field_(**base)


def test_weather_blocks_on_rain():
    r = weather_report(field(), {"rain_probability_pct": 70, "wind_kmh": 9, "source": "test"})
    assert r.status == "unfavourable"
    assert "70%" in r.summary


def test_weather_blocks_on_wind():
    r = weather_report(field(), {"rain_probability_pct": 10, "wind_kmh": 30, "source": "test"})
    assert r.status == "unfavourable"


def test_weather_ok():
    r = weather_report(field(), {"rain_probability_pct": 10, "wind_kmh": 5, "source": "test"})
    assert r.status == "favourable"


def test_stage_blocks_inside_pre_harvest_interval():
    r = crop_stage_report(field(), TODAY)  # day 98, picking in 7 days, last spray 6 days ago
    assert r.evidence["days_after_sowing"] == 98
    assert r.evidence["days_to_first_pick"] == 7
    assert r.evidence["spray_allowed"] is False


def test_stage_allows_early_in_season():
    f = field(sowing_date=TODAY - timedelta(days=40), last_spray_date=TODAY - timedelta(days=30))
    r = crop_stage_report(f, TODAY)
    assert r.evidence["spray_allowed"] is True
    assert r.status == "favourable"


def P(now, before):
    return {"source": "farmer-entered", "mandi": "Guntur", "price_now_per_quintal": now,
            "price_7d_ago_per_quintal": before, "age_days": 0, "baseline_days": 7}


def test_market_trend():
    up = market_report(field(), prices=P(16200, 15000))
    down = market_report(field(), prices=P(14000, 15000))
    flat = market_report(field(), prices=P(15100, 15000))
    assert (up.status, down.status, flat.status) == ("favourable", "unfavourable", "caution")


def test_intents():
    assert detect_intent("Should I spray tomorrow?") == "spray"
    assert detect_intent("When should I sell?") == "pick"
    assert detect_intent("What should I do this week?") == "plan"


def test_demo_scenario_is_a_visible_conflict():
    f = stubs.demo_fields(TODAY)["demo-1"]
    d = asyncio.run(decide(f, "Should I spray tomorrow?", TODAY))
    assert d.verdict.conflict is True
    assert d.verdict.action.startswith("Skip the spray.")
    assert "Start picking in 7 days" in d.verdict.action
    assert d.verdict.follow_up
    assert d.rules_verified is False  # all rules are still samples
    assert {r.agent for r in d.reports} == {"weather", "crop_stage", "market"}
