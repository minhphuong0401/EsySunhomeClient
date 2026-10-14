#!/usr/bin/env bash
# Applies: night-charge table redesign (summary rows that expand), PV so far, Peak SOC.
# Run from anywhere inside the EsySunhomeClient repository.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
git pull --rebase --autostash

patch_file="$(mktemp)"
trap 'rm -f "$patch_file"' EXIT
cat > "$patch_file" <<'PATCH'
diff --git a/README.md b/README.md
index adc7365..c9daf29 100644
--- a/README.md
+++ b/README.md
@@ -84,9 +84,10 @@ refreshes the forecast at most once an hour and caches it in
 
 The dashboard's "Grid charging decisions" table shows the last plan made for
 each of the last 5 nights next to what actually happened between 06:00 and
-midnight: solar, load, and the lowest and peak SOC (forecasts assume no grid
-charge). Load also shows the full day
-(00:00–24:00), forecast and actual. The result shows the decision and
+midnight: solar, load, and the lowest and peak SOC, each with an icon comparing
+it with the forecast (forecasts assume no grid charge). Select a night to see
+the forecasts, PV so far for a day in progress, and the full-day load
+(00:00–24:00). The result shows the decision and
 whether it was right, by comparing the actual lowest SOC with the 30% target:
 "No charge – correct" (green), "No charge – fell below 30%" (red),
 "Charge – correct" (blue) and "Planned charge – not needed" (yellow). The
diff --git a/site/app.js b/site/app.js
index 8a313d1..8cdcbd6 100644
--- a/site/app.js
+++ b/site/app.js
@@ -459,32 +459,52 @@ function makeCell(text, className) {
   return cell;
 }
 
