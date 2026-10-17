#!/usr/bin/env python3
"""Dry-run BYD charging advice for tomorrow's trips and daytime solar surplus."""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, fields
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.build_history import REPOSITORY_ROOT, _git_snapshot_contents, _parse_timestamp, load_tariff
from scripts.plan_night_charge import (
    SLOT,
    _charge_battery,
    _floor_slot,
    _iso,
    _load_history,
    _parse_utc,
    _quantile,
    _slot_index,
    build_load_profile,
    cheap_window,
    load_config as load_home_config,
    load_forecast,
)


CONFIG_FILE = REPOSITORY_ROOT / "config" / "ev_charge.json"
VEHICLE_FILE = REPOSITORY_ROOT / "data" / "byd.json"
HOME_FILE = REPOSITORY_ROOT / "data" / "data.json"
PLAN_FILE = REPOSITORY_ROOT / "data" / "ev_charge_plan.json"


@dataclass(frozen=True)
class EvConfig:
    capacity_kwh: float
    min_soc_percent: float
    max_current_amps: int
    voltage_v: float
    charge_efficiency: float
    daytime_home_start: str
    daytime_home_end: str
    fallback_daily_km: float
    fallback_consumption_kwh_per_100km: float
    distance_quantile: float
    history_days: int
    max_vehicle_age_hours: float
    solar_soc_cap_percent: float


def load_ev_config(path: Path = CONFIG_FILE) -> EvConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {field.name for field in fields(EvConfig)}:
        raise ValueError("Invalid EV charge configuration")
    config = EvConfig(**raw)
    start, end = time.fromisoformat(config.daytime_home_start), time.fromisoformat(config.daytime_home_end)
    if (
        config.capacity_kwh <= 0 or not 0 <= config.min_soc_percent < 100
        or type(config.max_current_amps) is not int or not 6 <= config.max_current_amps <= 32
        or config.voltage_v <= 0 or not 0 < config.charge_efficiency <= 1
        or start >= end or start.minute % 30 or end.minute % 30 or start.second or end.second
        or config.fallback_daily_km <= 0 or config.fallback_consumption_kwh_per_100km <= 0
        or not 0 <= config.distance_quantile <= 1 or config.history_days < 2
        or config.max_vehicle_age_hours <= 0
        or not config.min_soc_percent < config.solar_soc_cap_percent <= 100
    ):
        raise ValueError("Invalid EV charge configuration values")
    return config


def daily_distances(
    snapshots: list[dict[str, Any]], tz: Any, config: EvConfig
) -> dict[int, float]:
    readings: dict[date, float] = {}
    for snapshot in sorted(snapshots, key=lambda item: item["fetchedAt"]):
        day = _parse_utc(snapshot["fetchedAt"]).astimezone(tz).date()
        odometer = float(snapshot["odometerKm"])
        if math.isfinite(odometer) and odometer >= 0:
            readings[day] = odometer
    samples: dict[int, list[float]] = {weekday: [] for weekday in range(7)}
    for day, odometer in readings.items():
        previous = readings.get(day - timedelta(days=1))
        if previous is not None and 0 <= odometer - previous <= 500:
            samples[day.weekday()].append(odometer - previous)
    all_distances = [distance for values in samples.values() for distance in values]
    return {
        weekday: max(
            config.fallback_daily_km,
            _quantile(values if len(values) >= 3 else all_distances, config.distance_quantile),
        ) if len(values) >= 3 or all_distances else config.fallback_daily_km
        for weekday, values in samples.items()
    }


def solar_surplus(
    start: datetime,
    end: datetime,
    home_soc: float,
    forecasts: list[dict[str, Any]],
    profile: Any,
    tariff: Any,
    home_config: Any,
) -> dict[datetime, float]:
    pv_by_slot = {_parse_utc(item["period_end"]) - SLOT: item["pv_estimate"] for item in forecasts}
    capacity = home_config.battery_capacity_kwh
    energy = home_soc / 100 * capacity
    floor = home_config.battery_min_soc / 100 * capacity
    surplus: dict[datetime, float] = {}
    cursor = _floor_slot(start)
    while cursor < end:
        slot_pv = pv_by_slot.get(cursor, 0.0) * 0.5 * home_config.worst_case_pv_factor
        slot_load = profile.worst[_slot_index(cursor, tariff.timezone)]
        net = slot_pv - slot_load
        if net > 0:
            energy, surplus[cursor] = _charge_battery(energy, net, 0.5, home_config)
        else:
            energy = max(floor, energy - min(-net, home_config.battery_max_discharge_kw * 0.5) / home_config.discharge_efficiency)
        cursor += SLOT
    return surplus


def _local_window(day: date, start: time, end: time, tz: Any) -> tuple[datetime, datetime]:
    return (
        datetime.combine(day, start, tzinfo=tz).astimezone(timezone.utc),
        datetime.combine(day, end, tzinfo=tz).astimezone(timezone.utc),
    )


