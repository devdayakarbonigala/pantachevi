from __future__ import annotations

from ..data.weather_provider import get_forecast
from ..models import AgentReport, Field_
from ..rules import rule_is_sample, rule_value

CONFIDENCE_BY_SOURCE = {"open-meteo": 0.8, "stub": 0.6, "stub-fallback": 0.4}


def weather_report(field: Field_, forecast: dict | None = None) -> AgentReport:
    forecast = forecast or get_forecast(field.lat, field.lng)
    max_rain = rule_value("weather", "max_rain_probability_pct")
    max_wind = rule_value("weather", "max_wind_kmh")
    rain = forecast["rain_probability_pct"]
    wind = forecast["wind_kmh"]

    problems = []
    if rain > max_rain:
        problems.append(f"rain chance {rain}% is above the {max_rain:g}% limit")
    if wind > max_wind:
        problems.append(f"wind {wind} km/h is above the {max_wind:g} km/h limit")

    if problems:
        status, summary = "unfavourable", "Not a good spraying window: " + "; ".join(problems) + "."
    else:
        status, summary = "favourable", f"Good spraying window: rain chance {rain}%, wind {wind} km/h."

    source = forecast.get("source", "unknown")
    if source == "stub-fallback":
        summary += " (Live forecast was unavailable, so this uses placeholder data.)"

    return AgentReport(
        agent="weather",
        status=status,
        summary=summary,
        evidence={
            "rain_probability_pct": rain,
            "wind_kmh": wind,
            "rain_hour_local": forecast.get("rain_hour_local"),
            "data_source": source,
        },
        confidence=CONFIDENCE_BY_SOURCE.get(source, 0.5),
        uses_sample_rules=rule_is_sample("weather", "max_rain_probability_pct")
        or rule_is_sample("weather", "max_wind_kmh"),
    )
