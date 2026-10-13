"""Forecast provider: Open-Meteo, with a safe fallback to stub data.

Source is chosen by PANTACHEVI_WEATHER:
  live (default)  call Open-Meteo, fall back to the stub if the call fails
  stub            always use the scripted stub forecast (tests, scripted demo)

The weather agent decides on the WORST hour in the next 24 hours: the highest
rain probability and the highest wind speed. That is deliberately conservative
for spraying. It is a choice made here, not a verified agronomic rule.

Open-Meteo's free API is for non-commercial use. Check its terms before any
commercial deployment.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

from . import stubs

log = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 5.0
CACHE_TTL_SECONDS = 30 * 60
WINDOW_HOURS = 24

_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def parse_open_meteo(payload: dict, now_local: datetime | None = None) -> dict:
    """Turn an Open-Meteo hourly response into the forecast dict the agent uses.

    Raises ValueError if the payload does not contain a usable 24 hour window.
    `now_local` is naive local time at the location (the API returns naive
    local timestamps); it is derived from utc_offset_seconds when not given.
    """
    try:
        hourly = payload["hourly"]
        times = hourly["time"]
        rain = hourly["precipitation_probability"]
        wind = hourly["wind_speed_10m"]
        temp = hourly["temperature_2m"]
        offset = int(payload.get("utc_offset_seconds", 0))
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unexpected Open-Meteo payload: {exc!r}") from exc

    if not (len(times) == len(rain) == len(wind) == len(temp)):
        raise ValueError("Open-Meteo hourly arrays have different lengths")

    if now_local is None:
        now_local = (datetime.now(timezone.utc) + timedelta(seconds=offset)).replace(tzinfo=None)
    start = now_local.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=WINDOW_HOURS)

    window = []
    for t, r, w, tc in zip(times, rain, wind, temp):
        stamp = datetime.fromisoformat(t)
        if start <= stamp < end and r is not None and w is not None:
            window.append((stamp, float(r), float(w), tc))

    if len(window) < WINDOW_HOURS // 2:
        raise ValueError(f"only {len(window)} usable hours in the next {WINDOW_HOURS}")

    peak_rain = max(window, key=lambda row: row[1])
    peak_wind = max(w for _, _, w, _ in window)
    first_temp = window[0][3]

    return {
        "source": "open-meteo",
        "rain_probability_pct": round(peak_rain[1]),
        "rain_hour_local": peak_rain[0].strftime("%H:%M") if peak_rain[1] > 0 else None,
        "wind_kmh": round(peak_wind, 1),
        "temp_c": round(first_temp, 1) if first_temp is not None else None,
        "window_hours": len(window),
    }


def fetch_open_meteo(
    lat: float,
    lng: float,
    client: httpx.Client | None = None,
    now_local: datetime | None = None,
) -> dict:
    params = {
        "latitude": lat,
        "longitude": lng,
        "hourly": "precipitation_probability,wind_speed_10m,temperature_2m",
        "forecast_days": 2,
        "timezone": "auto",
        "wind_speed_unit": "kmh",
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        resp = client.get(API_URL, params=params)
        resp.raise_for_status()
        return parse_open_meteo(resp.json(), now_local)
    finally:
        if owns_client:
            client.close()


def get_forecast(lat: float, lng: float, client: httpx.Client | None = None) -> dict:
    """Return a forecast dict. Never raises: any failure falls back to the stub
    and says so in `source` ("stub-fallback") and `fallback_reason`."""
    mode = os.environ.get("PANTACHEVI_WEATHER", "live").strip().lower()
    if mode == "stub":
        return stubs.stub_forecast(lat, lng)

    key = (round(lat, 2), round(lng, 2))
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]

    try:
        forecast = fetch_open_meteo(lat, lng, client=client)
    except Exception as exc:  # network, HTTP status, bad JSON, bad payload
        log.warning("Open-Meteo unavailable, using stub forecast: %r", exc)
        fallback = stubs.stub_forecast(lat, lng)
        fallback["source"] = "stub-fallback"
        fallback["fallback_reason"] = type(exc).__name__
        return fallback  # not cached, so the next request tries live again

    with _cache_lock:
        _cache[key] = (time.monotonic(), forecast)
    return forecast
