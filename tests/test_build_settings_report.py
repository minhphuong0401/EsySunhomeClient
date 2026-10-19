import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_settings_report import ROOT, build_settings_report


class SettingsReportTests(unittest.TestCase):
    def test_reports_readable_groups_and_tariff_schedule(self) -> None:
        groups = build_settings_report()["groups"]

        self.assertEqual([group["title"] for group in groups], ["Electricity & billing", "Home battery", "BYD DOLPHIN"])
        self.assertEqual([len(group["items"]) for group in groups], [4, 17, 12])
        self.assertEqual(groups[0]["items"][0]["value"], "Day 8 of each month")
        self.assertEqual(groups[0]["schedule"][0], {
            "hours": "00:00–06:00", "name": "Night saver", "price": "$0.08 / kWh",
        })
        self.assertEqual(groups[1]["items"][5]["value"], "90th percentile")

    def test_extra_config_fields_are_not_published(self) -> None:
        with TemporaryDirectory() as directory:
            config_dir = Path(directory)
            for filename in ("electricity_tariff.json", "night_charge.json", "ev_charge.json"):
                source = json.loads((ROOT / "config" / filename).read_text(encoding="utf-8"))
                source["api_key"] = "do-not-publish"
                (config_dir / filename).write_text(json.dumps(source), encoding="utf-8")

            report = build_settings_report(config_dir)

        self.assertNotIn("do-not-publish", json.dumps(report))
        self.assertNotIn("api_key", json.dumps(report))

    def test_new_rate_name_gets_a_readable_label(self) -> None:
        with TemporaryDirectory() as directory:
            config_dir = Path(directory)
            for filename in ("electricity_tariff.json", "night_charge.json", "ev_charge.json"):
                source = json.loads((ROOT / "config" / filename).read_text(encoding="utf-8"))
                if filename == "electricity_tariff.json":
                    source["rates"]["summer_saver"] = "0.10"
                    source["periods"][0]["rate"] = "summer_saver"
                (config_dir / filename).write_text(json.dumps(source), encoding="utf-8")

            schedule = build_settings_report(config_dir)["groups"][0]["schedule"]

        self.assertEqual(schedule[0]["name"], "Summer Saver")
        self.assertEqual(schedule[0]["price"], "$0.10 / kWh")


if __name__ == "__main__":
    unittest.main()