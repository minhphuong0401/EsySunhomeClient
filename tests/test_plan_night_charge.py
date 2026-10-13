from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from scripts.build_history import TARIFF_PATH, load_tariff
from scripts.plan_night_charge import (
    LoadProfile,
    PlannerConfig,
    build_load_profile,
    build_plan,
    load_config,
    planning_window,
)


def _forecast(start: datetime, hours: int, pv_kw_by_local_hour: dict[int, tuple[float, float]], tz) -> dict:
    forecasts = []
    for index in range(hours * 2):
        period_end = start + timedelta(minutes=30 * (index + 1))
        local_hour = (period_end - timedelta(minutes=30)).astimezone(tz).hour
        p50, p10 = pv_kw_by_local_hour.get(local_hour, (0.0, 0.0))
        forecasts.append(
            {
                "period_end": period_end.isoformat().replace("+00:00", "Z"),
                "pv_estimate": p50,
                "pv_estimate10": p10,
            }
        )
    return {"fetchedAt": start.isoformat().replace("+00:00", "Z"), "forecasts": forecasts}


class NightChargePlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tariff = load_tariff(TARIFF_PATH)
        cls.tz = cls.tariff.timezone
        cls.config = PlannerConfig(
            battery_capacity_kwh=25,
            expected_min_soc=30,
            worst_case_min_soc=25,
            worst_case_load_quantile=0.9,
            daily_total_min_full_days=7,
            worst_case_fallback_load_factor=1.2,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
            min_grid_charge_kwh=1.0,
            history_days=28,
            planning_lead_hours=2,
        )
        # Flat 1 kW load: 0.5 kWh per half-hour slot.
        cls.flat_profile = LoadProfile([0.5] * 48, [0.5] * 48, 7, 7)

    def _local(self, *args: int) -> datetime:
        return datetime(*args, tzinfo=self.tz).astimezone(timezone.utc)

    def _full_day(self, day: int, kwh_per_slot: float) -> list[tuple[datetime, float]]:
        start = self._local(2026, 9, day, 0, 0)
        return [
            (start + timedelta(minutes=15 * quarter), kwh_per_slot / 2 * quarter)
            for quarter in range(1, 96)
        ]

    def test_repository_config_loads(self) -> None:
        self.assertEqual(load_config().battery_capacity_kwh, 25)

    def test_planning_window_targets_the_upcoming_night_saver_period(self) -> None:
        start, end = self._local(2026, 10, 12, 0, 0), self._local(2026, 10, 12, 6, 0)
        self.assertEqual(planning_window(self._local(2026, 10, 11, 22, 0), self.tariff, 2), (start, end))
        self.assertEqual(planning_window(self._local(2026, 10, 12, 3, 0), self.tariff, 2), (start, end))
        self.assertIsNone(planning_window(self._local(2026, 10, 11, 21, 59), self.tariff, 2))
        self.assertIsNone(planning_window(self._local(2026, 10, 12, 6, 0), self.tariff, 2))

    def test_load_profile_resets_at_midnight_and_skips_long_gaps(self) -> None:
        snapshots = []
        for day in (10, 11):
            for quarter in range(1, 5):
                snapshots.append((self._local(2026, 10, day, 0, 15 * quarter - 15) + timedelta(minutes=15), 0.1 * quarter))
            # A 5-hour outage should not be smeared across slots.
            snapshots.append((self._local(2026, 10, day, 6, 0), 5.0))

        profile = build_load_profile(snapshots, self.tz, self.config)

        self.assertEqual(profile.history_days, 2)
        self.assertEqual(profile.full_days, 0)
        self.assertAlmostEqual(profile.expected[0], 0.2)
        self.assertAlmostEqual(profile.expected[1], 0.2)
        # Slots without history fall back to the overall median.
        self.assertAlmostEqual(profile.expected[20], 0.2)
        # Too few full days: keep the median shape and apply the fallback factor to the worst case.
        self.assertAlmostEqual(profile.worst[0], 0.24)

    def test_profiles_scale_to_median_and_high_daily_totals(self) -> None:
        rates = [0.4, 0.4, 0.4, 0.5, 0.5, 0.5, 0.6]
        snapshots = [item for day, rate in enumerate(rates, start=1) for item in self._full_day(day, rate)]

        profile = build_load_profile(snapshots, self.tz, self.config)

        self.assertEqual(profile.full_days, 7)
        # Daily totals are rate * 47.5 kWh: median 23.75 kWh, 90th percentile 25.65 kWh.
        self.assertAlmostEqual(sum(profile.expected), 23.75)
        self.assertAlmostEqual(sum(profile.worst), 25.65)

    def test_worst_case_never_drops_below_expected(self) -> None:
        rates = [0.4, 0.4, 0.4, 0.5, 0.5, 0.5, 0.6]
        snapshots = [item for day, rate in enumerate(rates, start=1) for item in self._full_day(day, rate)]

        profile = build_load_profile(snapshots, self.tz, replace(self.config, worst_case_load_quantile=0.1))

        self.assertEqual(profile.worst, profile.expected)

    def test_sunny_day_needs_no_grid_charge(self) -> None:
        now = self._local(2026, 10, 11, 23, 30)
        window = planning_window(now, self.tariff, 2)
        forecast = _forecast(now, 30, {hour: (6.0, 6.0) for hour in range(8, 16)}, self.tz)

        plan = build_plan(now, 70, window, self.config, self.tariff, self.flat_profile, forecast, [])

        self.assertEqual(plan["decision"], "no_charge")
        self.assertEqual(plan["gridCharge_kWh"], 0.0)
        self.assertGreaterEqual(plan["scenarios"]["worstCase"]["minSocWithoutCharge"], 25)
        self.assertEqual(plan["warnings"], [])

    def test_worst_case_blends_pv_between_p50_and_p10(self) -> None:
        now = self._local(2026, 10, 11, 23, 30)
        window = planning_window(now, self.tariff, 2)
        forecast = _forecast(now, 30, {hour: (6.0, 0.0) for hour in range(8, 16)}, self.tz)
        profile = LoadProfile([0.5] * 48, [0.6] * 48, 7, 7)

        plan = build_plan(now, 70, window, self.config, self.tariff, profile, forecast, [])

        worst = plan["scenarios"]["worstCase"]
        self.assertAlmostEqual(worst["pvAfterWindow_kWh"], plan["scenarios"]["expected"]["pvAfterWindow_kWh"] / 2)
        self.assertGreater(worst["loadAfterWindow_kWh"], plan["scenarios"]["expected"]["loadAfterWindow_kWh"])
        self.assertEqual(plan["decision"], "no_charge")

    def test_cloudy_day_charges_to_cover_evening(self) -> None:
        now = self._local(2026, 10, 11, 23, 30)
        window = planning_window(now, self.tariff, 2)
        forecast = _forecast(now, 30, {hour: (1.5, 1.0) for hour in range(8, 16)}, self.tz)

        plan = build_plan(now, 50, window, self.config, self.tariff, self.flat_profile, forecast, [])

        self.assertEqual(plan["decision"], "charge")
        self.assertGreater(plan["targetSoc"], plan["scenarios"]["expected"]["projectedSocAtWindowEnd"])
        self.assertAlmostEqual(plan["estimatedChargeCost_AUD"], round(plan["gridCharge_kWh"] * 0.08, 2), places=2)

    def test_unreachable_floor_targets_full_battery_with_warning(self) -> None:
        now = self._local(2026, 10, 11, 23, 30)
        window = planning_window(now, self.tariff, 2)
        heavy_profile = LoadProfile([2.0] * 48, [2.0] * 48, 7, 7)

        plan = build_plan(now, 50, window, self.config, self.tariff, heavy_profile, _forecast(now, 30, {}, self.tz), [])

        self.assertEqual(plan["decision"], "charge")
        self.assertEqual(plan["targetSoc"], 100)
        self.assertTrue(any("full battery" in warning for warning in plan["warnings"]))


if __name__ == "__main__":
    unittest.main()