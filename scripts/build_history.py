#!/usr/bin/env python3
"""Build a static JSON history from recent data/data.json Git snapshots."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = "data/data.json"
GIT_HISTORY_MARGIN_DAYS = 7
TARIFF_PATH = REPOSITORY_ROOT / "config" / "electricity_tariff.json"
ZERO = Decimal("0")
FOUR_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class TariffPeriod:
    start_minute: int
    end_minute: int
    rate: Decimal


@dataclass(frozen=True)
class Tariff:
    timezone_name: str
    timezone: ZoneInfo
    currency: str
    feed_in_rate: Decimal
    supply_charge: Decimal
    periods: tuple[TariffPeriod, ...]


def _decimal_value(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Tariff value {name!r} must be a decimal number.") from error
    if not result.is_finite() or result < ZERO:
        raise ValueError(f"Tariff value {name!r} must be a finite, non-negative number.")
    return result


def _parse_clock(value: Any, name: str) -> int:
    if not isinstance(value, str):
        raise ValueError(f"Tariff period {name!r} must be a time string.")
    if value == "24:00":
        return 24 * 60
    try:
        parsed = time.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Tariff period {name!r} has invalid time {value!r}.") from error
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ValueError(f"Tariff period {name!r} must use HH:MM local time.")
    return parsed.hour * 60 + parsed.minute


def load_tariff(path: Path = TARIFF_PATH) -> Tariff:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load electricity tariff configuration from {path}: {error}") from error

    if not isinstance(config, dict):
        raise ValueError(f"Electricity tariff configuration in {path} must be a JSON object.")
    timezone_name = config.get("timezone")
    rates = config.get("rates")
    period_configs = config.get("periods")
    if not isinstance(timezone_name, str):
        raise ValueError("Electricity tariff timezone must be a string.")
    if not isinstance(rates, dict) or not isinstance(period_configs, list):
        raise ValueError("Electricity tariff rates and periods must be objects and arrays.")
    try:
        timezone_info = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError(f"Unknown electricity tariff timezone {timezone_name!r}.") from error
    if config.get("currency") != "AUD":
        raise ValueError("Electricity tariff currency must be AUD.")

    parsed_rates = {
        name: _decimal_value(value, name)
        for name, value in rates.items()
    }
    feed_in_rate = _decimal_value(config["feed_in_rate"], "feed_in_rate")
    supply_charge = _decimal_value(config["supply_charge"], "supply_charge")

    periods: list[TariffPeriod] = []
    for index, item in enumerate(period_configs):
        if not isinstance(item, dict):
            raise ValueError(f"Tariff period {index} must be a JSON object.")
        start = _parse_clock(item.get("start"), "start")
        end = _parse_clock(item.get("end"), "end")
        rate_name = item.get("rate")
        if rate_name not in parsed_rates:
            raise ValueError(f"Tariff period refers to unknown rate {rate_name!r}.")
        if start >= end:
            raise ValueError(f"Tariff period {rate_name!r} must have start before end.")
        periods.append(TariffPeriod(start, end, parsed_rates[rate_name]))

    periods.sort(key=lambda period: period.start_minute)
    next_start = 0
    for period in periods:
        if period.start_minute != next_start:
            raise ValueError("Tariff periods must cover the day exactly once without gaps or overlaps.")
        next_start = period.end_minute
    if next_start != 24 * 60:
        raise ValueError("Tariff periods must cover the day through 24:00.")

    return Tariff(
        timezone_name=timezone_name,
        timezone=timezone_info,
        currency=config["currency"],
        feed_in_rate=feed_in_rate,
        supply_charge=supply_charge,
        periods=tuple(periods),
    )


def _git_snapshot_contents(since: datetime) -> list[tuple[str, bytes]]:
    revisions = subprocess.run(
        [
            "git",
            "log",
            f"--since={since.isoformat()}",
            "--format=%H",
            "--",
            DATA_PATH,
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    if not revisions:
        return []

    requests = "".join(f"{revision}:{DATA_PATH}\n" for revision in revisions)
    output = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        input=requests.encode("ascii"),
    ).stdout
    stream = io.BytesIO(output)
    snapshots: list[tuple[str, bytes]] = []

    for revision in revisions:
        header = stream.readline().decode("ascii").strip().split()
        if len(header) != 3 or header[1] != "blob":
            raise RuntimeError(f"Could not read {DATA_PATH} from commit {revision}.")

        content = stream.read(int(header[2]))
        if stream.read(1) != b"\n":
            raise RuntimeError(f"Unexpected Git object boundary for commit {revision}.")
        snapshots.append((revision, content))

    return snapshots


def _parse_timestamp(value: Any, revision: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{DATA_PATH} in commit {revision} has no valid mqttCurrentTime.")

    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(
            f"{DATA_PATH} in commit {revision} has invalid mqttCurrentTime: {value!r}."
        ) from error

    if timestamp.tzinfo is None:
        raise ValueError(
            f"{DATA_PATH} in commit {revision} has a timezone-naive mqttCurrentTime."
        )
    return timestamp.astimezone(timezone.utc)


def _reading(record: dict[str, Any], field: str, day: str, warnings: dict[str, str]) -> Decimal | None:
    value = record.get(field)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        warnings[day] = f"Missing or invalid {field} reading."
        return None
    if not result.is_finite() or result < ZERO:
        warnings[day] = f"Invalid negative or non-finite {field} reading."
        return None
    return result


def _period_rate(timestamp: datetime, tariff: Tariff) -> Decimal:
    local_time = timestamp.astimezone(tariff.timezone)
    minute = local_time.hour * 60 + local_time.minute
    for period in tariff.periods:
        if period.start_minute <= minute < period.end_minute:
            return period.rate
    raise RuntimeError(f"No electricity rate covers local minute {minute}.")


def _energy_charge(
    energy_kwh: Decimal,
    start: datetime,
    end: datetime,
    tariff: Tariff,
) -> Decimal:
    if energy_kwh == ZERO:
        return ZERO
    duration_seconds = Decimal(str((end - start).total_seconds()))
    if duration_seconds <= ZERO:
        raise ValueError("Cannot price energy across a zero-length snapshot interval.")

    charge = ZERO
    cursor = start
    while cursor < end:
        next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        segment_end = min(end, next_hour)
        segment_seconds = Decimal(str((segment_end - cursor).total_seconds()))
        midpoint = cursor + (segment_end - cursor) / 2
        charge += energy_kwh * segment_seconds / duration_seconds * _period_rate(midpoint, tariff)
        cursor = segment_end
    return charge


def _local_day_bounds(day: date, tariff: Tariff) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=tariff.timezone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tariff.timezone).astimezone(timezone.utc)
    return start, end


def _money_value(value: Decimal) -> float:
    return float(value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP))


def _add_daily_cost_estimates(
    records: list[tuple[datetime, dict[str, Any]]],
    tariff: Tariff,
) -> dict[str, str]:
    warnings: dict[str, str] = {}
    active_day: str | None = None
    previous_timestamp: datetime | None = None
    previous_import: Decimal | None = None
    previous_export: Decimal | None = None
    import_cost = ZERO
    export_credit = ZERO
    day_is_valid = True

    for timestamp, record in records:
        local_timestamp = timestamp.astimezone(tariff.timezone)
        local_date = local_timestamp.date()
        day = local_date.isoformat()
        record["tariffLocalDate"] = day

        if day != active_day:
            active_day = day
            previous_timestamp = _local_day_bounds(local_date, tariff)[0]
            previous_import = ZERO
            previous_export = ZERO
            import_cost = ZERO
            export_credit = ZERO
            day_is_valid = True

        imported = _reading(record, "buyElectricityToday_kWh", day, warnings)
        exported = _reading(record, "sellingElectricityToday_kWh", day, warnings)
        if imported is None or exported is None:
            record["dailyImportCost_AUD"] = None
            record["dailyExportCredit_AUD"] = None
            record["dailySupplyCharge_AUD"] = None
            record["dailyNetCost_AUD"] = None
            continue

        import_delta = imported - previous_import if previous_import is not None else imported
        export_delta = exported - previous_export if previous_export is not None else exported
        if import_delta < ZERO or export_delta < ZERO:
            warnings[day] = "An import or export counter decreased during the day; daily cost is unavailable."
            day_is_valid = False
        elif day_is_valid and previous_timestamp is not None:
            try:
                import_cost += _energy_charge(import_delta, previous_timestamp, timestamp, tariff)
                export_credit += export_delta * tariff.feed_in_rate
            except ValueError as error:
                warnings[day] = str(error)
                day_is_valid = False

        previous_timestamp = timestamp
        previous_import = imported
        previous_export = exported
        if not day_is_valid:
            record["dailyImportCost_AUD"] = None
            record["dailyExportCredit_AUD"] = None
            record["dailySupplyCharge_AUD"] = None
            record["dailyNetCost_AUD"] = None
            continue

        supply_charge = tariff.supply_charge
        net_cost = export_credit - import_cost - supply_charge
        record["dailyImportCost_AUD"] = _money_value(import_cost)
        record["dailyExportCredit_AUD"] = _money_value(export_credit)
        record["dailySupplyCharge_AUD"] = _money_value(supply_charge)
        record["dailyNetCost_AUD"] = _money_value(net_cost)

    return warnings


def build_history(days: int, now: datetime, tariff_path: Path = TARIFF_PATH) -> dict[str, Any]:
    tariff = load_tariff(tariff_path)
    cutoff = now - timedelta(days=days)
    search_since = cutoff - timedelta(days=GIT_HISTORY_MARGIN_DAYS)
    records: list[tuple[datetime, dict[str, Any]]] = []

    # Git's commit time is only used to narrow the search; the MQTT timestamp
    # decides whether a snapshot is actually inside the requested time window.
    for revision, content in reversed(_git_snapshot_contents(search_since)):
        try:
            record = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                f"{DATA_PATH} in commit {revision} is not valid JSON."
            ) from error

        if not isinstance(record, dict):
            raise ValueError(f"{DATA_PATH} in commit {revision} must contain a JSON object.")

        timestamp = _parse_timestamp(record.get("mqttCurrentTime"), revision)
        if search_since <= timestamp <= now:
            record["timestamp"] = timestamp.isoformat().replace("+00:00", "Z")
            records.append((timestamp, record))

    records.sort(key=lambda item: item[0])
    cost_warnings = _add_daily_cost_estimates(records, tariff)
    included = [(timestamp, record) for timestamp, record in records if cutoff <= timestamp <= now]
    included_days = {record["tariffLocalDate"] for _, record in included}
    return {
        "generatedAt": now.isoformat().replace("+00:00", "Z"),
        "days": days,
        "tariff": {"timezone": tariff.timezone_name, "currency": tariff.currency},
        "costWarnings": [
            {"date": day, "message": message}
            for day, message in sorted(cost_warnings.items())
            if day in included_days
        ],
        "records": [record for _, record in included],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, help="History window in days (default: 90)")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "site" / "data" / "history.json",
        help="Path for the generated history JSON",
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")

    try:
        history = build_history(args.days, datetime.now(timezone.utc))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(history, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError) as error:
        print(f"Could not build energy history: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {len(history['records'])} snapshots to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
