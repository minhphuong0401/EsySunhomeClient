#!/usr/bin/env python3
"""Dry-run planner: decide whether to grid-charge the battery in the cheapest tariff window.

Run from the repository root with ``python -m scripts.plan_night_charge``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, fields
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.build_history import (
    REPOSITORY_ROOT,
    Tariff,
    _git_snapshot_contents,
    _parse_timestamp,
    load_tariff,
)


CONFIG_PATH = REPOSITORY_ROOT / "config" / "night_charge.json"
DATA_FILE = REPOSITORY_ROOT / "data" / "data.json"
FORECAST_FILE = REPOSITORY_ROOT / "data" / "solcast_forecast.json"
PLAN_FILE = REPOSITORY_ROOT / "data" / "night_charge_plan.json"
SOLCAST_URL = "https://api.solcast.com.au/rooftop_sites/{resource_id}/forecasts?format=json&hours=48"
SLOT = timedelta(minutes=30)
SLOTS_PER_DAY = 48
MAX_SNAPSHOT_GAP = timedelta(hours=2)
MAX_PLAUSIBLE_LOAD_KW = 20.0
MIN_SLOT_COVERAGE = 0.5
FULL_DAY_LAST_SNAPSHOT = time(23, 30)


@dataclass(frozen=True)
class LoadProfile:
    expected: list[float]
    worst: list[float]
    history_days: int
    full_days: int


@dataclass(frozen=True)
class PlannerConfig:
    battery_capacity_kwh: float
    expected_min_soc: float
    worst_case_min_soc: float
    worst_case_load_quantile: float
    daily_total_min_full_days: int
    worst_case_fallback_load_factor: float
    charge_efficiency: float
    discharge_efficiency: float
    min_grid_charge_kwh: float
    history_days: int
    planning_lead_hours: float


def load_config(path: Path = CONFIG_PATH) -> PlannerConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    expected = {field.name for field in fields(PlannerConfig)}
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError(f"{path} must define exactly: {', '.join(sorted(expected))}")
    return PlannerConfig(**raw)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _floor_slot(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    return value.replace(minute=value.minute // 30 * 30, second=0, microsecond=0)


def _slot_index(value: datetime, tz: ZoneInfo) -> int:
    local = value.astimezone(tz)
    return (local.hour * 60 + local.minute) // 30


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def cheap_window(tariff: Tariff) -> tuple[int, int, float]:
    period = min(tariff.periods, key=lambda item: item.rate)
    return period.start_minute, period.end_minute, float(period.rate)


def planning_window(now: datetime, tariff: Tariff, lead_hours: float) -> tuple[datetime, datetime] | None:
    """Return the UTC (start, end) of the cheap window to plan for, or None outside planning time."""
    start_minute, end_minute, _ = cheap_window(tariff)
    local_today = now.astimezone(tariff.timezone).date()
    for day in (local_today, local_today + timedelta(days=1)):
        midnight = datetime.combine(day, time.min, tzinfo=tariff.timezone)
        start = (midnight + timedelta(minutes=start_minute)).astimezone(timezone.utc)
        end = (midnight + timedelta(minutes=end_minute)).astimezone(timezone.utc)
        if start - timedelta(hours=lead_hours) <= now < end:
            return start, end
    return None


def build_load_profile(
    snapshots: list[tuple[datetime, float]],
    tz: ZoneInfo,
    config: PlannerConfig,
) -> LoadProfile:
    """Build expected and worst-case per-slot load profiles scaled to real daily totals.

    Per-slot medians only give the daily shape: summing them understates spiky days, and summing
    per-slot high quantiles stacks peaks that came from different days.
    """
    coverage: dict[tuple[date, int], list[float]] = {}
    last_reading: dict[date, tuple[datetime, float]] = {}
    previous_time: datetime | None = None
    previous_value = 0.0
    previous_day: date | None = None

    for timestamp, consumption in sorted(snapshots):
        day = timestamp.astimezone(tz).date()
        if day != previous_day:
            # Daily counters reset at local midnight.
            previous_time = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)
            previous_value = 0.0
        energy = consumption - previous_value
        duration = timestamp - previous_time
        hours = duration.total_seconds() / 3600
        if (
            energy >= 0
            and timedelta(0) < duration <= MAX_SNAPSHOT_GAP
            and energy / hours <= MAX_PLAUSIBLE_LOAD_KW
        ):
            cursor = previous_time
            while cursor < timestamp:
                segment_end = min(timestamp, _floor_slot(cursor) + SLOT)
                bucket = coverage.setdefault(
                    (cursor.astimezone(tz).date(), _slot_index(cursor, tz)), [0.0, 0.0]
                )
                bucket[0] += energy * ((segment_end - cursor) / duration)
                bucket[1] += (segment_end - cursor) / SLOT
                cursor = segment_end
        previous_time, previous_value, previous_day = timestamp, consumption, day
        last_reading[day] = (timestamp, consumption)

    by_slot: list[list[float]] = [[] for _ in range(SLOTS_PER_DAY)]
    for (_, slot), (energy, covered) in coverage.items():
        if covered >= MIN_SLOT_COVERAGE:
            by_slot[slot].append(energy / covered)
    all_values = [value for values in by_slot for value in values]
    if not all_values:
        raise ValueError("No usable consumption history to build a load profile.")

    shape = [_quantile(values or all_values, 0.5) for values in by_slot]
    # The daily counter is cumulative, so a late-evening reading gives the full-day total despite gaps.
    daily_totals = [
        value
        for timestamp, value in last_reading.values()
        if timestamp.astimezone(tz).time() >= FULL_DAY_LAST_SNAPSHOT
    ]
    if len(daily_totals) >= config.daily_total_min_full_days:
        expected_factor = _quantile(daily_totals, 0.5) / sum(shape)
        worst_factor = _quantile(daily_totals, config.worst_case_load_quantile) / sum(shape)
    else:
        expected_factor = 1.0
        worst_factor = config.worst_case_fallback_load_factor
    worst_factor = max(expected_factor, worst_factor)
    return LoadProfile(
        expected=[value * expected_factor for value in shape],
        worst=[value * worst_factor for value in shape],
        history_days=len({day for day, _ in coverage}),
        full_days=len(daily_totals),
    )


def _parse_period_end(value: str) -> datetime:
    # Solcast returns 7 fractional digits, e.g. 2026-10-11T04:00:00.0000000Z.
    return datetime.fromisoformat(value[:19]).replace(tzinfo=timezone.utc)


def fetch_solcast(api_key: str, resource_id: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        SOLCAST_URL.format(resource_id=urllib.parse.quote(resource_id, safe="")),
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return [
        {
            "period_end": _iso(_parse_period_end(item["period_end"])),
            "pv_estimate": float(item["pv_estimate"]),
            "pv_estimate10": float(item["pv_estimate10"]),
        }
        for item in payload["forecasts"]
    ]


def load_forecast(now: datetime, refresh_after: datetime, warnings: list[str]) -> dict[str, Any]:
    """Reuse the cached forecast if fetched after refresh_after; Solcast hobbyist plans allow ~10 calls/day."""
    cached: dict[str, Any] | None = None
    if FORECAST_FILE.exists():
        cached = json.loads(FORECAST_FILE.read_text(encoding="utf-8"))
        if _parse_utc(cached["fetchedAt"]) >= refresh_after:
            return cached

    api_key = os.environ.get("SOLCAST_API_KEY")
    resource_id = os.environ.get("SOLCAST_RESOURCE_ID")
    try:
        if not api_key or not resource_id:
            raise ValueError("SOLCAST_API_KEY and SOLCAST_RESOURCE_ID must be set")
        forecast = {"fetchedAt": _iso(now), "forecasts": fetch_solcast(api_key, resource_id)}
    except (OSError, ValueError, KeyError, TypeError) as error:
        if cached is None:
            raise RuntimeError(f"Solcast forecast unavailable: {error}") from error
        warnings.append(f"Solcast refresh failed ({error}); using forecast fetched at {cached['fetchedAt']}.")
        return cached

    FORECAST_FILE.write_text(json.dumps(forecast, indent=2) + "\n", encoding="utf-8")
    return forecast


def _scenario_slots(
    start: datetime,
    end: datetime,
    pv_by_slot: dict[datetime, dict[str, Any]],
    pv_key: str,
    load: list[float],
    tz: ZoneInfo,
    missing: set[datetime],
) -> list[tuple[float, float]]:
    """Return (pv kWh, load kWh) per 30-minute slot between start and end."""
    slots: list[tuple[float, float]] = []
    cursor = start
    while cursor < end:
        slot_start = _floor_slot(cursor)
        slot_end = min(end, slot_start + SLOT)
        fraction = (slot_end - cursor) / SLOT
        forecast = pv_by_slot.get(slot_start)
        if forecast is None:
            missing.add(slot_start)
        pv_kwh = forecast[pv_key] * 0.5 if forecast else 0.0
        slots.append((pv_kwh * fraction, load[_slot_index(slot_start, tz)] * fraction))
        cursor = slot_end
    return slots


def _simulate(start_soc: float, slots: list[tuple[float, float]], config: PlannerConfig) -> tuple[float, float]:
    """Return (end SOC %, minimum SOC %) after applying the slots."""
    capacity = config.battery_capacity_kwh
    energy = start_soc / 100 * capacity
    lowest = energy
    for pv, load in slots:
        net = pv - load
        if net >= 0:
            energy = min(capacity, energy + net * config.charge_efficiency)
        else:
            energy = max(0.0, energy + net / config.discharge_efficiency)
        lowest = min(lowest, energy)
    return energy / capacity * 100, lowest / capacity * 100


def _required_soc(slots: list[tuple[float, float]], floor: float, config: PlannerConfig) -> int | None:
    for soc in range(101):
        if _simulate(soc, slots, config)[1] >= floor:
            return soc
    return None


def build_plan(
    now: datetime,
    soc: float,
    window: tuple[datetime, datetime],
    config: PlannerConfig,
    tariff: Tariff,
    profile: LoadProfile,
    forecast: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    window_start, window_end = window
    horizon_end = (window_start.astimezone(tariff.timezone) + timedelta(days=1)).astimezone(timezone.utc)
    pv_by_slot = {_parse_utc(item["period_end"]) - SLOT: item for item in forecast["forecasts"]}
    missing: set[datetime] = set()

    scenarios = {
        "expected": ("pv_estimate", profile.expected, config.expected_min_soc),
        "worstCase": ("pv_estimate10", profile.worst, config.worst_case_min_soc),
    }
    results: dict[str, dict[str, Any]] = {}
    for name, (pv_key, load, floor) in scenarios.items():
        before = _scenario_slots(now, window_end, pv_by_slot, pv_key, load, tariff.timezone, missing)
        after = _scenario_slots(window_end, horizon_end, pv_by_slot, pv_key, load, tariff.timezone, missing)
        projected = _simulate(soc, before, config)[0]
        required = _required_soc(after, floor, config)
        if required is None:
            warnings.append(f"Even a full battery may drop below {floor}% in the {name} scenario.")
            required = 100
        results[name] = {
            "minSocTarget": floor,
            "pvAfterWindow_kWh": round(sum(pv for pv, _ in after), 2),
            "loadAfterWindow_kWh": round(sum(load_kwh for _, load_kwh in after), 2),
            "projectedSocAtWindowEnd": round(projected, 1),
            "requiredSocAtWindowEnd": required,
            "minSocWithoutCharge": round(_simulate(projected, after, config)[1], 1),
        }

    if missing:
        warnings.append(f"No Solcast forecast for {len(missing)} half-hour slots; assumed zero PV.")

    shortfall = max(
        max(0.0, result["requiredSocAtWindowEnd"] - result["projectedSocAtWindowEnd"])
        for result in results.values()
    )
    grid_kwh = shortfall / 100 * config.battery_capacity_kwh / config.charge_efficiency
    charge = grid_kwh >= config.min_grid_charge_kwh
    night_rate = cheap_window(tariff)[2]
    return {
        "generatedAt": _iso(now),
        "dryRun": True,
        "decision": "charge" if charge else "no_charge",
        "targetSoc": max(result["requiredSocAtWindowEnd"] for result in results.values()) if charge else None,
        "gridCharge_kWh": round(grid_kwh, 2) if charge else 0.0,
        "estimatedChargeCost_AUD": round(grid_kwh * night_rate, 2) if charge else 0.0,
        "batterySoc": soc,
        "window": {"start": _iso(window_start), "end": _iso(window_end), "horizonEnd": _iso(horizon_end)},
        "scenarios": results,
        "forecastFetchedAt": forecast["fetchedAt"],
        "loadHistoryDays": profile.history_days,
        "fullLoadHistoryDays": profile.full_days,
        "dailyLoad_kWh": {
            "expected": round(sum(profile.expected), 2),
            "worstCase": round(sum(profile.worst), 2),
        },
        "warnings": warnings,
    }


def _load_history(since: datetime) -> list[tuple[datetime, float]]:
    snapshots: list[tuple[datetime, float]] = []
    for revision, content in _git_snapshot_contents(since):
        try:
            record = json.loads(content)
            snapshots.append(
                (
                    _parse_timestamp(record.get("mqttCurrentTime"), revision),
                    float(record["totalConsumptionToday_kWh"]),
                )
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return snapshots


def main() -> int:
    try:
        tariff = load_tariff()
        config = load_config()
        current = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        now = _parse_timestamp(current.get("mqttCurrentTime"), "working tree")
        window = planning_window(now, tariff, config.planning_lead_hours)
        if window is None:
            print("Outside the night-charge planning window; nothing to do.")
            return 0

        history = _load_history(now - timedelta(days=config.history_days))
        history.append((now, float(current["totalConsumptionToday_kWh"])))
        profile = build_load_profile(history, tariff.timezone, config)
        warnings: list[str] = []
        forecast = load_forecast(now, window[0] - timedelta(hours=config.planning_lead_hours), warnings)
        plan = build_plan(
            now, float(current["batterySoc_percent"]), window, config, tariff, profile, forecast, warnings
        )
        PLAN_FILE.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Could not plan night charge: {error}", file=sys.stderr)
        return 1

    print(
        f"Night charge plan (dry run): {plan['decision']}, target SOC {plan['targetSoc']}, "
        f"grid {plan['gridCharge_kWh']} kWh, est. ${plan['estimatedChargeCost_AUD']}"
    )
    for warning in plan["warnings"]:
        print(f"Warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
