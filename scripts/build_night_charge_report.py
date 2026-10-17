#!/usr/bin/env python3
"""Build the dashboard's night-charge report: recent dry-run plans compared with what actually happened.

Run from the repository root with ``python -m scripts.build_night_charge_report``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.build_history import (
    DATA_PATH,
    REPOSITORY_ROOT,
    _git_snapshot_contents,
    _parse_timestamp,
    load_tariff,
)
from scripts.plan_night_charge import SLOT, _iso, _parse_utc, load_config


PLAN_PATH = "data/night_charge_plan.json"
EDGE_TOLERANCE = timedelta(minutes=30)
FIELDS = {
    "pv_kWh": "photovoltaicPowerGenerationToday_kWh",
    "load_kWh": "totalConsumptionToday_kWh",
    "gridImport_kWh": "buyElectricityToday_kWh",
}


def _git_json(path: str, since: datetime) -> list[tuple[str, dict[str, Any]]]:
    records: list[tuple[str, dict[str, Any]]] = []
    for revision, content in _git_snapshot_contents(since, path):
        try:
            record = json.loads(content)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append((revision, record))
    return records


def latest_plans(plans: list[dict[str, Any]], nights: int) -> list[dict[str, Any]]:
    """Keep the last plan generated for each window, newest windows first."""
    by_window: dict[str, tuple[tuple[datetime, str], dict[str, Any]]] = {}
    for plan in plans:
        try:
            start = plan["window"]["start"]
            # A replay keeps the original plan time, so the replay time breaks the tie.
            key = (_parse_utc(plan["generatedAt"]), plan.get("replayedAt") or "")
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if start not in by_window or key > by_window[start][0]:
            by_window[start] = (key, plan)
    ordered = sorted(by_window.items(), key=lambda item: _parse_utc(item[0]), reverse=True)
    return [plan for _, (_, plan) in ordered[:nights]]


def plan_trigger(plan: dict[str, Any], lead: timedelta) -> str:
    """How a plan was made: scheduled, manual (outside the planning window) or replay."""
    if plan.get("trigger"):
        return plan["trigger"]
    # Older plans predate the "trigger" field, so infer it.
    generated = _parse_utc(plan["generatedAt"])
    fetched = plan.get("forecastFetchedAt")
    if fetched and _parse_utc(fetched) > generated:
        return "replay"
    return "manual" if generated < _parse_utc(plan["window"]["start"]) - lead else "scheduled"


def decision_history(plans: list[dict[str, Any]], lead: timedelta) -> list[dict[str, Any]]:
    """A window's plans, oldest first, with consecutive identical decisions merged into one run."""
    # Older replays have no replayedAt, but their forecast was fetched later than the original's.
    unique = {
        (plan["generatedAt"], plan.get("replayedAt") or plan.get("forecastFetchedAt") or ""): plan for plan in plans
    }
    runs: list[dict[str, Any]] = []
    for key in sorted(unique, key=lambda item: (_parse_utc(item[0]), item[1])):
        plan = unique[key]
        trigger = plan_trigger(plan, lead)
        same = (plan.get("decision"), plan.get("targetSoc"), trigger)
        if runs and trigger != "replay" and (runs[-1]["decision"], runs[-1]["targetSoc"], runs[-1]["trigger"]) == same:
            runs[-1]["to"] = plan["generatedAt"]
            runs[-1]["count"] += 1
            runs[-1]["gridCharge_kWh"] = plan.get("gridCharge_kWh")
            continue
        runs.append(
            {
                "from": plan["generatedAt"],
                "to": plan["generatedAt"],
                "count": 1,
                "decision": plan.get("decision"),
                "targetSoc": plan.get("targetSoc"),
                "gridCharge_kWh": plan.get("gridCharge_kWh"),
                "trigger": trigger,
                # Older replays lack replayedAt; their forecast was fetched when they ran.
                "replayedAt": plan.get("replayedAt") or (plan.get("forecastFetchedAt") if trigger == "replay" else None),
            }
        )
    return runs


def _difference(end: dict[str, Any], start: dict[str, Any], field: str) -> float | None:
    try:
        return round(float(end[field]) - float(start[field]), 2)
    except (KeyError, TypeError, ValueError):
        return None


def _forecast_until(plan: dict[str, Any], slots_key: str, until: datetime) -> float | None:
    """Expected kWh from the window end until `until`, or None for plans without half-hourly slots."""
    slots = plan["scenarios"]["expected"].get(slots_key)
    if not slots:
        return None
    slot_start = _parse_utc(plan["window"]["end"])
    total = 0.0
    for kwh in slots:
        if slot_start >= until:
            break
        total += kwh * min(1.0, (until - slot_start) / SLOT)
        slot_start += SLOT
    return round(total, 2)


def _worst_ratio(plan: dict[str, Any], total_key: str) -> float:
    # The worst case scales every expected slot by one factor, so partial totals scale the same way.
    expected_total = plan["scenarios"]["expected"].get(total_key) or 0
    worst_total = plan["scenarios"].get("worstCase", {}).get(total_key) or 0
    return worst_total / expected_total if expected_total else 0


