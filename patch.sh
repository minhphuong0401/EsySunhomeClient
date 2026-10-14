#!/usr/bin/env bash
# Applies: night-charge details, load projection, and decision time / trigger / history.
# Run from anywhere inside the EsySunhomeClient repository.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
git pull --rebase --autostash

patch_file="$(mktemp)"
trap 'rm -f "$patch_file"' EXIT
cat > "$patch_file" <<'PATCH'
diff --git a/README.md b/README.md
index c9daf29..55f2d85 100644
--- a/README.md
+++ b/README.md
@@ -84,10 +84,16 @@ refreshes the forecast at most once an hour and caches it in
 
 The dashboard's "Grid charging decisions" table shows the last plan made for
 each of the last 5 nights next to what actually happened between 06:00 and
-midnight: solar, load, and the lowest and peak SOC, each with an icon comparing
-it with the forecast (forecasts assume no grid charge). Select a night to see
-the forecasts, PV so far for a day in progress, and the full-day load
-(00:00–24:00). The result shows the decision and
+midnight: solar, load, and the lowest and peak SOC (forecasts assume no grid
+charge). Each actual value has an icon: ★ at or better than the forecast, ✓
+between the forecast and the worst case, ✗ at or worse than the worst case
+(for load, lower is better). Select a night to see the forecast, worst case and
+actual for each value, including solar and load so far for a day in progress and
+the full-day load (00:00–24:00). Until the day ends, load shows a projection
+(≈): load so far plus the rest of the day's forecast. The Decision column also
+shows how and when the shown plan was made (scheduled, manual or replay), and
+the expanded view lists every plan made for that night, with identical
+consecutive scheduled decisions merged. The result shows the decision and
 whether it was right, by comparing the actual lowest SOC with the 30% target:
 "No charge – correct" (green), "No charge – fell below 30%" (red),
 "Charge – correct" (blue) and "Planned charge – not needed" (yellow). The
diff --git a/scripts/build_night_charge_report.py b/scripts/build_night_charge_report.py
index 76b3000..8656077 100644
--- a/scripts/build_night_charge_report.py
+++ b/scripts/build_night_charge_report.py
@@ -21,7 +21,7 @@ from scripts.build_history import (
     _parse_timestamp,
     load_tariff,
 )
-from scripts.plan_night_charge import SLOT, _iso, _parse_utc
+from scripts.plan_night_charge import SLOT, _iso, _parse_utc, load_config
 
 
 PLAN_PATH = "data/night_charge_plan.json"
@@ -47,19 +47,64 @@ def _git_json(path: str, since: datetime) -> list[tuple[str, dict[str, Any]]]:
 
 def latest_plans(plans: list[dict[str, Any]], nights: int) -> list[dict[str, Any]]:
     """Keep the last plan generated for each window, newest windows first."""
-    by_window: dict[str, tuple[datetime, dict[str, Any]]] = {}
+    by_window: dict[str, tuple[tuple[datetime, str], dict[str, Any]]] = {}
     for plan in plans:
         try:
             start = plan["window"]["start"]
-            generated = _parse_utc(plan["generatedAt"])
+            # A replay keeps the original plan time, so the replay time breaks the tie.
+            key = (_parse_utc(plan["generatedAt"]), plan.get("replayedAt") or "")
         except (AttributeError, KeyError, TypeError, ValueError):
             continue
-        if start not in by_window or generated > by_window[start][0]:
-            by_window[start] = (generated, plan)
+        if start not in by_window or key > by_window[start][0]:
+            by_window[start] = (key, plan)
     ordered = sorted(by_window.items(), key=lambda item: _parse_utc(item[0]), reverse=True)
     return [plan for _, (_, plan) in ordered[:nights]]
 
 
