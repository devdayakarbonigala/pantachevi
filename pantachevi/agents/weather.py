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

    problems, problems_te = [], []
    if rain > max_rain:
        problems.append(f"rain chance {rain}% is above the {max_rain:g}% limit")
        problems_te.append(f"వర్షం అవకాశం {rain}% ({max_rain:g}% పరిమితి కంటే ఎక్కువ)")
    if wind > max_wind:
        problems.append(f"wind {wind} km/h is above the {max_wind:g} km/h limit")
        problems_te.append(f"గాలి వేగం {wind} కి.మీ/గంట ({max_wind:g} కి.మీ/గంట పరిమితి కంటే ఎక్కువ)")

    if problems:
        status = "unfavourable"
        summary = "Not a good spraying window: " + "; ".join(problems) + "."
        summary_te = "పిచికారీకి మంచి సమయం కాదు: " + "; ".join(problems_te) + "."
    else:
        status = "favourable"
        summary = f"Good spraying window: rain chance {rain}%, wind {wind} km/h."
        summary_te = f"పిచికారీకి మంచి సమయం: వర్షం అవకాశం {rain}%, గాలి వేగం {wind} కి.మీ/గంట."

    source = forecast.get("source", "unknown")
    if source == "stub-fallback":
        summary += " (Live forecast was unavailable, so this uses placeholder data.)"
        summary_te += " (ప్రత్యక్ష వాతావరణ సూచన దొరకలేదు, అందుకే నమూనా సమాచారం వాడాను.)"

    return AgentReport(
        agent="weather",
        status=status,
        summary=summary,
        summary_te=summary_te,
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