def build_ev_plan(
    now: datetime,
    vehicle: dict[str, Any],
    distances: dict[int, float],
    config: EvConfig,
    tariff: Any,
    available_solar: dict[datetime, float],
    warnings: list[str],
) -> dict[str, Any]:
    reading = _parse_utc(vehicle["fetchedAt"])
    vehicle_time = _parse_utc(vehicle["vehicleTime"]) if vehicle.get("vehicleTime") else None
    if (now - reading > timedelta(hours=config.max_vehicle_age_hours)
            or vehicle_time is None or now - vehicle_time > timedelta(hours=config.max_vehicle_age_hours)
            or vehicle_time > now + timedelta(minutes=5)):
        raise ValueError("BYD vehicle telemetry is missing or too old to recommend charging")
    soc = float(vehicle["socPercent"])
    if not math.isfinite(soc) or not 0 <= soc <= 100:
        raise ValueError("Invalid BYD SOC")
    consumption = vehicle.get("recent50kmKwhPer100km")
    if consumption is None or not math.isfinite(float(consumption)) or float(consumption) <= 0:
        consumption = config.fallback_consumption_kwh_per_100km
        warnings.append("Recent BYD consumption unavailable; using configured fallback.")
    consumption = float(consumption)

    tomorrow = now.astimezone(tariff.timezone).date() + timedelta(days=1)
    following = tomorrow + timedelta(days=1)
    night_start_minute, night_end_minute, night_rate = cheap_window(tariff)
    night_start, night_end = _local_window(
        tomorrow, time(night_start_minute // 60, night_start_minute % 60),
        time(night_end_minute // 60, night_end_minute % 60), tariff.timezone,
    )
    day_start, day_end = _local_window(
        tomorrow, time.fromisoformat(config.daytime_home_start),
        time.fromisoformat(config.daytime_home_end), tariff.timezone,
    )
    if now >= night_end:
        raise ValueError("Run the EV planner after the day's driving, before the next cheap window ends")
    tomorrow_km = distances[tomorrow.weekday()]
    following_km = distances[following.weekday()]
    energy_tomorrow = tomorrow_km * consumption / 100
    reserve_kwh = config.min_soc_percent / 100 * config.capacity_kwh
    required_night_kwh = reserve_kwh + energy_tomorrow
    available_hours = (night_end - max(night_start, now)).total_seconds() / 3600
    if required_night_kwh > config.capacity_kwh:
        warnings.append("Tomorrow's estimated drive plus reserve exceeds the vehicle battery capacity.")
    night_battery_kwh = min(config.capacity_kwh, max(0.0, required_night_kwh))
    needed_ac_kwh = max(0.0, night_battery_kwh - soc / 100 * config.capacity_kwh) / config.charge_efficiency
    night_kw = config.voltage_v * config.max_current_amps / 1000
    night_ac_kwh = min(needed_ac_kwh, night_kw * available_hours)
    night_minutes = math.ceil(night_ac_kwh / night_kw * 60) if night_ac_kwh > 0 else 0
    night_ac_kwh = min(
        night_kw * night_minutes / 60,
        (config.capacity_kwh - soc / 100 * config.capacity_kwh) / config.charge_efficiency,
    )
    night_finish = night_end if night_minutes else None
    night_begin = night_finish - timedelta(minutes=night_minutes) if night_finish else None
    if night_ac_kwh + 1e-6 < needed_ac_kwh:
        warnings.append("The required overnight charge cannot fit in the available cheap window.")
    soc_after_night = min(100.0, soc + night_ac_kwh * config.charge_efficiency / config.capacity_kwh * 100)
    soc_on_return = max(0.0, soc_after_night - energy_tomorrow / config.capacity_kwh * 100)

    required_following_kwh = min(config.capacity_kwh, reserve_kwh + following_km * consumption / 100)
    target_day_kwh = required_following_kwh
    if float(tariff.feed_in_rate) < night_rate:
        next_day_start, next_day_end = _local_window(
            following, time.fromisoformat(config.daytime_home_start),
            time.fromisoformat(config.daytime_home_end), tariff.timezone,
        )
        min_slot_kwh = config.voltage_v * 6 / 2000
        max_slot_kwh = night_kw * 0.5
        future_solar_kwh = sum(
            min(solar_kwh, max_slot_kwh) for slot, solar_kwh in available_solar.items()
            if next_day_start <= slot < next_day_end and solar_kwh >= min_slot_kwh
        ) * config.charge_efficiency
        later_kwh = sum(
            distances[(following + timedelta(days=offset)).weekday()] * consumption / 100
            for offset in (1, 2)
        )
        target_day_kwh = max(required_following_kwh, min(
            config.capacity_kwh * config.solar_soc_cap_percent / 100,
            required_following_kwh + max(0.0, later_kwh - future_solar_kwh),
        ))
    day_needed_ac = max(0.0, target_day_kwh - soc_on_return / 100 * config.capacity_kwh) / config.charge_efficiency
    day_slots = []
    for slot, solar_kwh in sorted(available_solar.items()):
        if not day_start <= slot < day_end or day_needed_ac <= 0:
            continue
        current = min(config.max_current_amps, math.floor(solar_kwh * 2000 / config.voltage_v))
        if current < 6:
            continue
        slot_kw = config.voltage_v * current / 1000
        energy_ac = min(day_needed_ac, slot_kw * 0.5)
        minutes = math.floor(energy_ac / slot_kw * 60)
        if minutes < 1:
            continue
        energy_ac = slot_kw * minutes / 60
        day_slots.append({
            "start": _iso(slot), "end": _iso(slot + timedelta(minutes=minutes)),
            "currentA": current, "energyFromSolar_kWh": round(energy_ac, 3),
        })
        day_needed_ac -= energy_ac

    day_ac_kwh = sum(slot["energyFromSolar_kWh"] for slot in day_slots)
    return {
        "generatedAt": _iso(now), "dryRun": True,
        "vehicleSoc": round(soc, 1), "vehicleFetchedAt": vehicle["fetchedAt"],
        "consumption50km_kWhPer100km": consumption,
        "minimumSoc": config.min_soc_percent,
        "tomorrow": {"date": tomorrow.isoformat(), "estimatedDistanceKm": round(tomorrow_km, 1),
                     "socAfterOvernightCharge": round(soc_after_night, 1),
                     "socAfterDriving": round(soc_on_return, 1)},
        "overnight": {
            "decision": "charge" if night_minutes else "no_charge",
            "start": _iso(night_begin) if night_begin else None,
            "end": _iso(night_finish) if night_finish else None,
            "currentA": config.max_current_amps if night_minutes else None,
            "durationMinutes": night_minutes,
            "energyFromGrid_kWh": round(night_ac_kwh, 2),
            "cost_AUD": round(night_ac_kwh * night_rate, 2),
        },
        "daytime": {
            "window": {"start": _iso(day_start), "end": _iso(day_end)},
            "decision": "charge" if day_slots else "no_charge",
            "source": "forecast solar surplus after house and home battery",
            "slots": day_slots,
            "energyFromSolar_kWh": round(day_ac_kwh, 2),
            "opportunityCost_AUD": round(day_ac_kwh * float(tariff.feed_in_rate), 2),
            "socAfterCharge": round(min(100, soc_on_return + day_ac_kwh * config.charge_efficiency / config.capacity_kwh * 100), 1),
            "estimatedNextDayKm": round(following_km, 1),
            "remainingEnergyBeforeNextNight_kWh": round(max(0, (
                required_following_kwh - soc_on_return / 100 * config.capacity_kwh
            ) / config.charge_efficiency - day_ac_kwh), 2),
        },
        "warnings": warnings,
    }


def main() -> int:
    try:
        now = datetime.now(timezone.utc)
        config = load_ev_config()
        tariff = load_tariff()
        vehicle = json.loads(VEHICLE_FILE.read_text(encoding="utf-8"))
        since = now - timedelta(days=config.history_days + 2)
        snapshots = []
        for _, content in _git_snapshot_contents(since, "data/byd.json"):
            try:
                snapshots.append(json.loads(content))
            except (ValueError, TypeError):
                continue
        snapshots.append(vehicle)
        distances = daily_distances(snapshots, tariff.timezone, config)
        warnings: list[str] = []
        if len({item["fetchedAt"][:10] for item in snapshots}) < 4:
            warnings.append("Not enough daily odometer history; using configured distance fallback.")

        available_solar: dict[datetime, float] = {}
        try:
            home = json.loads(HOME_FILE.read_text(encoding="utf-8"))
            home_time = _parse_timestamp(home.get("mqttCurrentTime"), "working tree")
            if now - home_time > timedelta(hours=3):
                raise ValueError("Home energy snapshot is too old")
            home_config = load_home_config()
            history = _load_history(now - timedelta(days=home_config.history_days), home_time)
            history.append((home_time, float(home["totalConsumptionToday_kWh"])))
            profile = build_load_profile(history, tariff.timezone, home_config)
            forecast = load_forecast(now, now - timedelta(hours=1), warnings)
            following = now.astimezone(tariff.timezone).date() + timedelta(days=2)
            day_end = _local_window(
                following, time.fromisoformat(config.daytime_home_start),
                time.fromisoformat(config.daytime_home_end), tariff.timezone,
            )[1]
            available_solar = solar_surplus(
                home_time, day_end, float(home["batterySoc_percent"]),
                forecast["forecasts"], profile, tariff, home_config,
            )
        except (OSError, KeyError, ValueError, RuntimeError, TypeError, ImportError) as error:
            warnings.append(f"Daytime surplus unavailable ({error}); overnight advice only.")

        plan = build_ev_plan(now, vehicle, distances, config, tariff, available_solar, warnings)
        PLAN_FILE.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    except (OSError, KeyError, ValueError, RuntimeError, TypeError, ImportError) as error:
        print(f"Could not plan EV charge: {error}", file=sys.stderr)
        return 1
    print(f"EV charge plan: overnight {plan['overnight']['decision']}, daytime {plan['daytime']['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())