+def plan_trigger(plan: dict[str, Any], lead: timedelta) -> str:
+    """How a plan was made: scheduled, manual (outside the planning window) or replay."""
+    if plan.get("trigger"):
+        return plan["trigger"]
+    # Older plans predate the "trigger" field, so infer it.
+    generated = _parse_utc(plan["generatedAt"])
+    fetched = plan.get("forecastFetchedAt")
+    if fetched and _parse_utc(fetched) > generated:
+        return "replay"
+    return "manual" if generated < _parse_utc(plan["window"]["start"]) - lead else "scheduled"
+
+
+def decision_history(plans: list[dict[str, Any]], lead: timedelta) -> list[dict[str, Any]]:
+    """A window's plans, oldest first, with consecutive identical decisions merged into one run."""
+    # Older replays have no replayedAt, but their forecast was fetched later than the original's.
+    unique = {
+        (plan["generatedAt"], plan.get("replayedAt") or plan.get("forecastFetchedAt") or ""): plan for plan in plans
+    }
+    runs: list[dict[str, Any]] = []
+    for key in sorted(unique, key=lambda item: (_parse_utc(item[0]), item[1])):
+        plan = unique[key]
+        trigger = plan_trigger(plan, lead)
+        same = (plan.get("decision"), plan.get("targetSoc"), trigger)
+        if runs and trigger != "replay" and (runs[-1]["decision"], runs[-1]["targetSoc"], runs[-1]["trigger"]) == same:
+            runs[-1]["to"] = plan["generatedAt"]
+            runs[-1]["count"] += 1
+            runs[-1]["gridCharge_kWh"] = plan.get("gridCharge_kWh")
+            continue
+        runs.append(
+            {
+                "from": plan["generatedAt"],
+                "to": plan["generatedAt"],
+                "count": 1,
+                "decision": plan.get("decision"),
+                "targetSoc": plan.get("targetSoc"),
+                "gridCharge_kWh": plan.get("gridCharge_kWh"),
+                "trigger": trigger,
+                # Older replays lack replayedAt; their forecast was fetched when they ran.
+                "replayedAt": plan.get("replayedAt") or (plan.get("forecastFetchedAt") if trigger == "replay" else None),
+            }
+        )
+    return runs
+
+
 def _difference(end: dict[str, Any], start: dict[str, Any], field: str) -> float | None:
     try:
         return round(float(end[field]) - float(start[field]), 2)
@@ -67,9 +112,9 @@ def _difference(end: dict[str, Any], start: dict[str, Any], field: str) -> float
         return None
 
 
-def _pv_forecast_until(plan: dict[str, Any], until: datetime) -> float | None:
-    """Expected PV from the window end until `until`, or None for plans without half-hourly slots."""
-    slots = plan["scenarios"]["expected"].get("pvSlotsAfterWindow_kWh")
+def _forecast_until(plan: dict[str, Any], slots_key: str, until: datetime) -> float | None:
+    """Expected kWh from the window end until `until`, or None for plans without half-hourly slots."""
+    slots = plan["scenarios"]["expected"].get(slots_key)
     if not slots:
         return None
     slot_start = _parse_utc(plan["window"]["end"])
@@ -82,6 +127,37 @@ def _pv_forecast_until(plan: dict[str, Any], until: datetime) -> float | None:
     return round(total, 2)
 
 
+def _worst_ratio(plan: dict[str, Any], total_key: str) -> float:
+    # The worst case scales every expected slot by one factor, so partial totals scale the same way.
+    expected_total = plan["scenarios"]["expected"].get(total_key) or 0
+    worst_total = plan["scenarios"].get("worstCase", {}).get(total_key) or 0
+    return worst_total / expected_total if expected_total else 0
+
+
+def _so_far(plan: dict[str, Any], as_of: datetime, latest: dict[str, Any], start: dict[str, Any]) -> dict[str, Any] | None:
+    """Actual vs forecast from 06:00 until the latest reading, plus end-of-day load projections."""
+    pv_forecast = _forecast_until(plan, "pvSlotsAfterWindow_kWh", as_of)
+    load_forecast = _forecast_until(plan, "loadSlotsAfterWindow_kWh", as_of)
+    if pv_forecast is None and load_forecast is None:
+        return None
+    so_far: dict[str, Any] = {"asOf": _iso(as_of)}
+    if pv_forecast is not None:
+        so_far["pvForecast_kWh"] = pv_forecast
+        so_far["pvWorstCase_kWh"] = round(pv_forecast * _worst_ratio(plan, "pvAfterWindow_kWh"), 2)
+        so_far["pv_kWh"] = _difference(latest, start, FIELDS["pv_kWh"])
+    if load_forecast is not None:
+        load_actual = _difference(latest, start, FIELDS["load_kWh"])
+        remaining = (plan["scenarios"]["expected"].get("loadAfterWindow_kWh") or 0) - load_forecast
+        load_today = _difference(latest, {FIELDS["load_kWh"]: 0}, FIELDS["load_kWh"])
+        so_far["loadForecast_kWh"] = load_forecast
+        so_far["loadWorstCase_kWh"] = round(load_forecast * _worst_ratio(plan, "loadAfterWindow_kWh"), 2)
+        so_far["load_kWh"] = load_actual
+        # Projection: what has been used so far plus the rest of today's expected load.
+        so_far["loadProjected_kWh"] = round(load_actual + remaining, 2) if load_actual is not None else None
+        so_far["loadDayProjected_kWh"] = round(load_today + remaining, 2) if load_today is not None else None
+    return so_far
+
+
 def actual_outcome(plan: dict[str, Any], snapshots: list[tuple[datetime, dict[str, Any]]]) -> dict[str, Any]:
     """Summarize the snapshots between the window end and the next window (the planning horizon)."""
     window_start = _parse_utc(plan["window"]["start"])
