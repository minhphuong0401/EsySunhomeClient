"""Publish an allowlisted, human-readable view of dashboard settings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def build_settings_report(config_dir: Path = ROOT / "config") -> dict[str, Any]:
    def read(name: str) -> dict[str, Any]:
        return json.loads((config_dir / name).read_text(encoding="utf-8"))

    tariff = read("electricity_tariff.json")
    home = read("night_charge.json")
    vehicle = read("ev_charge.json")

    def item(label: str, value: str, detail: str) -> dict[str, str]:
        return {"label": label, "value": value, "detail": detail}

    def percent(value: Any) -> str:
        return f"{float(value) * 100:g}%"

    def percentile(value: Any) -> str:
        return f"{float(value) * 100:g}th percentile"

    rates = tariff["rates"]
    rate_names = {
        "peak": "Peak",
        "off_peak": "Off-peak",
        "shoulder": "Shoulder",
        "night_saver_ev": "Night saver",
    }
    return {"groups": [
        {
            "title": "Electricity & billing",
            "description": "Import prices, export credit and your billing window.",
            "items": [
                item("Billing cycle starts", f"Day {tariff['billing_cycle_start_day']} of each month", "The cycle ends the day before the next start."),
                item("Daily supply charge", f"${tariff['supply_charge']} / day", "Fixed charge, even on days with no grid use."),
                item("Solar export credit", f"${tariff['feed_in_rate']} / kWh", "Credit for electricity sent to the grid."),
                item("Time zone", tariff["timezone"], "Used for tariff periods and billing dates."),
            ],
            "schedule": [
                {"hours": f"{period['start']}–{period['end']}", "name": rate_names.get(period["rate"], period["rate"].replace("_", " ").title()), "price": f"${rates[period['rate']]} / kWh"}
                for period in tariff["periods"]
            ],
        },
        {
            "title": "Home battery",
            "description": "Limits and assumptions for overnight grid-charge advice.",
            "items": [
                item("Battery capacity", f"{home['battery_capacity_kwh']:g} kWh", "Usable size assumed by the planner."),
                item("Inverter minimum charge", f"{home['battery_min_soc']:g}%", "The floor below which the planner stops discharging."),
                item("Expected-day reserve", f"{home['expected_min_soc']:g}%", "Minimum predicted charge in a typical day."),
                item("Worst-case reserve", f"{home['worst_case_min_soc']:g}%", "Minimum predicted charge in a poor-solar, high-load day."),
                item("Worst-case solar", percent(home["worst_case_pv_factor"]), "Share of the forecast solar used in the cautious scenario."),
                item("Worst-case household load", percentile(home["worst_case_load_quantile"]), "Recent daily usage used for the cautious scenario."),
                item("Minimum complete days", f"{home['daily_total_min_full_days']} days", "History needed before using a daily load percentile."),
                item("Fallback household load", percent(home["worst_case_fallback_load_factor"]), "Share of the estimated load used when history is sparse."),
                item("Charging efficiency", percent(home["charge_efficiency"]), "Estimated energy retained while charging the battery."),
                item("Discharging efficiency", percent(home["discharge_efficiency"]), "Estimated energy delivered from the battery."),
                item("Maximum charging power", f"{home['battery_max_charge_kw']:g} kW", "Planner limit for home-battery input."),
                item("Maximum discharge power", f"{home['battery_max_discharge_kw']:g} kW", "Planner limit for home-battery output."),
                item("Charging tapers at", f"{home['battery_taper_soc_percent']:g}%", "Charge level where the planner reduces charging speed."),
                item("Tapered charging power", f"{home['battery_taper_charge_kw']:g} kW", "Planner power limit after the taper point."),
                item("Smallest grid top-up", f"{home['min_grid_charge_kwh']:g} kWh", "Smaller top-ups are not recommended."),
                item("Household history", f"{home['history_days']} days", "Past usage considered for the home load profile."),
                item("Planning lead time", f"{home['planning_lead_hours']} hours", "How early before the overnight window a plan may run."),
            ],
        },
        {
            "title": "BYD DOLPHIN",
            "description": "Vehicle and driving assumptions for charging advice.",
            "items": [
                item("Vehicle battery capacity", f"{vehicle['capacity_kwh']:g} kWh", "Battery size assumed for the car."),
                item("Driving reserve", f"{vehicle['min_soc_percent']:g}%", "Minimum vehicle charge kept after expected driving."),
                item("Maximum charger current", f"{vehicle['max_current_amps']} A", "Upper limit of the recommended charge current."),
                item("Charger voltage", f"{vehicle['voltage_v']} V", "Voltage used to estimate charging power."),
                item("Charging efficiency", percent(vehicle["charge_efficiency"]), "Grid energy expected to reach the vehicle battery."),
                item("Home during daylight", f"{vehicle['daytime_home_start']}–{vehicle['daytime_home_end']}", "Hours when solar charging may be recommended."),
                item("Minimum daily driving", f"{vehicle['fallback_daily_km']:g} km", "Driving estimate used when trip history is sparse."),
                item("Fallback energy use", f"{vehicle['fallback_consumption_kwh_per_100km']:g} kWh / 100 km", "Estimated energy needed per distance driven."),
                item("Driving estimate", percentile(vehicle["distance_quantile"]), "Recent daily distance used when enough trips are available."),
                item("Driving history", f"{vehicle['history_days']} days", "Past trips considered for the driving estimate."),
                item("Vehicle reading age limit", f"{vehicle['max_vehicle_age_hours']} hours", "Older vehicle data is not used for new advice."),
                item("Solar charge ceiling", f"{vehicle['solar_soc_cap_percent']:g}%", "Vehicle charge limit for daytime solar top-ups."),
            ],
        },
    ]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "site/data/settings.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_settings_report(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()