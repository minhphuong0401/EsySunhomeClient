# ESY Sunhome Client

Fetch daily energy data and battery state of charge from an ESY Sunhome
inverter through its authenticated API and MQTT connection.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

When available, the client uses API tokens. If neither token is configured,
it falls back to the ESY account credentials:

```bash
export ESY_ACCESS_TOKEN="..."
export ESY_REFRESH_TOKEN="..."
# Or:
export ESY_USERNAME="you@example.com"
export ESY_PASSWORD="your-password"
python fetch_today.py
```

The GitHub Actions workflow can be started manually from the Actions tab. Add
`ESY_ACCESS_TOKEN` and/or `ESY_REFRESH_TOKEN` as repository
Actions secrets. If neither is set, configure both `ESY_USERNAME` and
`ESY_PASSWORD` secrets instead. The workflow writes the latest result to
`data/data.json` and commits it to `main` only when its contents change.
To persist tokens rotated by the ESY API, also add an
`ESY_SECRETS_UPDATE_TOKEN` repository secret containing a fine-grained GitHub
PAT with **Secrets: Read and write** access to this repository. The workflow
uses that PAT to replace `ESY_ACCESS_TOKEN` and, when returned, the rotated
`ESY_REFRESH_TOKEN`. Token state is written only to a permission-restricted
temporary file on the Actions runner and is never committed.

The JSON output contains daily PV generation, electricity bought from the
grid, electricity sold to the grid, total consumption, battery charge and
discharge energy, and battery SOC. An MQTT-derived timestamp is included when
the response header contains a valid epoch timestamp.

MQTT credentials are read from device information. If unavailable, set
`ESY_MQTT_USERNAME` and `ESY_MQTT_PASSWORD`. Do not commit credentials,
certificates, or `.env` files.

## Night-charge planner (dry run)

After each fetch, `python -m scripts.plan_night_charge` decides whether the
battery should be charged from the grid during the cheapest tariff window
(Night Saver, 00:00–06:00) and to what SOC. It only runs from two hours before
the window until the window ends, and it never changes the inverter mode yet.
To plan or recompute outside that schedule, run the "Plan night charge
(manual)" workflow. It does not fetch ESY data or rotate tokens; it uses the
latest `data/data.json` on `main`. Choose `next-night` to plan the next Night
Saver window now, or `replay` with a local date (for example, `2026-10-13`) to
recompute that night's plan from the archived energy snapshot. For a replay the
PV forecast is rebuilt from Open-Meteo's archived model runs (Historical
Forecast API). This updates the stored plan for that night; it does not change
the measured actual minimum SOC.

The plan simulates SOC in half-hour steps from the end of the window until the
next window starts, using the PV forecast from `forecast.py` and a load profile
built from up to 28 days of `data/data.json` history. The load profile keeps the
median half-hourly shape and scales it to real daily totals: the median daily
total for the expected case and the 90th-percentile daily total for the worst
case (until 7 full days exist, the shape is used as-is and the worst case adds
20%). Two scenarios must hold: the expected case (forecast PV) keeps SOC at or
above 30%, and the worst case (high load, forecast PV scaled by
`worst_case_pv_factor`, 75% by default) keeps it at or above 20%.
The simulation stops discharging at `battery_min_soc` (the inverter's lowest
SOC limit, 15%); below that the grid supplies the house. Home-battery charging
is limited to 6 kW, slowing to 2 kW at 85% SOC, and discharge is limited to
5.5 kW. These limits are independent of the PV inverter rating: set
`PV_INVERTER_KW` to 8 for this installation.
Settings live in `config/night_charge.json`.

## BYD charging advice (dry run)

The `Fetch BYD and plan EV charge` workflow is dispatched by an external
scheduler (or manually); it has no built-in cron. For the default Sydney
windows, run after the day's driving around 21:00-23:00 local time for the
upcoming cheap night, then refresh at 06:15 and optionally at 10:30 or 12:30
local time for the current day's remaining solar slots. Refresh home energy
data alongside BYD telemetry: the planner requires a home snapshot under three
hours old and vehicle telemetry under eight hours old. Schedule in Sydney local
time so daylight-saving changes do not shift these runs. Add `BYD_USERNAME` and
`BYD_PASSWORD` as Actions secrets, and
`BYD_BASE_URL` and `BYD_COUNTRY_CODE` as Actions variables for your BYD region.
The workflow takes a minimal snapshot of the first vehicle on the account with
`pybyd`: SOC, odometer, vehicle timestamp and last-50-km consumption in
kWh/100 km. It writes `data/byd.json`, without VIN or location, and calculates
`data/ev_charge_plan.json`. The latest valid advice appears on the dashboard.
Do not publish the odometer history if the repository is public and you do not
want daily driving patterns visible; Git history retains previous snapshots.

