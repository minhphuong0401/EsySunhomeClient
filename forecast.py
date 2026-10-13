#!/usr/bin/env python3
"""Solar PV forecast from Open-Meteo weather and a pvlib PVWatts model.

System settings come from PV_* environment variables (GitHub repository variables).
Run from the repository root with ``python forecast.py [days]`` to print the forecast.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, fields
from datetime import date
from typing import Any

import pandas as pd
import pvlib

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
# Archived model runs (also covering the next few days), used to rebuild past plans.
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
MAX_FORECAST_DAYS = 16
GAMMA_PDC = -0.004


@dataclass(frozen=True)
class PvSystem:
    latitude: float
    longitude: float
    tilt: float
    # pvlib convention: 0 = north, 90 = east, 180 = south, 270 = west.
    azimuth: float
    kwp: float
    inverter_kw: float
    system_loss: float


def load_system() -> PvSystem:
    names = {field.name: f"PV_{field.name.upper()}" for field in fields(PvSystem)}
    missing = [name for name in names.values() if not os.environ.get(name)]
    if missing:
        raise ValueError(f"Missing PV settings: {', '.join(missing)}")
    return PvSystem(**{field: float(os.environ[name]) for field, name in names.items()})


def forecast_power(
    system: PvSystem, days: int = 3, start: date | None = None, end: date | None = None
) -> pd.Series:
    """Return AC power (kW) per hour, indexed by the hour's UTC midpoint.

    Uses the live forecast for the next `days`, or archived forecasts for the UTC dates start..end.
    """
    if start is not None and end is not None:
        url, period = HISTORICAL_FORECAST_URL, {"start_date": start.isoformat(), "end_date": end.isoformat()}
    elif 1 <= days <= MAX_FORECAST_DAYS:
        url, period = OPEN_METEO_URL, {"forecast_days": days}
    else:
        raise ValueError(f"days must be between 1 and {MAX_FORECAST_DAYS}")
    query = urllib.parse.urlencode(
        {
            "latitude": system.latitude,
            "longitude": system.longitude,
            "hourly": "temperature_2m,wind_speed_10m,shortwave_radiation,direct_normal_irradiance,diffuse_radiation",
            **period,
            "timezone": "UTC",
            "wind_speed_unit": "ms",
        }
    )
    with urllib.request.urlopen(f"{url}?{query}", timeout=30) as response:
        raw = json.load(response)

    df = pd.DataFrame(raw["hourly"])
    df = df.set_index(pd.to_datetime(df.pop("time"))).tz_localize("UTC")
    df = df.rename(
        columns={
            "temperature_2m": "temp_air",
            "wind_speed_10m": "wind_speed",
            "shortwave_radiation": "ghi",
            "direct_normal_irradiance": "dni",
            "diffuse_radiation": "dhi",
        }
    )
    # Radiation is the mean of the preceding hour, so model the sun at that hour's midpoint.
    df.index = df.index - pd.Timedelta(minutes=30)

    solpos = pvlib.solarposition.get_solarposition(df.index, system.latitude, system.longitude)
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=system.tilt,
        surface_azimuth=system.azimuth,
        solar_zenith=solpos["apparent_zenith"],
        solar_azimuth=solpos["azimuth"],
        dni=df["dni"],
        ghi=df["ghi"],
        dhi=df["dhi"],
        dni_extra=pvlib.irradiance.get_extra_radiation(df.index),
        model="haydavies",
    )["poa_global"].fillna(0)
    temp_cell = pvlib.temperature.sapm_cell(
        poa,
        df["temp_air"],
        df["wind_speed"],
        **pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"]["open_rack_glass_glass"],
    )
    pdc = pvlib.pvsystem.pvwatts_dc(poa, temp_cell, system.kwp * 1000, GAMMA_PDC)
    # Panels (kWp, DC) can exceed the inverter rating, which caps AC output.
    power_w = (pdc * (1 - system.system_loss)).clip(lower=0, upper=system.inverter_kw * 1000)
    return (power_w / 1000).fillna(0)


def half_hour_forecasts(
    system: PvSystem, days: int = 3, start: date | None = None, end: date | None = None
) -> list[dict[str, Any]]:
    """Return the forecast as 30-minute slots (UTC period_end, average kW)."""
    forecasts = []
    for midpoint, kw in forecast_power(system, days, start, end).items():
        for period_end in (midpoint, midpoint + pd.Timedelta(minutes=30)):
            forecasts.append(
                {
                    "period_end": period_end.isoformat().replace("+00:00", "Z"),
                    "pv_estimate": round(float(kw), 4),
                }
            )
    return forecasts


def main() -> int:
    from scripts.build_history import load_tariff

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    try:
        power = forecast_power(load_system(), days).tz_convert(load_tariff().timezone)
    except (OSError, ValueError, KeyError) as error:
        print(f"Could not build PV forecast: {error}", file=sys.stderr)
        return 1

    daily_kwh = power.resample("D").sum().round(1)
    print("=== Hourly AC power (kW, daytime) ===")
    print(power[power > 0].round(2).to_string())
    print("\n=== Daily forecast (kWh) ===")
    print(daily_kwh.to_string())
    print(f"\nTotal {days} days: {daily_kwh.sum():.1f} kWh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())