@@ -114,14 +190,7 @@ def actual_outcome(plan: dict[str, Any], snapshots: list[tuple[datetime, dict[st
     outcome["loadDay_kWh"] = _difference(inside[-1][1], {FIELDS["load_kWh"]: 0}, FIELDS["load_kWh"]) if complete else None
     outcome["soFar"] = None
     if not complete and inside and start is not None:
-        as_of, latest = inside[-1]
-        forecast = _pv_forecast_until(plan, as_of)
-        if forecast is not None:
-            outcome["soFar"] = {
-                "asOf": _iso(as_of),
-                "pvForecast_kWh": forecast,
-                "pv_kWh": _difference(latest, start, FIELDS["pv_kWh"]),
-            }
+        outcome["soFar"] = _so_far(plan, inside[-1][0], inside[-1][1], start)
     return outcome
 
 
@@ -141,7 +210,14 @@ def build_report(
     now: datetime,
 ) -> dict[str, Any]:
     tz = load_tariff().timezone
+    lead = timedelta(hours=load_config().planning_lead_hours)
     snapshots = sorted(snapshots, key=lambda item: item[0])
+    by_window: dict[str, list[dict[str, Any]]] = {}
+    for plan in plans:
+        try:
+            by_window.setdefault(plan["window"]["start"], []).append(plan)
+        except (KeyError, TypeError):
+            continue
     report_nights = []
     for plan in latest_plans(plans, nights):
         actual = actual_outcome(plan, snapshots)
@@ -149,6 +225,8 @@ def build_report(
             {
                 "night": _parse_utc(plan["window"]["start"]).astimezone(tz).date().isoformat(),
                 "plan": plan,
+                "trigger": plan_trigger(plan, lead),
+                "history": decision_history(by_window[plan["window"]["start"]], lead),
                 "actual": actual,
                 "verdict": verdict(plan, actual),
             }
diff --git a/scripts/plan_night_charge.py b/scripts/plan_night_charge.py
index cd41b95..953a0ab 100644
--- a/scripts/plan_night_charge.py
+++ b/scripts/plan_night_charge.py
@@ -326,8 +326,9 @@ def build_plan(
             "peakSocWithoutCharge": round(peak, 1),
         }
         if name == "expected":
-            # Half-hour slots starting at the window end; the dashboard compares them with PV so far.
+            # Half-hour slots starting at the window end; the dashboard compares them with actuals so far.
             results[name]["pvSlotsAfterWindow_kWh"] = [round(pv, 3) for pv, _ in after]
+            results[name]["loadSlotsAfterWindow_kWh"] = [round(load_kwh, 3) for _, load_kwh in after]
 
     if missing:
         warnings.append(f"No PV forecast for {len(missing)} half-hour slots; assumed zero PV.")
@@ -454,6 +455,8 @@ def _replay_plan(night: date, tariff: Tariff, config: PlannerConfig) -> dict[str
         forecast,
         warnings,
     )
+    plan["trigger"] = "replay"
+    plan["replayedAt"] = _iso(datetime.now(timezone.utc).replace(microsecond=0))
     return plan
 
 
@@ -494,6 +497,8 @@ def main() -> int:
             plan = build_plan(
                 now, float(current["batterySoc_percent"]), window, config, tariff, profile, forecast, warnings
             )
+            scheduled = planning_window(now, tariff, config.planning_lead_hours) is not None
+            plan["trigger"] = "scheduled" if scheduled else "manual"
         args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
     except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError, KeyError, TypeError, ImportError) as error:
         print(f"Could not plan night charge: {error}", file=sys.stderr)
diff --git a/site/app.js b/site/app.js
index 8cdcbd6..17b973d 100644
--- a/site/app.js
+++ b/site/app.js
@@ -484,48 +484,79 @@ function makeActualCell(value, trend, note) {
   return cell;
 }
 
-function makeDetailLine(label, parts) {
-  const term = document.createElement("dt");
-  term.textContent = label;
-  const detail = document.createElement("dd");
-  parts.forEach(([name, value, trend], index) => {
-    if (index > 0) detail.append(" · ");
-    const part = document.createElement("span");
-    part.className = "plan-detail-part";
-    const partName = document.createElement("span");
-    partName.className = "plan-detail-name";
-    partName.textContent = `${name} `;
-    const partValue = document.createElement("strong");
-    partValue.textContent = value;
-    part.append(partName);
-    if (trend) part.append(makeTrendIcon(trend));
-    part.append(partValue);
-    detail.append(part);
-  });
-  return [term, detail];
+function makeDetailsTable(rows, headings = ["", "Forecast", "Worst case", "Actual"]) {
+  const table = document.createElement("table");
+  table.className = "plan-details-table";
+  const headRow = document.createElement("tr");
+  for (const heading of headings) {
+    const cell = document.createElement("th");
+    cell.scope = "col";
+    cell.textContent = heading;
+    headRow.append(cell);
+  }
+  const head = document.createElement("thead");
+  head.append(headRow);
+  const body = document.createElement("tbody");
+  body.append(...rows);
+  table.append(head, body);
+  return table;
 }
 
-// The arrow shows actual vs forecast; the colour shows whether that is good for the battery.
-function actualTrend(actual, forecast, higherIsGood) {
-  const actualValue = numberOrNull(actual);
-  const forecastValue = numberOrNull(forecast);
-  if (actualValue === null || forecastValue === null) return null;
-  const higher = actualValue >= forecastValue;
-  return {
-    symbol: higher ? "▲" : "▼",
-    tone: higher === higherIsGood ? "good" : "bad",
-    title: higher ? "At or above forecast" : "Below forecast",
-  };
+// ★ at or better than the forecast, ✓ between the forecast and worst case, ✗ at or worse than the worst case.
+function rangeTrend(actual, forecast, worst, higherIsGood = true) {
+  const values = [actual, forecast, worst].map(numberOrNull);
+  if (values.includes(null)) return null;
+  const [actualValue, forecastValue, worstValue] = higherIsGood ? values : values.map((value) => -value);
+  if (actualValue >= forecastValue) return { symbol: "★", tone: "great", title: "At or better than the forecast" };
+  if (actualValue > worstValue) return { symbol: "✓", tone: "good", title: "Between the forecast and the worst case" };
+  return { symbol: "✗", tone: "bad", title: "At or worse than the worst case" };
+}
+
+const PROJECTED_TITLE = "Projected: load so far plus the rest of today's forecast";
+const TRIGGER_LABELS = { scheduled: "Scheduled", manual: "Manual", replay: "Replay" };
+
+const formatPlanTime = (timestamp) =>
+  formatDate(timestamp, { weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
+
+function describeTrigger(trigger, replayedAt) {
+  const label = TRIGGER_LABELS[trigger] ?? "Scheduled";
+  return trigger === "replay" && replayedAt ? `${label} (run ${formatPlanTime(replayedAt)})` : label;
 }
 
-function socRangeTrend(actual, expected, worst) {
-  const actualValue = numberOrNull(actual);
-  const expectedValue = numberOrNull(expected);
-  const worstValue = numberOrNull(worst);
-  if (actualValue === null || expectedValue === null || worstValue === null) return null;
-  if (actualValue >= expectedValue) return { symbol: "★", tone: "great", title: "At or above the expected forecast" };
-  if (actualValue > worstValue) return { symbol: "✓", tone: "good", title: "Between the worst case and expected forecasts" };
-  return { symbol: "✗", tone: "bad", title: "At or below the worst-case forecast" };
+function makeHistoryTable(history) {
+  const rows = history.map((run) => {
+    const row = document.createElement("tr");
+    const time = run.count > 1
+      ? `${formatPlanTime(run.from)} – ${formatPlanTime(run.to)} (${run.count} runs)`
+      : formatPlanTime(run.from);
+    const charging = run.decision === "charge";
+    row.append(
+      makeCell(time),
+      makeCell(charging ? `Charge to ${run.targetSoc}%` : "No charge"),
+      makeCell(charging ? formatAmount(run.gridCharge_kWh, " kWh") : "—"),
+      makeCell(describeTrigger(run.trigger, run.replayedAt)),
+    );
+    return row;
+  });
+  const table = makeDetailsTable(rows, ["Plan time", "Decision", "Grid charge", "How"]);
+  table.classList.add("plan-history-table");
+  const caption = document.createElement("caption");
+  caption.textContent = "Decision history";
+  table.prepend(caption);
+  return table;
+}
+
+function makeRangeLine(label, forecast, worst, actual, suffix, trend, projected = false) {
+  const row = document.createElement("tr");
+  const name = document.createElement("th");
+  name.scope = "row";
+  name.textContent = label;
+  const actualText = formatAmount(actual, suffix);
+  const actualCell = makeCell(projected && actualText !== "—" ? `≈ ${actualText}` : actualText, "plan-details-actual");
+  if (projected) actualCell.title = PROJECTED_TITLE;
+  if (trend) actualCell.prepend(makeTrendIcon(trend));
+  row.append(name, makeCell(formatAmount(forecast, suffix)), makeCell(formatAmount(worst, suffix)), actualCell);
+  return row;
 }
 
 const formatAmount = (value, suffix = "") => {
@@ -556,7 +587,7 @@ function renderNightChargeRows(nights, emptyMessage) {
   }
 
   const nightFormat = new Intl.DateTimeFormat("en-AU", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
-  for (const { night, plan, actual, verdict } of nights) {
+  for (const { night, plan, actual, verdict, trigger, history } of nights) {
     const [year, month, day] = night.split("-").map(Number);
     const expected = plan.scenarios?.expected ?? {};
     const worst = plan.scenarios?.worstCase ?? {};
@@ -565,14 +596,19 @@ function renderNightChargeRows(nights, emptyMessage) {
     const soFar = actual.soFar;
     const soFarTime = soFar ? formatDate(soFar.asOf, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) : null;
     const soFarNote = actual.complete ? null : "so far";
+    // Until the day ends, show where load is heading rather than a blank.
+    const projecting = !actual.complete && numberOrNull(soFar?.loadProjected_kWh) !== null;
+    const load06To24 = projecting ? soFar.loadProjected_kWh : actual.load_kWh;
+    const loadFullDay = projecting ? soFar.loadDayProjected_kWh : actual.loadDay_kWh;
 
     const trends = {
-      solar: actualTrend(actual.pv_kWh, expected.pvAfterWindow_kWh, true),
-      solarSoFar: soFar ? actualTrend(soFar.pv_kWh, soFar.pvForecast_kWh, true) : null,
-      load: actualTrend(actual.load_kWh, expected.loadAfterWindow_kWh, false),
-      loadDay: actualTrend(actual.loadDay_kWh, plan.dailyLoad_kWh?.expected, false),
-      lowest: socRangeTrend(actual.minSoc, expected.minSocWithoutCharge, worst.minSocWithoutCharge),
-      peak: socRangeTrend(actual.maxSoc, expected.peakSocWithoutCharge, worst.peakSocWithoutCharge),
+      solar: rangeTrend(actual.pv_kWh, expected.pvAfterWindow_kWh, worst.pvAfterWindow_kWh),
+      solarSoFar: soFar ? rangeTrend(soFar.pv_kWh, soFar.pvForecast_kWh, soFar.pvWorstCase_kWh) : null,
+      load: rangeTrend(load06To24, expected.loadAfterWindow_kWh, worst.loadAfterWindow_kWh, false),
+      loadSoFar: soFar ? rangeTrend(soFar.load_kWh, soFar.loadForecast_kWh, soFar.loadWorstCase_kWh, false) : null,
+      loadDay: rangeTrend(loadFullDay, plan.dailyLoad_kWh?.expected, plan.dailyLoad_kWh?.worstCase, false),
+      lowest: rangeTrend(actual.minSoc, expected.minSocWithoutCharge, worst.minSocWithoutCharge),
+      peak: rangeTrend(actual.maxSoc, expected.peakSocWithoutCharge, worst.peakSocWithoutCharge),
     };
 
     const detailsId = `night-charge-details-${night}`;
@@ -599,6 +635,14 @@ function renderNightChargeRows(nights, emptyMessage) {
       cost.textContent = `${formatAmount(plan.gridCharge_kWh, " kWh")} · ${formatCurrency(plan.estimatedChargeCost_AUD)}`;
       decision.append(cost);
     }
+    const madeAt = document.createElement("span");
+    madeAt.className = "plan-note";
+    madeAt.textContent = `${TRIGGER_LABELS[trigger] ?? "Scheduled"} · ${formatPlanTime(plan.generatedAt)}`;
+    if (trigger === "replay") {
+      const replayedAt = plan.replayedAt ?? plan.forecastFetchedAt;
+      madeAt.title = `Recomputed${replayedAt ? ` ${formatPlanTime(replayedAt)}` : ""} from the data at the original plan time`;
+    }
+    decision.append(madeAt);
 
     const result = document.createElement("td");
     const badge = document.createElement("span");
@@ -610,49 +654,40 @@ function renderNightChargeRows(nights, emptyMessage) {
       ? makeActualCell(formatAmount(actual.pv_kWh, " kWh"), trends.solar)
       : makeActualCell(formatAmount(soFar.pv_kWh, " kWh"), trends.solarSoFar, `to ${soFarTime}`);
 
+    const loadCell = projecting
+      ? makeActualCell(`≈ ${formatAmount(load06To24, " kWh")}`, trends.load, "projected")
+      : makeActualCell(formatAmount(actual.load_kWh, " kWh"), trends.load);
+    if (projecting) loadCell.title = PROJECTED_TITLE;
+
     const summary = document.createElement("tr");
     summary.className = "plan-summary";
     summary.append(
       nightCell,
       decision,
       solarCell,
-      makeActualCell(formatAmount(actual.load_kWh, " kWh"), trends.load),
+      loadCell,
       makeActualCell(formatAmount(actual.minSoc, "%"), trends.lowest, actual.minSoc == null ? null : soFarNote),
       makeActualCell(formatAmount(actual.maxSoc, "%"), trends.peak, actual.maxSoc == null ? null : soFarNote),
       result,
     );
 
-    const list = document.createElement("dl");
-    list.className = "plan-details-list";
-    list.append(
-      ...makeDetailLine("Solar 06–24", [
-        ["Forecast", formatAmount(expected.pvAfterWindow_kWh, " kWh")],
-        ["Actual", formatAmount(actual.pv_kWh, " kWh"), trends.solar],
-        ...(soFar ? [
-          [`To ${soFarTime} forecast`, formatAmount(soFar.pvForecast_kWh, " kWh")],
-          [`To ${soFarTime} actual`, formatAmount(soFar.pv_kWh, " kWh"), trends.solarSoFar],
-        ] : []),
-      ]),
-      ...makeDetailLine("Load", [
-        ["06–24 forecast", formatAmount(expected.loadAfterWindow_kWh, " kWh")],
-        ["06–24 actual", formatAmount(actual.load_kWh, " kWh"), trends.load],
-        ["Full day forecast", formatAmount(plan.dailyLoad_kWh?.expected, " kWh")],
-        ["Full day actual", formatAmount(actual.loadDay_kWh, " kWh"), trends.loadDay],
-      ]),
-      ...makeDetailLine("Lowest SOC 06–24", [
-        ["Expected", formatAmount(expected.minSocWithoutCharge, "%")],
-        ["Worst case", formatAmount(worst.minSocWithoutCharge, "%")],
-        ["Actual", formatAmount(actual.minSoc, "%"), trends.lowest],
-      ]),
-      ...makeDetailLine("Peak SOC 06–24", [
-        ["Expected", formatAmount(expected.peakSocWithoutCharge, "%")],
-        ["Worst case", formatAmount(worst.peakSocWithoutCharge, "%")],
-        ["Actual", formatAmount(actual.maxSoc, "%"), trends.peak],
-      ]),
-    );
+    const list = makeDetailsTable([
+      makeRangeLine("Solar 06–24", expected.pvAfterWindow_kWh, worst.pvAfterWindow_kWh, actual.pv_kWh, " kWh", trends.solar),
+      ...(soFar
+        ? [makeRangeLine(`Solar 06–${soFarTime}`, soFar.pvForecast_kWh, soFar.pvWorstCase_kWh, soFar.pv_kWh, " kWh", trends.solarSoFar)]
+        : []),
+      makeRangeLine("Load 06–24", expected.loadAfterWindow_kWh, worst.loadAfterWindow_kWh, load06To24, " kWh", trends.load, projecting),
+      ...(numberOrNull(soFar?.loadForecast_kWh) !== null
+        ? [makeRangeLine(`Load 06–${soFarTime}`, soFar.loadForecast_kWh, soFar.loadWorstCase_kWh, soFar.load_kWh, " kWh", trends.loadSoFar)]
+        : []),
+      makeRangeLine("Load full day", plan.dailyLoad_kWh?.expected, plan.dailyLoad_kWh?.worstCase, loadFullDay, " kWh", trends.loadDay, projecting),
+      makeRangeLine("Lowest SOC 06–24", expected.minSocWithoutCharge, worst.minSocWithoutCharge, actual.minSoc, "%", trends.lowest),
+      makeRangeLine("Peak SOC 06–24", expected.peakSocWithoutCharge, worst.peakSocWithoutCharge, actual.maxSoc, "%", trends.peak),
+    ]);
     const detailsCell = document.createElement("td");
     detailsCell.colSpan = NIGHT_CHARGE_COLUMNS;
     detailsCell.append(list);
+    if (history?.length) detailsCell.append(makeHistoryTable(history));
     const details = document.createElement("tr");
     details.className = "plan-details";
     details.id = detailsId;
diff --git a/site/index.html b/site/index.html
index b664be0..cf82285 100644
--- a/site/index.html
+++ b/site/index.html
@@ -26,9 +26,9 @@
     </script>
     <link rel="icon" type="image/svg+xml" href="favicon.svg">
     <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
-    <link rel="stylesheet" href="styles.css?v=16">
+    <link rel="stylesheet" href="styles.css?v=20">
     <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js" defer></script>
-    <script src="app.js?v=16" defer></script>
+    <script src="app.js?v=20" defer></script>
   </head>
   <body>
     <main class="page">
diff --git a/site/styles.css b/site/styles.css
index 1456e36..f590eb3 100644
--- a/site/styles.css
+++ b/site/styles.css
@@ -277,11 +277,15 @@ h4 { margin: 0 0 4px; font-size: 14px; letter-spacing: -.02em; }
 .plan-actual { font-variant-numeric: tabular-nums; font-weight: 600; }
 .plan-note { display: block; color: var(--muted); font-size: 10px; font-weight: 400; }
 .plan-table .plan-details td { padding-top: 0; white-space: normal; }
-.plan-details-list { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 0; padding: 12px 14px; border-radius: 12px; background: var(--input-surface); }
-.plan-details-list dt { color: var(--muted); font-weight: 600; }
-.plan-details-list dd { margin: 0; font-variant-numeric: tabular-nums; }
-.plan-detail-name { color: var(--muted); }
-.plan-detail-part { white-space: nowrap; }
+.plan-details-table { width: auto; border-collapse: separate; border-spacing: 0; padding: 6px 10px; border-radius: 12px; background: var(--input-surface); }
+.plan-table .plan-details-table th, .plan-table .plan-details-table td { padding: 5px 14px; border: 0; font-variant-numeric: tabular-nums; }
+.plan-table .plan-details-table thead th { font-size: 10px; text-align: right; }
+.plan-table .plan-details-table tbody th { color: var(--muted); font-size: 12px; font-weight: 600; letter-spacing: normal; text-align: left; }
+.plan-table .plan-details-table td { text-align: right; }
+.plan-table .plan-details-table .plan-details-actual { font-weight: 600; }
+.plan-history-table { margin-top: 10px; }
+.plan-history-table caption { padding: 0 14px 4px; color: var(--muted); font-size: 10px; font-weight: 600; letter-spacing: .04em; text-align: left; }
+.plan-table .plan-history-table thead th, .plan-table .plan-history-table td { text-align: left; }
 .plan-warning { margin-left: 6px; color: var(--series-export); cursor: help; }
 .plan-trend { margin-right: 5px; font-size: 10px; cursor: help; }
 .plan-trend-great { color: var(--series-solar); font-size: 12px; font-weight: 700; }
diff --git a/tests/test_build_night_charge_report.py b/tests/test_build_night_charge_report.py
index b0e7885..937ca77 100644
--- a/tests/test_build_night_charge_report.py
+++ b/tests/test_build_night_charge_report.py
@@ -4,7 +4,7 @@ import unittest
 from datetime import datetime, timedelta, timezone
 
 from scripts.build_history import TARIFF_PATH, load_tariff
-from scripts.build_night_charge_report import actual_outcome, build_report, latest_plans, verdict
+from scripts.build_night_charge_report import actual_outcome, build_report, decision_history, latest_plans, verdict
 
 
 def _iso(value: datetime) -> str:
@@ -81,16 +81,63 @@ class NightChargeReportTests(unittest.TestCase):
     def test_pending_day_compares_pv_so_far_with_forecast(self) -> None:
         plan = self._plan(12)
         plan["scenarios"]["expected"]["pvSlotsAfterWindow_kWh"] = [1.0] * 36
+        plan["scenarios"]["expected"]["pvAfterWindow_kWh"] = 36.0
+        plan["scenarios"]["worstCase"] = {"pvAfterWindow_kWh": 27.0}
         snapshots = [self._snapshot(12, 5, 45, 60, 0.0, 2.0, 0.1), self._snapshot(12, 10, 15, 70, 9.5, 5.0, 0.2)]
 
         outcome = actual_outcome(plan, snapshots)
 
         # 06:00-10:15 covers eight full slots and half of the ninth.
         self.assertEqual(outcome["soFar"]["pvForecast_kWh"], 8.5)
+        self.assertEqual(outcome["soFar"]["pvWorstCase_kWh"], 6.38)
         self.assertEqual(outcome["soFar"]["pv_kWh"], 9.5)
         self.assertEqual(outcome["soFar"]["asOf"], _iso(self._local(2026, 10, 12, 10, 15)))
         self.assertIsNone(actual_outcome(self._plan(12), snapshots)["soFar"])
 
+    def test_pending_day_projects_end_of_day_load(self) -> None:
+        plan = self._plan(12)
+        plan["scenarios"]["expected"]["loadSlotsAfterWindow_kWh"] = [0.5] * 36
+        plan["scenarios"]["expected"]["loadAfterWindow_kWh"] = 18.0
+        plan["scenarios"]["worstCase"] = {"loadAfterWindow_kWh": 21.6}
+        snapshots = [self._snapshot(12, 5, 45, 60, 0.0, 2.0, 0.1), self._snapshot(12, 12, 0, 50, 9.0, 9.0, 0.2)]
+
+        so_far = actual_outcome(plan, snapshots)["soFar"]
+
+        self.assertEqual(so_far["loadForecast_kWh"], 6.0)
+        self.assertEqual(so_far["loadWorstCase_kWh"], 7.2)
+        self.assertEqual(so_far["load_kWh"], 7.0)
+        # 7 kWh used since 06:00 plus the 12 kWh still expected for 12:00-24:00.
+        self.assertEqual(so_far["loadProjected_kWh"], 19.0)
+        self.assertEqual(so_far["loadDayProjected_kWh"], 21.0)
+        self.assertNotIn("pv_kWh", so_far)
+
+    def test_decision_history_merges_runs_and_keeps_replays_separate(self) -> None:
+        def plan_at(hour: int, minute: int, decision: str, target: int | None, **extra) -> dict:
+            plan = self._plan(12, decision)
+            plan["generatedAt"] = _iso(self._local(2026, 10, 11 if hour >= 12 else 12, hour, minute))
+            plan["targetSoc"] = target
+            plan.update(extra)
+            return plan
+
+        original = plan_at(5, 45, "no_charge", None)
+        replay = dict(original, trigger="replay", replayedAt="2026-10-12T01:00:00Z", decision="charge", targetSoc=40)
+        plans = [
+            plan_at(15, 0, "charge", 35),
+            plan_at(22, 0, "charge", 35),
+            plan_at(22, 15, "charge", 35),
+            plan_at(23, 0, "no_charge", None),
+            original,
+            replay,
+        ]
+
+        history = decision_history(plans, timedelta(hours=2))
+
+        self.assertEqual([run["trigger"] for run in history], ["manual", "scheduled", "scheduled", "replay"])
+        self.assertEqual(history[1]["count"], 2)
+        self.assertEqual(history[2]["count"], 2)
+        self.assertEqual(history[3]["targetSoc"], 40)
+        self.assertEqual(latest_plans(plans, 1)[0]["replayedAt"], "2026-10-12T01:00:00Z")
+
     def test_verdicts_compare_decision_with_actual_lowest_soc(self) -> None:
         low = {"complete": True, "minSoc": 22}
         high = {"complete": True, "minSoc": 48}
diff --git a/tests/test_plan_night_charge.py b/tests/test_plan_night_charge.py
index e383e1c..fc87a79 100644
--- a/tests/test_plan_night_charge.py
+++ b/tests/test_plan_night_charge.py
@@ -150,6 +150,8 @@ class NightChargePlannerTests(unittest.TestCase):
         slots = plan["scenarios"]["expected"]["pvSlotsAfterWindow_kWh"]
         self.assertEqual(len(slots), 36)
         self.assertAlmostEqual(sum(slots), plan["scenarios"]["expected"]["pvAfterWindow_kWh"])
+        load_slots = plan["scenarios"]["expected"]["loadSlotsAfterWindow_kWh"]
+        self.assertAlmostEqual(sum(load_slots), plan["scenarios"]["expected"]["loadAfterWindow_kWh"])
         self.assertGreater(worst["loadAfterWindow_kWh"], plan["scenarios"]["expected"]["loadAfterWindow_kWh"])
         self.assertEqual(plan["decision"], "no_charge")
 
PATCH

if git apply --check "$patch_file" 2>/dev/null; then
  git apply "$patch_file"
else
  echo "Patch does not apply cleanly; trying a 3-way merge (resolve any conflicts it reports)." >&2
  git apply --3way "$patch_file"
fi

if python3 -m unittest discover -s tests; then
  echo "Changes applied. Review with 'git status' / 'git diff', then commit and push."
else
  echo "Changes applied but tests failed; review before committing." >&2
  exit 1
fi