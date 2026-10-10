from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from scripts.build_history import (
    TARIFF_PATH,
    _add_daily_cost_estimates,
    _energy_charge,
    _local_day_bounds,
    load_tariff,
)


class ElectricityTariffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tariff = load_tariff(TARIFF_PATH)

    def test_tariff_contains_confirmed_gst_inclusive_rates(self) -> None:
        self.assertEqual(self.tariff.timezone_name, "Australia/Sydney")
        self.assertEqual(self.tariff.feed_in_rate, Decimal("0.04"))
        self.assertEqual(self.tariff.supply_charge, Decimal("0.8716"))
        self.assertEqual(
            [period.rate for period in self.tariff.periods],
            [
                Decimal("0.08"),
                Decimal("0.2882"),
                Decimal("0.2052"),
                Decimal("0.2882"),
                Decimal("0.4362"),
                Decimal("0.2882"),
            ],
        )

    def test_prices_usage_across_peak_boundary_by_elapsed_time(self) -> None:
        start = datetime(2026, 6, 1, 14, 30, tzinfo=self.tariff.timezone).astimezone(timezone.utc)
        end = datetime(2026, 6, 1, 15, 30, tzinfo=self.tariff.timezone).astimezone(timezone.utc)

        charge = _energy_charge(Decimal("1"), start, end, self.tariff)

        self.assertEqual(charge, Decimal("0.3622"))

    def test_daily_cost_includes_import_supply_and_export_credit(self) -> None:
        records = [
            (
                datetime(2026, 6, 1, 14, 0, tzinfo=self.tariff.timezone).astimezone(timezone.utc),
                {"buyElectricityToday_kWh": 0, "sellingElectricityToday_kWh": 0},
            ),
            (
                datetime(2026, 6, 1, 15, 30, tzinfo=self.tariff.timezone).astimezone(timezone.utc),
                {"buyElectricityToday_kWh": 1, "sellingElectricityToday_kWh": 0},
            ),
            (
                datetime(2026, 6, 1, 16, 30, tzinfo=self.tariff.timezone).astimezone(timezone.utc),
                {"buyElectricityToday_kWh": 2, "sellingElectricityToday_kWh": 1},
            ),
        ]

        warnings = _add_daily_cost_estimates(records, self.tariff)

        self.assertEqual(warnings, {})
        final = records[-1][1]
        self.assertEqual(final["dailyImportCost_AUD"], 0.7737)
        self.assertEqual(final["dailyExportCredit_AUD"], 0.04)
        self.assertEqual(final["dailySupplyCharge_AUD"], 0.5992)
        self.assertEqual(final["dailyNetCost_AUD"], 1.333)

    def test_counter_reset_marks_that_day_unavailable(self) -> None:
        records = [
            (
                datetime(2026, 6, 1, 10, 0, tzinfo=self.tariff.timezone).astimezone(timezone.utc),
                {"buyElectricityToday_kWh": 2, "sellingElectricityToday_kWh": 1},
            ),
            (
                datetime(2026, 6, 1, 10, 15, tzinfo=self.tariff.timezone).astimezone(timezone.utc),
                {"buyElectricityToday_kWh": 0.1, "sellingElectricityToday_kWh": 1.1},
            ),
            (
                datetime(2026, 6, 1, 10, 30, tzinfo=self.tariff.timezone).astimezone(timezone.utc),
                {"buyElectricityToday_kWh": 0.2, "sellingElectricityToday_kWh": 1.2},
            ),
        ]

        warnings = _add_daily_cost_estimates(records, self.tariff)

        self.assertIn("2026-06-01", warnings)
        self.assertIsNone(records[1][1]["dailyNetCost_AUD"])
        self.assertIsNone(records[2][1]["dailyNetCost_AUD"])

    def test_day_bounds_follow_daylight_saving_length(self) -> None:
        start, end = _local_day_bounds(date(2026, 10, 4), self.tariff)

        self.assertEqual((end - start).total_seconds(), 23 * 60 * 60)

    def test_day_bounds_follow_daylight_saving_end(self) -> None:
        start, end = _local_day_bounds(date(2026, 4, 5), self.tariff)

        self.assertEqual((end - start).total_seconds(), 25 * 60 * 60)


if __name__ == "__main__":
    unittest.main()
