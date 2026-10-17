from __future__ import annotations

import asyncio
import contextlib
import importlib
import io
import json
import sys
import tempfile
import types
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from scripts import plan_ev_charge
from scripts.build_history import load_tariff
from scripts.plan_ev_charge import build_ev_plan, daily_distances, load_ev_config, solar_surplus
from scripts.plan_night_charge import LoadProfile, load_config


class EvChargePlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tariff = load_tariff()
        cls.config = load_ev_config()
        cls.now = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
        cls.vehicle = {
            "fetchedAt": cls.now.isoformat(), "vehicleTime": cls.now.isoformat(),
            "socPercent": 25, "odometerKm": 12000, "recent50kmKwhPer100km": 20,
        }

    def test_configurable_home_window_and_current(self) -> None:
        config = replace(self.config, daytime_home_start="12:00", daytime_home_end="16:00", max_current_amps=10)
        plan = build_ev_plan(self.now, self.vehicle, {weekday: 100 for weekday in range(7)},
                             config, self.tariff, {}, [])

        self.assertEqual(plan["daytime"]["window"]["start"], "2026-10-15T01:00:00Z")
        self.assertEqual(plan["daytime"]["window"]["end"], "2026-10-15T05:00:00Z")
        self.assertEqual(plan["overnight"]["currentA"], 10)

    def test_night_charge_covers_full_estimated_day_and_reserve(self) -> None:
        plan = build_ev_plan(self.now, self.vehicle, {weekday: 100 for weekday in range(7)},
                             self.config, self.tariff, {}, [])

        self.assertEqual(plan["overnight"]["decision"], "charge")
        self.assertEqual(plan["overnight"]["currentA"], 32)
        self.assertEqual(plan["overnight"]["end"], "2026-10-14T19:00:00Z")
        self.assertGreaterEqual(plan["tomorrow"]["socAfterDriving"], 20)
        self.assertEqual(plan["daytime"]["decision"], "no_charge")

    def test_daytime_solar_is_used_only_when_needed_and_available(self) -> None:
        vehicle = dict(self.vehicle, socPercent=65)
        midday = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
        solar = {midday + timedelta(minutes=30 * index): 1.84 for index in range(4)}
        plan = build_ev_plan(self.now, vehicle, {weekday: 60 for weekday in range(7)},
                             self.config, self.tariff, solar, [])

        self.assertEqual(plan["overnight"]["decision"], "no_charge")
        self.assertEqual(plan["daytime"]["decision"], "charge")
        self.assertTrue(all(6 <= slot["currentA"] <= 32 for slot in plan["daytime"]["slots"]))
        self.assertAlmostEqual(plan["daytime"]["opportunityCost_AUD"],
                               round(plan["daytime"]["energyFromSolar_kWh"] * 0.04, 2))

    def test_cheap_solar_can_charge_above_next_day_requirement(self) -> None:
        vehicle = dict(self.vehicle, socPercent=60)
        midday = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
        solar = {midday + timedelta(minutes=30 * index): 1.84 for index in range(8)}
        plan = build_ev_plan(self.now, vehicle, {weekday: 37 for weekday in range(7)},
                             self.config, self.tariff, solar, [])

        self.assertEqual(plan["overnight"]["decision"], "no_charge")
        self.assertEqual(plan["daytime"]["decision"], "charge")
        self.assertGreater(plan["daytime"]["socAfterCharge"], plan["tomorrow"]["socAfterDriving"])
        self.assertEqual(plan["daytime"]["remainingEnergyBeforeNextNight_kWh"], 0)

    def test_future_solar_reduces_early_top_up(self) -> None:
        vehicle = dict(self.vehicle, socPercent=60)
        midday = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
        solar = {midday + timedelta(minutes=30 * index): 1.84 for index in range(8)}
        solar.update({midday + timedelta(days=1, minutes=30 * index): 3.68 for index in range(8)})
        plan = build_ev_plan(self.now, vehicle, {weekday: 37 for weekday in range(7)},
                             self.config, self.tariff, solar, [])

        self.assertEqual(plan["daytime"]["decision"], "no_charge")

    def test_early_top_up_requires_cheaper_solar(self) -> None:
        vehicle = dict(self.vehicle, socPercent=60)
        midday = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
        solar = {midday + timedelta(minutes=30 * index): 1.84 for index in range(8)}
        expensive_export = replace(self.tariff, feed_in_rate=Decimal("0.09"))
        plan = build_ev_plan(self.now, vehicle, {weekday: 37 for weekday in range(7)},
                             self.config, expensive_export, solar, [])
        necessary = build_ev_plan(self.now, self.vehicle, {weekday: 60 for weekday in range(7)},
                                  self.config, expensive_export, solar, [])

        self.assertEqual(plan["daytime"]["decision"], "no_charge")
        self.assertEqual(necessary["daytime"]["decision"], "charge")

    def test_early_top_up_respects_configured_soc_cap(self) -> None:
        vehicle = dict(self.vehicle, socPercent=60)
        midday = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
        solar = {midday + timedelta(minutes=30 * index): 3.68 for index in range(12)}
        config = replace(self.config, solar_soc_cap_percent=65)
        plan = build_ev_plan(self.now, vehicle, {weekday: 60 for weekday in range(7)},
                             config, self.tariff, solar, [])

        self.assertEqual(plan["daytime"]["decision"], "charge")
        self.assertLessEqual(plan["daytime"]["socAfterCharge"], 65)

    def test_stale_vehicle_data_is_rejected(self) -> None:
        vehicle = dict(self.vehicle, vehicleTime=(self.now - timedelta(hours=9)).isoformat())
        with self.assertRaisesRegex(ValueError, "too old"):
            build_ev_plan(self.now, vehicle, {weekday: 60 for weekday in range(7)},
                          self.config, self.tariff, {}, [])

    def test_infeasible_trip_and_night_window_raise_warnings(self) -> None:
        warnings: list[str] = []
        plan = build_ev_plan(self.now, self.vehicle, {weekday: 500 for weekday in range(7)},
                             self.config, self.tariff, {}, warnings)

        self.assertLess(plan["tomorrow"]["socAfterDriving"], plan["minimumSoc"])
        self.assertTrue(any("capacity" in warning for warning in warnings))
        slow_warnings: list[str] = []
        build_ev_plan(self.now, self.vehicle, {weekday: 100 for weekday in range(7)},
                  replace(self.config, max_current_amps=6), self.tariff, {}, slow_warnings)
        self.assertTrue(any("cheap window" in warning for warning in slow_warnings))

    def test_solar_below_minimum_current_is_not_scheduled(self) -> None:
        midday = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
        plan = build_ev_plan(self.now, self.vehicle, {weekday: 60 for weekday in range(7)},
                             self.config, self.tariff, {midday: 0.5}, [])

        self.assertEqual(plan["daytime"]["decision"], "no_charge")

    def test_unavailable_consumption_uses_configured_fallback(self) -> None:
        warnings: list[str] = []
        vehicle = dict(self.vehicle, recent50kmKwhPer100km=0)
        plan = build_ev_plan(self.now, vehicle, {weekday: 60 for weekday in range(7)},
                             self.config, self.tariff, {}, warnings)

        self.assertEqual(plan["consumption50km_kWhPer100km"], self.config.fallback_consumption_kwh_per_100km)
        self.assertTrue(any("fallback" in warning for warning in warnings))

    def test_daily_distance_excludes_gaps_and_falls_back_without_history(self) -> None:
        readings = [
            {"fetchedAt": (self.now + timedelta(days=day)).isoformat(), "odometerKm": odometer}
            for day, odometer in ((0, 1000), (1, 1080), (2, 1200), (5, 1250), (6, 1260))
        ]
        distances = daily_distances(readings, self.tariff.timezone, self.config)

        self.assertEqual(distances[(self.now + timedelta(days=1)).astimezone(self.tariff.timezone).weekday()], 104)
        self.assertEqual(distances[(self.now + timedelta(days=5)).astimezone(self.tariff.timezone).weekday()], 104)
        self.assertEqual(daily_distances([], self.tariff.timezone, self.config)[0], self.config.fallback_daily_km)

    def test_solar_surplus_after_home_battery_charge_tapers(self) -> None:
        config = load_config()
        start = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
        forecasts = [
            {"period_end": (start + timedelta(minutes=30 * (index + 1))).isoformat(), "pv_estimate": 6}
            for index in range(3)
        ]
        profile = LoadProfile([0.5] * 48, [0.5] * 48, 7, 7)
        surplus = solar_surplus(start, start + timedelta(minutes=90), 75, forecasts,
                                profile, self.tariff, config)

        self.assertEqual(surplus[start], 0)
        self.assertGreater(surplus[start + timedelta(minutes=30)], 0)

    def test_solar_surplus_respects_home_battery_charge_power(self) -> None:
        config = replace(load_config(), worst_case_pv_factor=1)
        start = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
        forecasts = [{"period_end": (start + timedelta(minutes=30)).isoformat(), "pv_estimate": 8}]
        profile = LoadProfile([0.0] * 48, [0.0] * 48, 7, 7)

        surplus = solar_surplus(start, start + timedelta(minutes=30), 20, forecasts,
                                profile, self.tariff, config)

        self.assertAlmostEqual(surplus[start], 1.0)

    def test_solar_surplus_increases_when_home_battery_charge_tapers(self) -> None:
        config = replace(load_config(), worst_case_pv_factor=1)
        start = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
        forecasts = [{"period_end": (start + timedelta(minutes=30)).isoformat(), "pv_estimate": 8}]
        profile = LoadProfile([0.0] * 48, [0.0] * 48, 7, 7)

        surplus = solar_surplus(start, start + timedelta(minutes=30), 90, forecasts,
                                profile, self.tariff, config)

        self.assertAlmostEqual(surplus[start], 3.0)

    def test_workflow_entrypoint_writes_a_plan_from_snapshots(self) -> None:
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return self.now

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vehicle_file = root / "byd.json"
            home_file = root / "data.json"
            plan_file = root / "ev_charge_plan.json"
            vehicle_file.write_text(json.dumps(self.vehicle), encoding="utf-8")
            home_file.write_text(json.dumps({
                "mqttCurrentTime": (self.now - timedelta(minutes=15)).isoformat(),
                "totalConsumptionToday_kWh": 12, "batterySoc_percent": 100,
            }), encoding="utf-8")
            forecasts = [
                {"period_end": (datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
                                + timedelta(minutes=30 * (index + 1))).isoformat(), "pv_estimate": 8}
                for index in range(12)
            ]
            with mock.patch.object(plan_ev_charge, "datetime", FixedDatetime), \
                    mock.patch.object(plan_ev_charge, "VEHICLE_FILE", vehicle_file), \
                    mock.patch.object(plan_ev_charge, "HOME_FILE", home_file), \
                    mock.patch.object(plan_ev_charge, "PLAN_FILE", plan_file), \
                    mock.patch.object(plan_ev_charge, "_git_snapshot_contents", return_value=[]), \
                    mock.patch.object(plan_ev_charge, "_load_history", return_value=[]), \
                    mock.patch.object(plan_ev_charge, "build_load_profile", return_value=self.flat_profile()), \
                    mock.patch.object(plan_ev_charge, "load_forecast", return_value={"forecasts": forecasts}), \
                    mock.patch.object(plan_ev_charge, "solar_surplus", wraps=solar_surplus) as surplus, \
                    contextlib.redirect_stdout(io.StringIO()):
                result = plan_ev_charge.main()
            plan = json.loads(plan_file.read_text(encoding="utf-8"))

        self.assertEqual(result, 0)
        self.assertEqual(surplus.call_args.args[1], datetime(2026, 10, 16, 6, tzinfo=timezone.utc))
        self.assertEqual(plan["overnight"]["decision"], "charge")
        self.assertEqual(plan["daytime"]["window"]["start"], "2026-10-15T00:00:00Z")

    @staticmethod
    def flat_profile() -> LoadProfile:
        return LoadProfile([0.5] * 48, [0.5] * 48, 7, 7)


