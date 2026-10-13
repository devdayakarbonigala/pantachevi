from datetime import date, timedelta

import pytest

from pantachevi import service
from pantachevi.agents.market import market_report
from pantachevi.data.prices import get_prices
from pantachevi.models import Field_
from pantachevi.store import MemoryStore

TODAY = date(2026, 10, 13)


def fld(mandi="Guntur"):
    return Field_(id="t", farmer="t", variety="Teja", village="x", lat=16.3, lng=80.4,
                  sowing_date=TODAY - timedelta(days=60), mandi=mandi)


def put(store, days_ago, price, mandi="Guntur"):
    r = service.log_price(store, mandi, price, TODAY - timedelta(days=days_ago), today=TODAY)
    assert "error" not in r, r


def report(store, mandi="Guntur"):
    return market_report(fld(mandi), prices=get_prices(store, mandi, TODAY))


def test_no_price_is_silent_and_says_how_to_fix_it():
    r = report(MemoryStore())
    assert r.status == "caution" and r.confidence == 0.1
    assert r.evidence["has_data"] is False and "Enter today's price" in r.summary


def test_stale_price_is_not_used():
    s = MemoryStore()
    put(s, 5, 16000)
    r = report(s)
    assert r.evidence["has_data"] is False and "too old" in r.summary


def test_single_price_gives_no_trend():
    s = MemoryStore()
    put(s, 0, 16000)
    r = report(s)
    assert r.status == "caution" and "no earlier price" in r.summary and r.evidence["has_data"] is True


def test_rising_falling_flat_from_typed_prices():
    for now, expect in ((16200, "favourable"), (14000, "unfavourable"), (15100, "caution")):
        s = MemoryStore()
        put(s, 7, 15000)
        put(s, 0, now)
        r = report(s)
        assert r.status == expect and r.evidence["trend_days"] == 7 and r.confidence == 0.75


def test_baseline_picks_entry_nearest_seven_days():
    s = MemoryStore()
    put(s, 10, 12000)
    put(s, 8, 15000)
    put(s, 2, 15500)   # too close to count as a baseline
    put(s, 0, 16500)
    v = get_prices(s, "Guntur", TODAY)
    assert v["price_7d_ago_per_quintal"] == 15000 and v["baseline_days"] == 8


def test_same_day_entry_is_a_correction():
    s = MemoryStore()
    put(s, 0, 16000)
    put(s, 0, 16500)
    assert [p.price_per_quintal for p in s.list_prices("Guntur")] == [16500]


def test_mandis_are_separate():
    s = MemoryStore()
    put(s, 0, 16000, "Guntur")
    assert get_prices(s, "Warangal", TODAY)["source"] == "none"


@pytest.mark.parametrize("kwargs,fragment", [
    ({"price_per_quintal": 500}, "must be between"),
    ({"price_per_quintal": 162000}, "must be between"),
    ({"price_per_quintal": 16000, "on_date": TODAY + timedelta(days=1)}, "future"),
    ({"price_per_quintal": 16000, "on_date": TODAY - timedelta(days=40)}, "more than 30 days"),
    ({"mandi": "  ", "price_per_quintal": 16000}, "mandi cannot be empty"),
])
def test_log_price_rejects_bad_input(kwargs, fragment):
    args = {"mandi": "Guntur", **kwargs}
    r = service.log_price(MemoryStore(), today=TODAY, **args)
    assert fragment in r["error"]


def test_big_jump_warns_but_saves():
    s = MemoryStore()
    put(s, 1, 16000)
    r = service.log_price(s, "Guntur", 26000, TODAY, today=TODAY)
    assert len(r["warnings"]) == 1 and "typing mistake" in r["warnings"][0]
    assert s.list_prices("Guntur")[0].price_per_quintal == 26000