-function makeComparisonCell(rows) {
+const NIGHT_CHARGE_COLUMNS = 7;
+
+function makeTrendIcon(trend) {
+  const icon = document.createElement("span");
+  icon.className = `plan-trend plan-trend-${trend.tone}`;
+  icon.textContent = trend.symbol;
+  icon.title = trend.title;
+  icon.setAttribute("aria-label", trend.title);
+  return icon;
+}
+
+function makeActualCell(value, trend, note) {
   const cell = document.createElement("td");
-  cell.className = "plan-comparison";
-  for (const [label, value, trend] of rows) {
-    const row = document.createElement("div");
-    row.className = "plan-comparison-row";
-    const rowLabel = document.createElement("span");
-    rowLabel.className = "plan-comparison-label";
-    rowLabel.textContent = label;
-    const rowValue = document.createElement("span");
-    rowValue.className = "plan-comparison-value";
-    if (trend) {
-      const icon = document.createElement("span");
-      icon.className = `plan-trend plan-trend-${trend.tone}`;
-      icon.textContent = trend.symbol;
-      icon.title = trend.title;
-      icon.setAttribute("aria-label", trend.title);
-      rowValue.append(icon);
-    }
-    rowValue.append(value);
-    row.append(rowLabel, rowValue);
-    cell.append(row);
+  cell.className = "plan-actual";
+  if (trend) cell.append(makeTrendIcon(trend));
+  cell.append(value);
+  if (note) {
+    const noteText = document.createElement("span");
+    noteText.className = "plan-note";
+    noteText.textContent = note;
+    cell.append(noteText);
   }
   return cell;
 }
 
+function makeDetailLine(label, parts) {
+  const term = document.createElement("dt");
+  term.textContent = label;
+  const detail = document.createElement("dd");
+  parts.forEach(([name, value, trend], index) => {
+    if (index > 0) detail.append(" · ");
+    const part = document.createElement("span");
+    part.className = "plan-detail-part";
+    const partName = document.createElement("span");
+    partName.className = "plan-detail-name";
+    partName.textContent = `${name} `;
+    const partValue = document.createElement("strong");
+    partValue.textContent = value;
+    part.append(partName);
+    if (trend) part.append(makeTrendIcon(trend));
+    part.append(partValue);
+    detail.append(part);
+  });
+  return [term, detail];
+}
+
 // The arrow shows actual vs forecast; the colour shows whether that is good for the battery.
 function actualTrend(actual, forecast, higherIsGood) {
   const actualValue = numberOrNull(actual);
@@ -498,7 +518,7 @@ function actualTrend(actual, forecast, higherIsGood) {
   };
 }
 
-function lowestSocTrend(actual, expected, worst) {
+function socRangeTrend(actual, expected, worst) {
   const actualValue = numberOrNull(actual);
   const expectedValue = numberOrNull(expected);
   const worstValue = numberOrNull(worst);
@@ -529,7 +549,7 @@ function renderNightChargeRows(nights, emptyMessage) {
   if (nights.length === 0) {
     const row = document.createElement("tr");
     const cell = makeCell(emptyMessage, "plan-empty");
-    cell.colSpan = 8;
+    cell.colSpan = NIGHT_CHARGE_COLUMNS;
     row.append(cell);
     body.append(row);
     return;
@@ -542,6 +562,28 @@ function renderNightChargeRows(nights, emptyMessage) {
     const worst = plan.scenarios?.worstCase ?? {};
     const charging = plan.decision === "charge";
     const [label, badgeClass] = nightChargeVerdict(verdict, expected.minSocTarget);
+    const soFar = actual.soFar;
+    const soFarTime = soFar ? formatDate(soFar.asOf, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) : null;
+    const soFarNote = actual.complete ? null : "so far";
+
+    const trends = {
+      solar: actualTrend(actual.pv_kWh, expected.pvAfterWindow_kWh, true),
+      solarSoFar: soFar ? actualTrend(soFar.pv_kWh, soFar.pvForecast_kWh, true) : null,
+      load: actualTrend(actual.load_kWh, expected.loadAfterWindow_kWh, false),
+      loadDay: actualTrend(actual.loadDay_kWh, plan.dailyLoad_kWh?.expected, false),
+      lowest: socRangeTrend(actual.minSoc, expected.minSocWithoutCharge, worst.minSocWithoutCharge),
+      peak: socRangeTrend(actual.maxSoc, expected.peakSocWithoutCharge, worst.peakSocWithoutCharge),
+    };
+
+    const detailsId = `night-charge-details-${night}`;
+    const toggle = document.createElement("button");
+    toggle.type = "button";
+    toggle.className = "plan-toggle";
+    toggle.textContent = nightFormat.format(Date.UTC(year, month - 1, day));
+    toggle.setAttribute("aria-expanded", "false");
+    toggle.setAttribute("aria-controls", detailsId);
+    const nightCell = document.createElement("td");
+    nightCell.append(toggle);
 
     const decision = makeCell(charging ? `Charge to ${plan.targetSoc}%` : "No charge");
     if (plan.warnings?.length) {
@@ -551,47 +593,83 @@ function renderNightChargeRows(nights, emptyMessage) {
       warning.title = plan.warnings.join("\n");
       decision.append(warning);
     }
+    if (charging) {
+      const cost = document.createElement("span");
+      cost.className = "plan-note";
+      cost.textContent = `${formatAmount(plan.gridCharge_kWh, " kWh")} · ${formatCurrency(plan.estimatedChargeCost_AUD)}`;
+      decision.append(cost);
+    }
+
     const result = document.createElement("td");
     const badge = document.createElement("span");
     badge.className = `badge ${badgeClass}`;
     badge.textContent = label;
     result.append(badge);
 
-    const soFar = actual.soFar;
-    const soFarTime = soFar ? formatDate(soFar.asOf, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) : null;
+    const solarCell = actual.complete || !soFar
+      ? makeActualCell(formatAmount(actual.pv_kWh, " kWh"), trends.solar)
+      : makeActualCell(formatAmount(soFar.pv_kWh, " kWh"), trends.solarSoFar, `to ${soFarTime}`);
 
-    const row = document.createElement("tr");
-    row.append(
-      makeCell(nightFormat.format(Date.UTC(year, month - 1, day))),
+    const summary = document.createElement("tr");
+    summary.className = "plan-summary";
+    summary.append(
+      nightCell,
       decision,
-      makeCell(charging ? `${formatAmount(plan.gridCharge_kWh, " kWh")} · ${formatCurrency(plan.estimatedChargeCost_AUD)}` : "—"),
-      makeComparisonCell([
+      solarCell,
+      makeActualCell(formatAmount(actual.load_kWh, " kWh"), trends.load),
+      makeActualCell(formatAmount(actual.minSoc, "%"), trends.lowest, actual.minSoc == null ? null : soFarNote),
+      makeActualCell(formatAmount(actual.maxSoc, "%"), trends.peak, actual.maxSoc == null ? null : soFarNote),
+      result,
+    );
+
+    const list = document.createElement("dl");
+    list.className = "plan-details-list";
+    list.append(
+      ...makeDetailLine("Solar 06–24", [
         ["Forecast", formatAmount(expected.pvAfterWindow_kWh, " kWh")],
-        ["Actual", formatAmount(actual.pv_kWh, " kWh"), actualTrend(actual.pv_kWh, expected.pvAfterWindow_kWh, true)],
+        ["Actual", formatAmount(actual.pv_kWh, " kWh"), trends.solar],
         ...(soFar ? [
-          [`Forecast to ${soFarTime}`, formatAmount(soFar.pvForecast_kWh, " kWh")],
-          [`Actual to ${soFarTime}`, formatAmount(soFar.pv_kWh, " kWh"), actualTrend(soFar.pv_kWh, soFar.pvForecast_kWh, true)],
+          [`To ${soFarTime} forecast`, formatAmount(soFar.pvForecast_kWh, " kWh")],
+          [`To ${soFarTime} actual`, formatAmount(soFar.pv_kWh, " kWh"), trends.solarSoFar],
         ] : []),
       ]),
-      makeComparisonCell([
+      ...makeDetailLine("Load", [
         ["06–24 forecast", formatAmount(expected.loadAfterWindow_kWh, " kWh")],
-        ["06–24 actual", formatAmount(actual.load_kWh, " kWh"), actualTrend(actual.load_kWh, expected.loadAfterWindow_kWh, false)],
+        ["06–24 actual", formatAmount(actual.load_kWh, " kWh"), trends.load],
         ["Full day forecast", formatAmount(plan.dailyLoad_kWh?.expected, " kWh")],
-        ["Full day actual", formatAmount(actual.loadDay_kWh, " kWh"), actualTrend(actual.loadDay_kWh, plan.dailyLoad_kWh?.expected, false)],
+        ["Full day actual", formatAmount(actual.loadDay_kWh, " kWh"), trends.loadDay],
       ]),
-      makeComparisonCell([
-        ["Forecast · expected", formatAmount(expected.minSocWithoutCharge, "%")],
-        ["Forecast · worst case", formatAmount(worst.minSocWithoutCharge, "%")],
-        ["Actual", formatAmount(actual.minSoc, "%"), lowestSocTrend(actual.minSoc, expected.minSocWithoutCharge, worst.minSocWithoutCharge)],
+      ...makeDetailLine("Lowest SOC 06–24", [
+        ["Expected", formatAmount(expected.minSocWithoutCharge, "%")],
+        ["Worst case", formatAmount(worst.minSocWithoutCharge, "%")],
+        ["Actual", formatAmount(actual.minSoc, "%"), trends.lowest],
       ]),
-      makeComparisonCell([
-        ["Forecast · expected", formatAmount(expected.peakSocWithoutCharge, "%")],
-        ["Forecast · worst case", formatAmount(worst.peakSocWithoutCharge, "%")],
-        ["Actual", formatAmount(actual.maxSoc, "%"), actualTrend(actual.maxSoc, expected.peakSocWithoutCharge, true)],
+      ...makeDetailLine("Peak SOC 06–24", [
+        ["Expected", formatAmount(expected.peakSocWithoutCharge, "%")],
+        ["Worst case", formatAmount(worst.peakSocWithoutCharge, "%")],
+        ["Actual", formatAmount(actual.maxSoc, "%"), trends.peak],
       ]),
-      result,
     );
-    body.append(row);
+    const detailsCell = document.createElement("td");
+    detailsCell.colSpan = NIGHT_CHARGE_COLUMNS;
+    detailsCell.append(list);
+    const details = document.createElement("tr");
+    details.className = "plan-details";
+    details.id = detailsId;
+    details.hidden = true;
+    details.append(detailsCell);
+
+    toggle.addEventListener("click", () => {
+      const open = toggle.getAttribute("aria-expanded") !== "true";
+      toggle.setAttribute("aria-expanded", String(open));
+      summary.classList.toggle("is-open", open);
+      details.hidden = !open;
+    });
+    summary.addEventListener("click", (event) => {
+      if (!event.target.closest("button")) toggle.click();
+    });
+
+    body.append(summary, details);
   }
 }
 
diff --git a/site/index.html b/site/index.html
index b1b475d..b664be0 100644
--- a/site/index.html
+++ b/site/index.html
@@ -26,9 +26,9 @@
     </script>
     <link rel="icon" type="image/svg+xml" href="favicon.svg">
     <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
-    <link rel="stylesheet" href="styles.css">
+    <link rel="stylesheet" href="styles.css?v=16">
     <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js" defer></script>
-    <script src="app.js?v=15" defer></script>
+    <script src="app.js?v=16" defer></script>
   </head>
   <body>
     <main class="page">
@@ -212,7 +212,7 @@
           <div>
             <p class="eyebrow">NIGHT CHARGE PLANNER · DRY RUN</p>
             <h3 id="night-charge-title">Grid charging decisions</h3>
-            <p class="group-description">Last 5 nights · each night's plan compared with what happened, measured 06:00–24:00 unless marked full day (no charging is performed yet)</p>
+            <p class="group-description">Last 5 nights · actual values measured 06:00–24:00, icons compare them with the plan's forecast · select a night for the forecasts (no charging is performed yet)</p>
           </div>
         </header>
         <article class="chart-card">
@@ -222,16 +222,15 @@
                 <tr>
                   <th scope="col">Night</th>
                   <th scope="col">Decision</th>
-                  <th scope="col">Grid charge</th>
                   <th scope="col">Solar 06–24</th>
-                  <th scope="col">Load</th>
+                  <th scope="col">Load 06–24</th>
                   <th scope="col">Lowest SOC 06–24</th>
                   <th scope="col">Peak SOC 06–24</th>
                   <th scope="col">Result</th>
                 </tr>
               </thead>
               <tbody id="night-charge-rows">
-                <tr><td colspan="8" class="plan-empty">Loading…</td></tr>
+                <tr><td colspan="7" class="plan-empty">Loading…</td></tr>
               </tbody>
             </table>
           </div>
diff --git a/site/styles.css b/site/styles.css
index d4454fb..1456e36 100644
--- a/site/styles.css
+++ b/site/styles.css
@@ -268,10 +268,20 @@ h4 { margin: 0 0 4px; font-size: 14px; letter-spacing: -.02em; }
 .plan-table th { color: var(--muted); font-size: 10px; font-weight: 600; letter-spacing: .04em; }
 .plan-table tbody tr:last-child td { border-bottom: 0; }
 .plan-table .plan-empty { color: var(--muted); text-align: center; }
-.plan-table .plan-comparison { min-width: 150px; white-space: normal; }
-.plan-comparison-row { display: flex; justify-content: space-between; gap: 12px; line-height: 1.6; }
-.plan-comparison-label { color: var(--muted); }
-.plan-comparison-value { font-variant-numeric: tabular-nums; font-weight: 600; text-align: right; }
+.plan-table tr.plan-summary { cursor: pointer; }
+.plan-table tr.plan-summary:hover td { background: var(--input-surface); }
+.plan-table tr.plan-summary.is-open td { border-bottom: 0; }
+.plan-toggle { display: inline-flex; align-items: center; gap: 6px; padding: 0; border: 0; background: none; color: inherit; font: inherit; font-weight: 600; cursor: pointer; }
+.plan-toggle::before { content: "▸"; width: 10px; color: var(--muted); font-size: 11px; }
+.plan-toggle[aria-expanded="true"]::before { content: "▾"; }
+.plan-actual { font-variant-numeric: tabular-nums; font-weight: 600; }
+.plan-note { display: block; color: var(--muted); font-size: 10px; font-weight: 400; }
+.plan-table .plan-details td { padding-top: 0; white-space: normal; }
+.plan-details-list { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 0; padding: 12px 14px; border-radius: 12px; background: var(--input-surface); }
+.plan-details-list dt { color: var(--muted); font-weight: 600; }
+.plan-details-list dd { margin: 0; font-variant-numeric: tabular-nums; }
+.plan-detail-name { color: var(--muted); }
+.plan-detail-part { white-space: nowrap; }
 .plan-warning { margin-left: 6px; color: var(--series-export); cursor: help; }
 .plan-trend { margin-right: 5px; font-size: 10px; cursor: help; }
 .plan-trend-great { color: var(--series-solar); font-size: 12px; font-weight: 700; }
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