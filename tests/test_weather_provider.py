from datetime import datetime, timedelta

import httpx
import pytest

from pantachevi.agents.weather import weather_report
from pantachevi.data import weather_provider as wp
from pantachevi.models import Field_

NOW = datetime(2026, 10, 13, 12, 20)  # local time at the field


def payload(rain=None, wind=None, temp=None, hours=48, start=datetime(2026, 10, 13, 0, 0), offset=19800):
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(hours)]
    rain = rain or [0] * hours
    wind = wind or [5.0] * hours
    temp = temp or [30.0] * hours
    return {
        "utc_offset_seconds": offset,
        "hourly": {
            "time": times,
            "precipitation_probability": rain,
            "wind_speed_10m": wind,
            "temperature_2m": temp,
        },
    }


def field() -> Field_:
    return Field_(id="t", farmer="t", variety="Teja", village="x", lat=16.3, lng=80.4,
                  sowing_date=NOW.date() - timedelta(days=98), mandi="Guntur")


@pytest.fixture(autouse=True)
def live_mode(monkeypatch):
    monkeypatch.setenv("PANTACHEVI_WEATHER", "live")
    wp.clear_cache()
    yield
    wp.clear_cache()


def test_parse_takes_worst_hour_in_next_24h():
    rain = [0] * 48
    rain[15] = 70   # 15:00 today, inside the window
    rain[40] = 95   # 16:00 tomorrow, outside the window (window ends 12:00 tomorrow)
    wind = [5.0] * 48
    wind[20] = 18.5  # 20:00 today
    got = wp.parse_open_meteo(payload(rain=rain, wind=wind), NOW)
    assert got["source"] == "open-meteo"
    assert got["rain_probability_pct"] == 70
    assert got["rain_hour_local"] == "15:00"
    assert got["wind_kmh"] == 18.5
    assert got["window_hours"] == 24


def test_parse_ignores_past_hours():
    rain = [0] * 48
    rain[3] = 100  # 03:00 today, already past
    got = wp.parse_open_meteo(payload(rain=rain), NOW)
    assert got["rain_probability_pct"] == 0
    assert got["rain_hour_local"] is None


def test_parse_skips_null_values():
    rain = [None] * 12 + [10] * 36
    got = wp.parse_open_meteo(payload(rain=rain), NOW)
    assert got["rain_probability_pct"] == 10


def test_parse_rejects_bad_payloads():
    with pytest.raises(ValueError):
        wp.parse_open_meteo({"nope": 1}, NOW)
    bad = payload()
    bad["hourly"]["wind_speed_10m"] = [1.0]
    with pytest.raises(ValueError):
        wp.parse_open_meteo(bad, NOW)
    with pytest.raises(ValueError):  # forecast ends before the window starts
        wp.parse_open_meteo(payload(hours=6), NOW)


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_sends_expected_query():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=payload())

    wp.fetch_open_meteo(16.3067, 80.4365, client=make_client(handler), now_local=NOW)
    assert seen["hourly"] == "precipitation_probability,wind_speed_10m,temperature_2m"
    assert seen["wind_speed_unit"] == "kmh"
    assert seen["forecast_days"] == "2"
    assert seen["latitude"] == "16.3067"


def test_get_forecast_falls_back_on_http_error():
    got = wp.get_forecast(16.3, 80.4, client=make_client(lambda r: httpx.Response(503)))
    assert got["source"] == "stub-fallback"
    assert got["fallback_reason"] == "HTTPStatusError"


def test_get_forecast_falls_back_on_network_error():
    def boom(request):
        raise httpx.ConnectError("no network")

    got = wp.get_forecast(16.3, 80.4, client=make_client(boom))
    assert got["source"] == "stub-fallback"


def test_get_forecast_falls_back_on_garbage_json():
    got = wp.get_forecast(16.3, 80.4, client=make_client(lambda r: httpx.Response(200, json={"hello": 1})))
    assert got["source"] == "stub-fallback"


def test_stub_mode_never_calls_network(monkeypatch):
    monkeypatch.setenv("PANTACHEVI_WEATHER", "stub")

    def boom(request):
        raise AssertionError("network must not be used in stub mode")

    got = wp.get_forecast(16.3, 80.4, client=make_client(boom))
    assert got["source"] == "stub"


def test_live_result_is_cached(monkeypatch):
    calls = []
    now_local = datetime.now()

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=payload(start=now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                                                - timedelta(days=0), offset=0))

    # Build a response that is valid relative to "now" so the 24h window is full.
    monkeypatch.setattr(wp, "parse_open_meteo", lambda p, n=None: {"source": "open-meteo", "rain_probability_pct": 1,
                                                                    "wind_kmh": 1, "window_hours": 24})
    client = make_client(handler)
    wp.get_forecast(16.3, 80.4, client=client)
    wp.get_forecast(16.3, 80.4, client=client)
    assert len(calls) == 1


def test_fallback_is_not_cached():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    client = make_client(handler)
    wp.get_forecast(16.3, 80.4, client=client)
    wp.get_forecast(16.3, 80.4, client=client)
    assert len(calls) == 2


def test_agent_reports_fallback_honestly():
    fb = {"source": "stub-fallback", "rain_probability_pct": 70, "wind_kmh": 9}
    r = weather_report(field(), fb)
    assert r.confidence == 0.4
    assert "placeholder data" in r.summary
    live = weather_report(field(), {"source": "open-meteo", "rain_probability_pct": 10, "wind_kmh": 5})
    assert live.confidence == 0.8
    assert "placeholder" not in live.summary