Set battery capacity (45 kWh by default), reserve SOC, maximum charger current
(integer 6-32 A), charger efficiency, solar top-up SOC cap (100% by default),
and the time the vehicle is home in `config/ev_charge.json`. The default daytime
window is 11:00-17:00 local Sydney time. Overnight charging assumes the vehicle
is also plugged in during the tariff's cheapest period, 00:00-06:00; change
the tariff if that period
changes. At 230 V single phase, the configured maximum of 32 A is about
7.36 kW from the wall, before losses. Never set a current above the installed
charger, circuit and vehicle ratings.

The planner reads daily odometer differences from committed BYD snapshots and
uses the 80th percentile of recent daily trips (weekday-specific when enough
samples exist); until enough history exists it uses the configured daily-km
minimum. A snapshot must have fresh vehicle telemetry. The overnight advice
charges only enough to cover *all* of tomorrow's estimated driving plus the
configurable reserve, even if the entire trip occurs before the car returns
home. Today's driving is already reflected in the evening SOC and is not
subtracted a second time. If the needed charge does not fit the cheap window,
the plan warns rather than claiming the reserve will be met. Runs before the
configured daytime window closes target that same local day; later runs target
the next day. Once the cheap window has ended, overnight advice is marked
closed, and daytime charging uses the freshly measured vehicle SOC and only
future half-hour slots. The no-charge driving projection conservatively assumes
the full estimated drive is still ahead if no trip timing is available.

During the selected day's configured home hours, the planner recommends using eligible
forecast PV surplus after estimated household load and the home battery's
limited charging input, even when the EV already has enough energy for the next
three estimated driving days. It charges toward the configured solar SOC cap
(100% by default) instead of exporting usable surplus; export price and later
sunny days do not prevent today's solar top-up. A separate estimate compares
the SOC after tomorrow's drive, without daytime charging, with the reserve and
next three days' driving needs. Solar can be available for the EV before the
home battery is full. Neither
the solar supply nor the feed-in credit forgone is guaranteed: household history
can already include past EV charging, and actual PV and home load can differ. The planned
charger AC energy is shown separately and is not added to the home-battery
planner's load forecast, since there is no EVSE meter or charging log to
separate past EV charging from household demand. When there is no such
surplus, it recommends no daytime charging; remaining demand can be planned
for the following night instead. The current is an integer A setting for each
listed time slot. This is advice only: the workflow cannot set charger current
or reliably stop a BYD charge through the cloud. The distance estimate cannot
guarantee an unexpected long trip, and the forecast may change, so check the
actual car SOC and charger before following a plan.

`forecast.py` models the system with pvlib from Open-Meteo weather. It reads
these repository Actions variables: `PV_LATITUDE`, `PV_LONGITUDE`, `PV_TILT`,
`PV_AZIMUTH` (pvlib convention: 0 = north, 90 = east, 180 = south, 270 = west),
`PV_KWP` (panel DC rating), `PV_INVERTER_KW` (inverter AC limit) and
`PV_SYSTEM_LOSS` (fraction, e.g. `0.15`). Export the same variables and run
`python forecast.py 7` to print a forecast for up to 16 days. The planner
refreshes the forecast at most once an hour and caches it in
`data/pv_forecast.json`; the decision is written to
`data/night_charge_plan.json`.