class BydSnapshotTests(unittest.TestCase):
    def test_falls_back_to_realtime_consumption_without_exposing_vin(self) -> None:
        class FakeApiError(Exception):
            pass

        class FakeClient:
            def __init__(self, config) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args) -> None:
                pass

            async def get_vehicles(self):
                return [types.SimpleNamespace(vin="PRIVATE-VIN")]

            async def get_vehicle_realtime(self, vin):
                return types.SimpleNamespace(
                    elec_percent=48, total_mileage=23000,
                    recent_50km_energy_ev=18.5, recent_50km_energy_ev_unit="kWh/100km",
                    timestamp=datetime.now(timezone.utc),
                )

            async def get_energy_consumption(self, vin):
                raise FakeApiError("endpoint unavailable")

        fake_library = types.SimpleNamespace(
            BydClient=FakeClient,
            BydConfig=types.SimpleNamespace(from_env=lambda: object()),
            BydApiError=FakeApiError,
        )
        output = io.StringIO()
        with mock.patch.dict(sys.modules, {"pybyd": fake_library}), contextlib.redirect_stdout(output):
            sys.modules.pop("byd", None)
            try:
                byd = importlib.import_module("byd")
                asyncio.run(byd.main())
            finally:
                sys.modules.pop("byd", None)

        result = json.loads(output.getvalue())
        self.assertEqual(result["socPercent"], 48)
        self.assertEqual(result["odometerKm"], 23000)
        self.assertEqual(result["recent50kmKwhPer100km"], 18.5)
        self.assertNotIn("PRIVATE-VIN", output.getvalue())


if __name__ == "__main__":
    unittest.main()