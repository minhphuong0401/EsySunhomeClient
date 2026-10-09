#!/usr/bin/env python3
"""Build a static JSON history from recent data/data.json Git snapshots."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = "data/data.json"
GIT_HISTORY_MARGIN_DAYS = 7


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


def build_history(days: int, now: datetime) -> dict[str, Any]:
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
        if cutoff <= timestamp <= now:
            record["timestamp"] = timestamp.isoformat().replace("+00:00", "Z")
            records.append((timestamp, record))

    records.sort(key=lambda item: item[0])
    return {
        "generatedAt": now.isoformat().replace("+00:00", "Z"),
        "days": days,
        "records": [record for _, record in records],
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