The dashboard's "Grid charging decisions" table shows the last plan made for
each of the last 5 nights next to what actually happened between 06:00 and
midnight: solar, load, and the lowest and peak SOC (forecasts assume no grid
charge). Each actual value has an icon: ★ at or better than the forecast, ✓
between the forecast and the worst case, ✗ at or worse than the worst case
(for load, lower is better). Select a night to see the forecast, worst case and
actual for each value, including solar and load so far for a day in progress and
the full-day load (00:00–24:00). Until the day ends, load shows a projection
(≈): load so far plus the rest of the day's forecast. Solar does the same until
the PV forecast has no energy left, then shows the latest measured total and
its reading time without waiting for midnight. The Decision column also
shows how and when the shown plan was made (scheduled, manual or replay), and
the expanded view lists every plan made for that night, with identical
consecutive scheduled decisions merged. The result compares the actual lowest
SOC with the expected-case target saved in that night's plan: "No charge –
correct" (green), "No charge – fell below target" (red), "Charge – correct"
(blue) and "Planned charge – not needed" (yellow). Hover or focus a result,
or expand its row, to see the recorded SOC and the reason for the label. These
are retrospective assessments of dry-run advice, not proof that charging
happened or would have prevented a drop. The Pages workflow generates this
from the Git history with
`python -m scripts.build_night_charge_report`.

## Energy dashboard

The static dashboard in `site/` visualizes the most recent 90 days of
`data/data.json` snapshots. The GitHub Pages workflow reads the file's Git
history and generates `site/data/history.json` during deployment; generated
history is not committed to the repository. The generation, consumption, grid
import/export, and battery charge/discharge metrics share one chart and date
range; the battery state-of-charge chart is in a separate section with its own
date range. Both ranges default to the latest seven days and can be selected
within the dashboard's 90-day history window. The energy chart uses the latest
snapshot for each Australia/Sydney calendar day, while the battery chart shows
individual snapshots. The dashboard has Auto, Light, and Dark theme modes.
Auto follows the browser's color-scheme preference, including changes while
the page is open; manually selected modes are remembered.

The read-only Settings page at `site/settings.html` shows labelled tariff,
home-battery and BYD charging assumptions. The Pages build generates
`site/data/settings.json` from an explicit allowlist of the three files in
`config/`; additional fields and credentials are not published. Settings
reflect the last Pages build, not unsaved local edits. For a local preview,
run `python3 -m scripts.build_settings_report` before serving `site/`.

Electricity prices are kept in `config/electricity_tariff.json` in AUD with
GST included: peak $0.4362/kWh, off-peak $0.2882/kWh, shoulder $0.2052/kWh,
Night Saver EV $0.08/kWh, supply $0.8716/day, and feed-in $0.04/kWh. The
history builder estimates daily import charges by apportioning cumulative
meter-reading differences across the elapsed snapshot interval and the
configured Australia/Sydney tariff periods. It adds the full daily supply
charge as a fixed daily subtraction regardless of time of day, and subtracts
import charges from the flat feed-in credit: estimated net cost is export
credit minus import charges minus supply charge. A zero-import, zero-export day
therefore has a net estimate of -$0.8716. Daily figures are estimates rather
than billing-grade readings because usage within each snapshot interval is not
measured by tariff period. Counter resets make the affected day's estimate
unavailable; missing or invalid individual readings are reported and can make
that snapshot's estimate unavailable.

Set `billing_cycle_start_day` (1–31) in `config/electricity_tariff.json` to
the first local day of each electricity billing cycle. For example, 8 means
8 October through 7 November. In a shorter month, a start day beyond its last
day is treated as that month's last day. The dashboard shows the current
Australia/Sydney cycle's estimated net cost using the last cost estimate for
each consecutive day from the cycle start, plus the latest day's estimate
separately (dated when the readings are stale).
The displayed "through" date shows how far history has been included; a
missing day or unavailable cost stops the total rather than silently skipping
it. A negative net value is a charge, and a positive one is an export credit.

To publish it, enable **Settings → Pages → Build and deployment → GitHub
Actions**. The `Deploy energy dashboard` workflow deploys on pushes to `main`
that update dashboard files or `data/data.json`, and can also be started
manually from the Actions tab. It also runs after the `Fetch today's energy
data` workflow completes successfully on `main`. Its checkout uses the full
Git history so the dashboard can build the 90-day view.

To generate the history file locally for preview:

```bash
python scripts/build_history.py --days 90 --output site/data/history.json
```

Then serve `site/` with a local HTTP server and open it in a browser. Opening
`index.html` directly from disk will not load the generated history because
the dashboard fetches the JSON file over HTTP.
