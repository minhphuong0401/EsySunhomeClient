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
grid, electricity sold to the grid, total consumption, and battery SOC. An
MQTT-derived timestamp is included when the response header contains a valid
epoch timestamp.

MQTT credentials are read from device information. If unavailable, set
`ESY_MQTT_USERNAME` and `ESY_MQTT_PASSWORD`. Do not commit credentials,
certificates, or `.env` files.

## Energy dashboard

The static dashboard in `site/` visualizes the most recent 90 days of
`data/data.json` snapshots. The GitHub Pages workflow reads the file's Git
history and generates `site/data/history.json` during deployment; generated
history is not committed to the repository. The generation, consumption, grid
import, and grid export metrics share one chart and date range; the battery
state-of-charge chart is in a separate section with its own date range. Both
ranges default to the latest seven days and can be selected within the
dashboard's 90-day history window. The energy chart uses the latest snapshot
for each local calendar day, while the battery chart shows individual
snapshots.

To publish it, enable **Settings → Pages → Build and deployment → GitHub
Actions**. The `Deploy energy dashboard` workflow deploys on pushes to `main`
that update dashboard files or `data/data.json`, and can also be started
manually from the Actions tab. Its checkout uses the full Git history so the
dashboard can build the 90-day view.

To generate the history file locally for preview:

```bash
python scripts/build_history.py --days 90 --output site/data/history.json
```

Then serve `site/` with a local HTTP server and open it in a browser. Opening
`index.html` directly from disk will not load the generated history because
the dashboard fetches the JSON file over HTTP.
