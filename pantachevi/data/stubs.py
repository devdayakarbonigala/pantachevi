"""Stub data for the day-1 build. Replaced by Open-Meteo, a mandi price feed
and PostgreSQL later. Every function returns plain dicts so the swap is local.

The demo field is dated relative to today so the demo scenario stays stable:
98 days after sowing, last sprayed 6 days ago.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..models import Field_

DEMO_FIELD_ID = "demo-1"


def demo_fields(today: date | None = None) -> dict[str, Field_]:
    today = today or date.today()
    demo = Field_(
        id=DEMO_FIELD_ID,
        farmer="Demo farmer",
        variety="Teja",
        village="Guntur (demo)",
        lat=16.3067,
        lng=80.4365,
        sowing_date=today - timedelta(days=98),
        last_spray_date=today - timedelta(days=6),
        mandi="Guntur",
    )
    return {demo.id: demo}


def stub_forecast(lat: float, lng: float) -> dict:
    """Pretend 24-hour forecast: rain likely tomorrow afternoon."""
    return {
        "source": "stub",
        "rain_probability_pct": 70,
        "rain_hour_local": "14:00",
        "wind_kmh": 9,
        "temp_c": 31,
    }


def stub_prices(mandi: str) -> dict:
    """Pretend mandi prices: up 8 percent over seven days."""
    return {
        "source": "stub",
        "mandi": mandi,
        "price_now_per_quintal": 16200,
        "price_7d_ago_per_quintal": 15000,
    }
