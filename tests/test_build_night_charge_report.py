from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from scripts.build_history import TARIFF_PATH, load_tariff
from scripts.build_night_charge_report import actual_outcome, build_report, latest_plans, verdict


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class NightChargeReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tz = load_tariff(TARIFF_PATH).timezone

    def _local(self, *args: int) -> datetime:
        return datetime(*args, tzinfo=self.tz).astimezone(timezone.utc)

    def _plan(self, day: int, decision: str = "no_charge", generated_hour: int = 23) -> dict:
        return {
            "generatedAt": _iso(self._local(2026, 10, day - 1, generated_hour, 0)),
            "decision": decision,
            "window": {
                "start": _iso(self._local(2026, 10, day, 0, 0)),
                "end": _iso(self._local(2026, 10, day, 6, 0)),
                "horizonEnd": _iso(self._local(2026, 10, day + 1, 0, 0)),
            },
            "scenarios": {"expected": {"minSocTarget": 30}},
        }

    def _snapshot(self, day: int, hour: int, minute: int, soc: float, pv: float, load: float, grid: float):
        return (
            self._local(2026, 10, day, hour, minute),
            {
                "batterySoc_percent": soc,
                "photovoltaicPowerGenerationToday_kWh": pv,
                "totalConsumptionToday_kWh": load,
                "buyElectricityToday_kWh": grid,
            },
        )

    def test_latest_plans_keeps_last_generated_plan_per_window(self) -> None:
        early = self._plan(12, "charge", generated_hour=22)
        late = self._plan(12, "no_charge", generated_hour=23)
        plans = latest_plans([early, late, self._plan(11), self._plan(10)], nights=2)

        self.assertEqual([plan["window"]["start"] for plan in plans], [late["window"]["start"], self._plan(11)["window"]["start"]])
        self.assertEqual(plans[0]["decision"], "no_charge")

    def test_actual_outcome_measures_horizon_after_window(self) -> None:
        snapshots = [
            self._snapshot(12, 5, 45, 60, 0.0, 2.0, 0.1),
            self._snapshot(12, 12, 0, 45, 20.0, 9.0, 0.2),
            self._snapshot(12, 23, 45, 55, 35.0, 22.0, 0.6),
            self._snapshot(13, 0, 15, 54, 0.0, 0.1, 0.0),
        ]

        outcome = actual_outcome(self._plan(12), snapshots)

        self.assertTrue(outcome["complete"])
        self.assertEqual(outcome["minSoc"], 45)
        self.assertEqual(outcome["pv_kWh"], 35.0)
        self.assertEqual(outcome["load_kWh"], 20.0)
        self.assertEqual(outcome["loadDay_kWh"], 22.0)
        self.assertEqual(outcome["gridImport_kWh"], 0.5)

    def test_outcome_is_pending_until_the_day_ends(self) -> None:
        snapshots = [self._snapshot(12, 5, 45, 60, 0.0, 2.0, 0.1), self._snapshot(12, 15, 0, 40, 20.0, 12.0, 0.2)]

        outcome = actual_outcome(self._plan(12), snapshots)

        self.assertFalse(outcome["complete"])
        self.assertIsNone(outcome["load_kWh"])
        self.assertIsNone(outcome["loadDay_kWh"])
        self.assertEqual(verdict(self._plan(12), outcome), "pending")

    def test_verdicts_compare_decision_with_actual_lowest_soc(self) -> None:
        low = {"complete": True, "minSoc": 22}
        high = {"complete": True, "minSoc": 48}

        self.assertEqual(verdict(self._plan(12, "no_charge"), high), "ok")
        self.assertEqual(verdict(self._plan(12, "no_charge"), low), "missed")
        self.assertEqual(verdict(self._plan(12, "charge"), low), "charge_needed")
        self.assertEqual(verdict(self._plan(12, "charge"), high), "charge_not_needed")

    def test_build_report_labels_nights_by_local_date(self) -> None:
        report = build_report([self._plan(12)], [], nights=5, now=self._local(2026, 10, 12, 8, 0))

        self.assertEqual(report["nights"][0]["night"], "2026-10-12")
        self.assertEqual(report["nights"][0]["verdict"], "pending")


if __name__ == "__main__":
    unittest.main()