def _so_far(plan: dict[str, Any], as_of: datetime, latest: dict[str, Any], start: dict[str, Any]) -> dict[str, Any] | None:
    """Actual vs forecast from 06:00 until the latest reading, plus end-of-day load projections."""
    pv_forecast = _forecast_until(plan, "pvSlotsAfterWindow_kWh", as_of)
    load_forecast = _forecast_until(plan, "loadSlotsAfterWindow_kWh", as_of)
    if pv_forecast is None and load_forecast is None:
        return None
    so_far: dict[str, Any] = {"asOf": _iso(as_of)}
    if pv_forecast is not None:
        so_far["pvForecast_kWh"] = pv_forecast
        so_far["pvWorstCase_kWh"] = round(pv_forecast * _worst_ratio(plan, "pvAfterWindow_kWh"), 2)
        pv_actual = _difference(latest, start, FIELDS["pv_kWh"])
        remaining = max(0.0, round(sum(plan["scenarios"]["expected"]["pvSlotsAfterWindow_kWh"]) - pv_forecast, 2))
        so_far["pv_kWh"] = pv_actual
        so_far["pvRemainingForecast_kWh"] = remaining
        so_far["pvProjected_kWh"] = round(pv_actual + remaining, 2) if pv_actual is not None else None
    if load_forecast is not None:
        load_actual = _difference(latest, start, FIELDS["load_kWh"])
        remaining = (plan["scenarios"]["expected"].get("loadAfterWindow_kWh") or 0) - load_forecast
        load_today = _difference(latest, {FIELDS["load_kWh"]: 0}, FIELDS["load_kWh"])
        so_far["loadForecast_kWh"] = load_forecast
        so_far["loadWorstCase_kWh"] = round(load_forecast * _worst_ratio(plan, "loadAfterWindow_kWh"), 2)
        so_far["load_kWh"] = load_actual
        # Projection: what has been used so far plus the rest of today's expected load.
        so_far["loadProjected_kWh"] = round(load_actual + remaining, 2) if load_actual is not None else None
        so_far["loadDayProjected_kWh"] = round(load_today + remaining, 2) if load_today is not None else None
    return so_far


def actual_outcome(plan: dict[str, Any], snapshots: list[tuple[datetime, dict[str, Any]]]) -> dict[str, Any]:
    """Summarize the snapshots between the window end and the next window (the planning horizon)."""
    window_start = _parse_utc(plan["window"]["start"])
    window_end = _parse_utc(plan["window"]["end"])
    horizon_end = _parse_utc(plan["window"]["horizonEnd"])
    inside = [(timestamp, record) for timestamp, record in snapshots if window_end <= timestamp < horizon_end]
    # Counters reset at the window start (local midnight), so any reading from the window is a valid baseline.
    baseline = [record for timestamp, record in snapshots if window_start <= timestamp <= window_end]
    socs = [
        float(record["batterySoc_percent"])
        for _, record in inside
        if isinstance(record.get("batterySoc_percent"), (int, float))
    ]
    complete = bool(inside) and horizon_end - inside[-1][0] <= EDGE_TOLERANCE
    if baseline:
        start = baseline[-1]
    elif inside and inside[0][0] - window_end <= EDGE_TOLERANCE:
        start = inside[0][1]
    else:
        start = None

    outcome: dict[str, Any] = {
        "complete": complete,
        "minSoc": min(socs) if socs else None,
        "maxSoc": max(socs) if socs else None,
    }
    for name, field in FIELDS.items():
        outcome[name] = _difference(inside[-1][1], start, field) if complete and start is not None else None
    # The daily counter starts at local midnight, so the last reading is the whole day's load.
    outcome["loadDay_kWh"] = _difference(inside[-1][1], {FIELDS["load_kWh"]: 0}, FIELDS["load_kWh"]) if complete else None
    outcome["soFar"] = None
    if not complete and inside and start is not None:
        outcome["soFar"] = _so_far(plan, inside[-1][0], inside[-1][1], start)
    return outcome


def verdict(plan: dict[str, Any], actual: dict[str, Any]) -> str:
    if not actual["complete"] or actual["minSoc"] is None:
        return "pending"
    below_target = actual["minSoc"] < plan["scenarios"]["expected"]["minSocTarget"]
    if plan.get("decision") == "charge":
        return "charge_needed" if below_target else "charge_not_needed"
    return "missed" if below_target else "ok"


def build_report(
    plans: list[dict[str, Any]],
    snapshots: list[tuple[datetime, dict[str, Any]]],
    nights: int,
    now: datetime,
) -> dict[str, Any]:
    tz = load_tariff().timezone
    lead = timedelta(hours=load_config().planning_lead_hours)
    snapshots = sorted(snapshots, key=lambda item: item[0])
    by_window: dict[str, list[dict[str, Any]]] = {}
    for plan in plans:
        try:
            by_window.setdefault(plan["window"]["start"], []).append(plan)
        except (KeyError, TypeError):
            continue
    report_nights = []
    for plan in latest_plans(plans, nights):
        actual = actual_outcome(plan, snapshots)
        report_nights.append(
            {
                "night": _parse_utc(plan["window"]["start"]).astimezone(tz).date().isoformat(),
                "plan": plan,
                "trigger": plan_trigger(plan, lead),
                "history": decision_history(by_window[plan["window"]["start"]], lead),
                "actual": actual,
                "verdict": verdict(plan, actual),
            }
        )
    return {"generatedAt": _iso(now), "nights": report_nights}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nights", type=int, default=5, help="Number of recent nights (default: 5)")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "site" / "data" / "night_charge.json",
        help="Path for the generated report JSON",
    )
    args = parser.parse_args()
    if args.nights < 1:
        parser.error("--nights must be at least 1")

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.nights + 2)
    try:
        plans = [plan for _, plan in _git_json(PLAN_PATH, since)]
        snapshots = []
        for revision, record in _git_json(DATA_PATH, since):
            try:
                snapshots.append((_parse_timestamp(record.get("mqttCurrentTime"), revision), record))
            except ValueError:
                continue
        report = build_report(plans, snapshots, args.nights, now)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Could not build night-charge report: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {len(report['nights'])} nights to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
