from datetime import date, timedelta

import pytest

from pantachevi import service
from pantachevi.models import Field_
from pantachevi.store import Activity, MemoryStore

TODAY = date(2026, 10, 13)


def new_field(store, field_id="ramu-1", sown_days_ago=60):
    return service.register_field(store, field_id, "Ramu", "Teja", "Nallapadu", 16.33, 80.43,
                                  TODAY - timedelta(days=sown_days_ago), today=TODAY)


def test_demo_field_seeded_with_derived_last_spray():
    s = MemoryStore()
    demo = s.get_field("demo-1")
    assert demo is not None and demo.last_spray_date == date.today() - timedelta(days=6)


def test_last_spray_comes_from_newest_spray_activity():
    s = MemoryStore()
    new_field(s)
    assert s.get_field("ramu-1").last_spray_date is None
    service.log_activity(s, "ramu-1", "spray", TODAY - timedelta(days=20), today=TODAY)
    service.log_activity(s, "ramu-1", "spray", TODAY - timedelta(days=12), today=TODAY)
    service.log_activity(s, "ramu-1", "pick", TODAY - timedelta(days=1), today=TODAY)
    assert s.get_field("ramu-1").last_spray_date == TODAY - timedelta(days=12)


def test_log_activity_defaults_to_today_and_returns_state():
    s = MemoryStore()
    new_field(s)
    r = service.log_activity(s, "ramu-1", "spray", product="mancozeb", today=TODAY)
    assert r["logged"]["on_date"] == TODAY.isoformat()
    assert r["days_since_last_spray"] == 0
    assert r["recent_activities"][0]["product"] == "mancozeb"
    assert r["warnings"] == []


@pytest.mark.parametrize("kwargs,fragment", [
    ({"kind": "dance"}, "kind must be"),
    ({"kind": "spray", "on_date": TODAY + timedelta(days=1)}, "future"),
    ({"kind": "spray", "on_date": TODAY - timedelta(days=100)}, "before this field was sown"),
    ({"kind": "note", "notes": "x" * 501}, "Invalid activity"),
])
def test_log_activity_rejects_bad_input(kwargs, fragment):
    s = MemoryStore()
    new_field(s)
    r = service.log_activity(s, "ramu-1", today=TODAY, **kwargs)
    assert fragment in r["error"]
    assert s.list_activities("ramu-1") == []


def test_log_activity_unknown_field():
    assert "Unknown field_id" in service.log_activity(MemoryStore(), "nope", "spray")["error"]


def test_close_spray_is_logged_with_warning():
    s = MemoryStore()
    new_field(s)
    service.log_activity(s, "ramu-1", "spray", TODAY - timedelta(days=3), today=TODAY)
    r = service.log_activity(s, "ramu-1", "spray", TODAY, today=TODAY)
    assert len(r["warnings"]) == 1 and "only 3 days" in r["warnings"][0]
    assert len(s.list_activities("ramu-1")) == 2


@pytest.mark.parametrize("kwargs,fragment", [
    ({"field_id": "Bad Id"}, "field_id must be"),
    ({"field_id": "demo-1"}, "already exists"),
    ({"sowing_date": TODAY + timedelta(days=1)}, "future"),
    ({"lat": 123.0}, "lat must be"),
    ({"village": "  "}, "cannot be empty"),
])
def test_register_field_validation(kwargs, fragment):
    base = dict(field_id="ok-1", farmer="R", variety="Teja", village="V", lat=16.3, lng=80.4,
                sowing_date=TODAY - timedelta(days=5))
    base.update(kwargs)
    assert fragment in service.register_field(MemoryStore(), today=TODAY, **base)["error"]


def test_logged_spray_changes_the_advice(client):
    """End to end: spraying today makes the crop stage agent block another spray."""

    c = client
    c.post("/api/fields", json={"field_id": "e2e-1", "farmer": "R", "variety": "Teja",
                                "village": "V", "lat": 16.3, "lng": 80.4,
                                "sowing_date": (date.today() - timedelta(days=40)).isoformat()})
    q = {"field_id": "e2e-1", "question": "Should I spray tomorrow?"}
    stage = lambda d: next(r for r in d["reports"] if r["agent"] == "crop_stage")
    assert stage(c.post("/api/advice", json=q).json())["evidence"]["days_since_last_spray"] is None
    assert c.post("/api/fields/e2e-1/activities", json={"kind": "spray"}).status_code == 201
    after = stage(c.post("/api/advice", json=q).json())
    assert after["evidence"]["days_since_last_spray"] == 0
    assert after["evidence"]["spray_allowed"] is False


def test_rest_errors(client):

    c = client
    assert c.get("/api/fields/nope").status_code == 404
    assert c.post("/api/fields/nope/activities", json={"kind": "spray"}).status_code == 404
    assert c.post("/api/fields/demo-1/activities", json={"kind": "dance"}).status_code == 400
    assert c.get("/api/fields/demo-1").json()["days_since_last_spray"] == 6


def test_mcp_log_activity_tool():
    from mcp import Client

    from pantachevi.server import mcp
    import json, asyncio

    async def run():
        async with Client(mcp) as c:
            res = await c.call_tool("log_activity", {"field_id": "demo-1", "kind": "note", "notes": "leaf curl"})
            return json.loads(res.content[0].text)

    out = asyncio.run(run())
    assert out["logged"]["kind"] == "note" and out["recent_activities"][0]["notes"] == "leaf curl"