def test_no_price_does_not_create_a_conflict(client):
    """Missing market data must not show up as the agents disagreeing."""
    f = client.post("/api/fields", json={"field_id": "p-1", "farmer": "R", "variety": "Teja", "village": "V",
                                         "lat": 16.3, "lng": 80.4, "mandi": "Guntur",
                                         "sowing_date": (date.today() - timedelta(days=40)).isoformat()})
    assert f.status_code == 201
    d = client.post("/api/advice", json={"field_id": "p-1", "question": "Should I spray tomorrow?"}).json()
    market = next(r for r in d["reports"] if r["agent"] == "market")
    assert market["evidence"]["has_data"] is False
    assert "market says" not in (d["verdict"]["conflict_detail"] or "")


def test_typed_prices_change_the_advice_end_to_end(client):
    client.post("/api/fields", json={"field_id": "p-2", "farmer": "R", "variety": "Teja", "village": "V",
                                     "lat": 16.3, "lng": 80.4, "mandi": "Mirchi Yard",
                                     "sowing_date": (date.today() - timedelta(days=98)).isoformat()})
    for days, price in ((7, 15000), (0, 16200)):
        r = client.post("/api/prices", json={"mandi": "Mirchi Yard", "price_per_quintal": price,
                                             "on_date": (date.today() - timedelta(days=days)).isoformat()})
        assert r.status_code == 201
    d = client.post("/api/advice", json={"field_id": "p-2", "question": "pick?"}).json()
    market = next(r for r in d["reports"] if r["agent"] == "market")
    assert market["status"] == "favourable" and market["evidence"]["data_source"] == "farmer-entered"
    assert client.post("/api/prices", json={"mandi": "Mirchi Yard", "price_per_quintal": 5}).status_code == 400
    assert client.get("/api/prices/Mirchi Yard").json()["market_view"]["price_now_per_quintal"] == 16200


def test_demo_field_keeps_its_scripted_market_story():
    s = MemoryStore()
    v = get_prices(s, "Guntur (demo)")
    assert v["price_now_per_quintal"] == 16200 and v["price_7d_ago_per_quintal"] == 15000
    assert get_prices(s, "Guntur")["source"] == "none"  # demo seed does not leak into real Guntur


def test_mcp_log_price_tool():
    import asyncio, json
    from mcp import Client
    from pantachevi.server import mcp

    async def run():
        async with Client(mcp) as c:
            res = await c.call_tool("log_price", {"mandi": "Guntur", "price_per_quintal": 16100})
            return json.loads(res.content[0].text)

    out = asyncio.run(run())
    assert out["logged"]["price_per_quintal"] == 16100 and out["market_view"]["source"] == "farmer-entered"


def test_delete_price_removes_entry_and_changes_the_view():
    s = MemoryStore()
    put(s, 7, 15000)
    put(s, 0, 16200)
    assert report(s).status == "favourable"
    r = service.delete_price(s, "Guntur", TODAY, today=TODAY)
    assert r["deleted"]["on_date"] == TODAY.isoformat()
    assert report(s).evidence["has_data"] is False  # only the week-old entry is left, and it is too old
    assert "No price entered" in service.delete_price(s, "Guntur", TODAY, today=TODAY)["error"]


def test_delete_price_over_rest_and_mcp(client):
    import asyncio, json
    from mcp import Client
    from pantachevi.server import mcp

    client.post("/api/prices", json={"mandi": "Tenali", "price_per_quintal": 15000})
    d = date.today().isoformat()
    assert client.delete(f"/api/prices/Tenali/{d}").status_code == 200
    assert client.delete(f"/api/prices/Tenali/{d}").status_code == 404
    client.post("/api/prices", json={"mandi": "Tenali", "price_per_quintal": 15000})

    async def run():
        async with Client(mcp) as c:
            res = await c.call_tool("delete_price", {"mandi": "Tenali", "on_date": d})
            return json.loads(res.content[0].text)

    assert asyncio.run(run())["deleted"]["mandi"] == "Tenali"
