const HISTORY_URL = "data/history.json";
const NIGHT_CHARGE_URL = "data/night_charge.json";
const EV_CHARGE_URL = "data/ev_charge.json";
const DAY_MS = 24 * 60 * 60 * 1000;
let dashboardTimezone = "Australia/Sydney";

const FIELDS = {
  pv: "photovoltaicPowerGenerationToday_kWh",
  consumption: "totalConsumptionToday_kWh",
  bought: "buyElectricityToday_kWh",
  sold: "sellingElectricityToday_kWh",
  batteryCharge: "dailyBattCharge_kWh",
  batteryDischarge: "dailyBattDischarge_kWh",
  soc: "batterySoc_percent",
  netCost: "dailyNetCost_AUD",
};

const COLORS = {
  solar: "--series-solar",
  solarFill: "--series-solar-fill",
  consumption: "--series-consumption",
  consumptionFill: "--series-consumption-fill",
  export: "--series-export",
  exportFill: "--series-export-fill",
  import: "--series-import",
  importFill: "--series-import-fill",
  batteryCharge: "--series-battery-charge",
  batteryChargeFill: "--series-battery-charge-fill",
  batteryDischarge: "--series-battery-discharge",
  batteryDischargeFill: "--series-battery-discharge-fill",
  soc: "--series-soc",
  socFill: "--series-soc-fill",
  cost: "--series-cost",
  costFill: "--series-cost-fill",
};

let refreshChartsForTheme = () => {};

const numberOrNull = (value) => {
  const number = Number(value);
  return value !== null && value !== "" && Number.isFinite(number) ? number : null;
};

const localDay = (timestamp) => dateInputValue(new Date(timestamp));

const dateInputValue = (date) => {
  const parts = new Intl.DateTimeFormat("en-AU", {
    timeZone: dashboardTimezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${values.year}-${values.month}-${values.day}`;
};

const offsetDate = (dateValue, days) => {
  const [year, month, day] = dateValue.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`;
};

function billingCycleRange(today, startDay) {
  const [year, month] = today.split("-").map(Number);
  const monthStart = (offset) => {
    const first = new Date(Date.UTC(year, month - 1 + offset, 1));
    const lastDay = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
    const day = Math.min(startDay, lastDay);
    return `${first.getUTCFullYear()}-${String(first.getUTCMonth() + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  };
  const previousMonth = today < monthStart(0);
  return {
    start: monthStart(previousMonth ? -1 : 0),
    end: offsetDate(monthStart(previousMonth ? 0 : 1), -1),
  };
}

function billingCycleCost(latestByDay, today, startDay) {
  const { start, end } = billingCycleRange(today, startDay);
  let total = 0;
  let through = null;
  for (let day = start; day <= today && day <= end; day = offsetDate(day, 1)) {
    const cost = numberOrNull(latestByDay.get(day)?.[FIELDS.netCost]);
    if (cost === null) break;
    total += cost;
    through = day;
  }
  return { start, end, through, total: through === null ? null : total };
}

const formatDate = (timestamp, options) =>
  new Intl.DateTimeFormat("en-AU", { ...options, timeZone: dashboardTimezone }).format(new Date(timestamp));

const formatBillingDay = (day, includeYear = false) =>
  new Intl.DateTimeFormat("en-AU", {
    day: "numeric", month: "short", year: includeYear ? "numeric" : undefined, timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));

const formatCurrency = (value) =>
  new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(value);

const themeColor = (property) =>
  getComputedStyle(document.documentElement).getPropertyValue(property).trim();

function updateThemeControls() {
  const dark = document.documentElement.dataset.theme === "dark";
  const mode = document.documentElement.dataset.themeMode ?? "auto";
  document.getElementById("theme-icon").textContent = dark ? "☀" : "☾";
  document.getElementById("theme-label").textContent =
    mode === "auto" ? "Auto" : mode === "light" ? "Light" : "Dark";
  document.getElementById("theme-toggle").setAttribute(
    "aria-label",
    `Theme mode: ${mode === "auto" ? "Auto" : mode === "light" ? "Light" : "Dark"}`,
  );
  document.querySelector('meta[name="theme-color"]').content = dark ? "#10191d" : "#edf4f2";
}

function initializeThemeToggle() {
  const button = document.getElementById("theme-toggle");
  const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
  updateThemeControls();
  themeMedia.addEventListener("change", (event) => {
    if (document.documentElement.dataset.themeMode !== "auto") return;
    document.documentElement.dataset.theme = event.matches ? "dark" : "light";
    updateThemeControls();
    refreshChartsForTheme();
  });
  button.addEventListener("click", () => {
    const currentMode = document.documentElement.dataset.themeMode ?? "auto";
    const nextMode = currentMode === "auto" ? "light" : currentMode === "light" ? "dark" : "auto";
    document.documentElement.dataset.themeMode = nextMode;
    document.documentElement.dataset.theme = nextMode === "auto"
      ? (themeMedia.matches ? "dark" : "light")
      : nextMode;
    updateThemeControls();
    try {
      if (nextMode === "auto") {
        localStorage.removeItem("esy-theme");
      } else {
        localStorage.setItem("esy-theme", nextMode);
      }
    } catch (error) {
      console.warn("Could not save the theme preference.", error);
    }
    refreshChartsForTheme();
  });
}

function setMetric(id, value, suffix = "") {
  const element = document.getElementById(id);
  element.textContent = value === null ? "—" : `${value.toLocaleString("en-AU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })}${suffix}`;
}

function setCurrencyMetric(id, value) {
  const element = document.getElementById(id);
  element.textContent = value === null ? "—" : formatCurrency(value);
}

function localDayStartTimestamp(dateValue) {
  const [year, month, day] = dateValue.split("-").map(Number);
  const desired = Date.UTC(year, month - 1, day);
  let timestamp = desired;
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: dashboardTimezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const parts = Object.fromEntries(
      formatter.formatToParts(new Date(timestamp)).map(({ type, value }) => [type, value]),
    );
    const represented = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour),
      Number(parts.minute),
      Number(parts.second),
    );
    timestamp += desired - represented;
  }
  return timestamp;
}

function makeChartOptions(unit, { percent = false, currency = false, startDate, endDate } = {}) {
  const textColor = themeColor("--chart-text");
  const selectedRangeMs = percent && startDate && endDate
    ? localDayStartTimestamp(offsetDate(endDate, 1)) - localDayStartTimestamp(startDate)
    : 0;
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: "index" },
    plugins: {
      legend: {
        position: "top",
        align: "end",
        labels: { usePointStyle: true, pointStyle: "circle", boxWidth: 7, boxHeight: 7, padding: 16, color: textColor, font: { family: "DM Sans", size: 10 } },
      },
      tooltip: {
        backgroundColor: themeColor("--chart-tooltip"),
        titleColor: themeColor("--chart-tooltip-text"),
        bodyColor: themeColor("--chart-tooltip-text"),
        padding: 11,
        titleFont: { family: "DM Sans", size: 11, weight: "600" },
        bodyFont: { family: "DM Sans", size: 11 },
        callbacks: {
          title(items) {
            const x = percent ? items[0]?.parsed.x : items[0]?.label;
            if (x === undefined || x === null || x === "") return "";
            const date = new Date(x);
            return Number.isNaN(date.getTime())
              ? String(x)
              : formatDate(date, { dateStyle: "medium", timeStyle: percent ? "short" : undefined });
          },
          label(context) {
            const value = context.parsed.y;
            return `${context.dataset.label}: ${value === null ? "—" : currency ? formatCurrency(value) : `${value} ${unit}`}`;
          },
        },
      },
    },
    scales: {
      x: {
        ...(percent ? {
          type: "linear",
          min: startDate ? localDayStartTimestamp(startDate) : undefined,
          max: endDate ? localDayStartTimestamp(offsetDate(endDate, 1)) : undefined,
        } : {}),
        grid: { display: false },
        border: { display: false },
        ticks: {
          color: textColor,
          maxTicksLimit: percent ? 5 : 10,
          stepSize: percent && selectedRangeMs <= 3 * DAY_MS ? DAY_MS / 2 : undefined,
          autoSkip: !(percent && selectedRangeMs <= 3 * DAY_MS),
          maxRotation: 0,
          font: { family: "DM Sans", size: 9 },
          callback(value) {
            const date = new Date(percent ? Number(value) : this.getLabelForValue(value));
            if (Number.isNaN(date.getTime())) return String(value);
            if (percent) {
              return [
                formatDate(date, { day: "2-digit", month: "2-digit" }),
                formatDate(date, { hour: "2-digit", minute: "2-digit" }),
              ];
            }
            return formatDate(date, { month: "short", day: "numeric" });
          },
        },
      },
      y: {
        beginAtZero: !percent,
        min: percent ? 0 : undefined,
        max: percent ? 100 : undefined,
        grid: { color: themeColor("--chart-grid") },
        border: { display: false, dash: [3, 4] },
        ticks: {
          color: textColor,
          maxTicksLimit: 5,
          font: { family: "DM Sans", size: 9 },
          callback: (value) => currency ? formatCurrency(value) : `${value}${percent ? "%" : ""}`,
        },
      },
    },
  };
}

function makeDataset(label, values, color, fillColor) {
  return {
    label,
    data: values,
    borderColor: color,
    backgroundColor: fillColor,
    borderWidth: 2,
    pointRadius: 0,
    pointHoverRadius: 4,
    tension: 0,
    fill: false,
    spanGaps: true,
  };
}

function showNotice(message) {
  const notice = document.getElementById("notice");
  notice.textContent = message;
  notice.hidden = false;
}

function renderDashboard(records, generatedAt, timeZone, costWarnings = [], billingCycleStartDay = null) {
  dashboardTimezone = timeZone;
  new Intl.DateTimeFormat("en-AU", { timeZone: dashboardTimezone });
  const now = Date.now();
  const cutoff = now - 90 * DAY_MS;
  const recent = records
    .filter((record) => {
      const timestamp = Date.parse(record.timestamp ?? record.mqttCurrentTime);
      return Number.isFinite(timestamp) && timestamp >= cutoff && timestamp <= now;
    })
    .sort((a, b) => Date.parse(a.timestamp ?? a.mqttCurrentTime) - Date.parse(b.timestamp ?? b.mqttCurrentTime));

  if (recent.length === 0) {
    showNotice("No snapshots are available for the last 90 days yet. The dashboard will update when matching history is available.");
    document.getElementById("last-updated").textContent = "No data available";
    document.getElementById("snapshot-count").textContent = "0 snapshots in the last 90 days";
    return;
  }

  const latest = recent[recent.length - 1];
  const latestTimestamp = latest.timestamp ?? latest.mqttCurrentTime;
  const latestDay = latest.tariffLocalDate ?? localDay(latestTimestamp);
  document.getElementById("metric-daily-label").textContent = latestDay === dateInputValue(new Date(now))
    ? "Today" : formatBillingDay(latestDay);
  setMetric("metric-pv", numberOrNull(latest[FIELDS.pv]), " kWh");
  setMetric("metric-consumption", numberOrNull(latest[FIELDS.consumption]), " kWh");
  setMetric("metric-bought", numberOrNull(latest[FIELDS.bought]), " kWh");
  setMetric("metric-sold", numberOrNull(latest[FIELDS.sold]), " kWh");
  setMetric("metric-battery-charge", numberOrNull(latest[FIELDS.batteryCharge]), " kWh");
  setMetric("metric-battery-discharge", numberOrNull(latest[FIELDS.batteryDischarge]), " kWh");
  setMetric("metric-soc", numberOrNull(latest[FIELDS.soc]), "%");
  setCurrencyMetric("metric-daily-cost", numberOrNull(latest[FIELDS.netCost]));
  document.getElementById("last-updated").textContent =
    `Updated ${formatDate(latestTimestamp, { dateStyle: "medium", timeStyle: "short" })}`;
  document.getElementById("snapshot-count").textContent =
    `${recent.length.toLocaleString("en-AU")} snapshots · generated ${formatDate(generatedAt, { dateStyle: "medium", timeStyle: "short" })}`;

  const latestByDay = new Map();
  for (const record of recent) {
    latestByDay.set(record.tariffLocalDate ?? localDay(record.timestamp ?? record.mqttCurrentTime), record);
  }
  const dailyRecords = [...latestByDay.values()];
  if (costWarnings.length > 0) {
    const warningDates = costWarnings.map((warning) => warning.date).join(", ");
    showNotice(`Some daily cost estimates may be incomplete due to missing or reset meter readings (${warningDates}).`);
  }
  const today = dateInputValue(new Date(now));
  if (Number.isInteger(billingCycleStartDay) && billingCycleStartDay >= 1 && billingCycleStartDay <= 31) {
    const cycle = billingCycleCost(latestByDay, today, billingCycleStartDay);
    setCurrencyMetric("metric-cycle-cost", cycle.total);
    const range = `${formatBillingDay(cycle.start)}–${formatBillingDay(cycle.end, true)}`;
    document.getElementById("metric-cycle-period").textContent = cycle.through
      ? `${range} · through ${formatBillingDay(cycle.through)}`
      : `${range} · no readings from cycle start`;
  } else {
    document.getElementById("metric-cycle-period").textContent = "Billing cycle not configured";
  }
  const earliest = offsetDate(today, -90);
  const defaultStart = offsetDate(today, -6);
  const dateInputs = {
    energyFrom: document.getElementById("energy-from"),
    energyTo: document.getElementById("energy-to"),
    socFrom: document.getElementById("soc-from"),
    socTo: document.getElementById("soc-to"),
    costFrom: document.getElementById("cost-from"),
    costTo: document.getElementById("cost-to"),
  };

  for (const input of Object.values(dateInputs)) {
    input.min = earliest;
    input.max = today;
    input.required = true;
  }
  dateInputs.energyFrom.value = defaultStart;
  dateInputs.energyTo.value = today;
  dateInputs.socFrom.value = defaultStart;
  dateInputs.socTo.value = today;
  dateInputs.costFrom.value = defaultStart;
  dateInputs.costTo.value = today;

  const energyChart = new Chart(document.getElementById("energy-chart"), {
    type: "line",
    data: { labels: [], datasets: [] },
    options: makeChartOptions("kWh"),
  });

  const socChart = new Chart(document.getElementById("soc-chart"), {
    type: "line",
    data: { labels: [], datasets: [] },
    options: makeChartOptions("%", { percent: true }),
  });

  const costChart = new Chart(document.getElementById("cost-chart"), {
    type: "line",
    data: { labels: [], datasets: [] },
    options: makeChartOptions("AUD", { currency: true }),
  });

  const updateEnergyChart = () => {
    const inRange = (record, start, end) => {
      const day = localDay(record.timestamp ?? record.mqttCurrentTime);
      return day >= start && day <= end;
    };
    const selectedDays = dailyRecords.filter((record) =>
      inRange(record, dateInputs.energyFrom.value, dateInputs.energyTo.value));
    const labels = selectedDays.map((record) => record.timestamp ?? record.mqttCurrentTime);

    energyChart.data.labels = labels;
    energyChart.data.datasets = [
      makeDataset("Solar generation", selectedDays.map((record) => numberOrNull(record[FIELDS.pv])), themeColor(COLORS.solar), themeColor(COLORS.solarFill)),
      makeDataset("Consumption", selectedDays.map((record) => numberOrNull(record[FIELDS.consumption])), themeColor(COLORS.consumption), themeColor(COLORS.consumptionFill)),
      makeDataset("Grid export", selectedDays.map((record) => numberOrNull(record[FIELDS.sold])), themeColor(COLORS.export), themeColor(COLORS.exportFill)),
      makeDataset("Grid import", selectedDays.map((record) => numberOrNull(record[FIELDS.bought])), themeColor(COLORS.import), themeColor(COLORS.importFill)),
      makeDataset("Battery charge", selectedDays.map((record) => numberOrNull(record[FIELDS.batteryCharge])), themeColor(COLORS.batteryCharge), themeColor(COLORS.batteryChargeFill)),
      makeDataset("Battery discharge", selectedDays.map((record) => numberOrNull(record[FIELDS.batteryDischarge])), themeColor(COLORS.batteryDischarge), themeColor(COLORS.batteryDischargeFill)),
    ];
    energyChart.update();
  };

  const updateSocChart = () => {
    const selectedSnapshots = recent.filter((record) => {
      const day = localDay(record.timestamp ?? record.mqttCurrentTime);
      return day >= dateInputs.socFrom.value && day <= dateInputs.socTo.value;
    });
    const firstSnapshotDay = selectedSnapshots.length
      ? localDay(selectedSnapshots[0].timestamp ?? selectedSnapshots[0].mqttCurrentTime)
      : undefined;
    const lastSnapshotDay = selectedSnapshots.length
      ? localDay(selectedSnapshots[selectedSnapshots.length - 1].timestamp
        ?? selectedSnapshots[selectedSnapshots.length - 1].mqttCurrentTime)
      : undefined;
    socChart.data.datasets = [
      {
        ...makeDataset(
          "Battery charge",
          selectedSnapshots.map((record) => ({
            x: Date.parse(record.timestamp ?? record.mqttCurrentTime),
            y: numberOrNull(record[FIELDS.soc]),
          })),
          themeColor(COLORS.soc),
          themeColor(COLORS.socFill),
        ),
        tension: 0.28,
        fill: true,
      },
    ];
    socChart.options = makeChartOptions("%", {
      percent: true,
      startDate: firstSnapshotDay,
      endDate: lastSnapshotDay,
    });
    socChart.update();
  };

  const updateCostChart = () => {
    const selectedDays = dailyRecords.filter((record) => {
      const day = record.tariffLocalDate ?? localDay(record.timestamp ?? record.mqttCurrentTime);
      return day >= dateInputs.costFrom.value && day <= dateInputs.costTo.value;
    });
    costChart.data.labels = selectedDays.map((record) => record.timestamp ?? record.mqttCurrentTime);
    costChart.data.datasets = [
      {
        ...makeDataset(
          "Estimated net cost",
          selectedDays.map((record) => numberOrNull(record[FIELDS.netCost])),
          themeColor(COLORS.cost),
          themeColor(COLORS.costFill),
        ),
        fill: true,
        spanGaps: false,
      },
    ];
    costChart.update();
  };

  const bindDateRange = (startInput, endInput, updateCharts) => {
    const update = () => {
      const invalidRange = startInput.value > endInput.value;
      endInput.setCustomValidity(invalidRange ? "End date must be on or after start date." : "");
      if (invalidRange) {
        endInput.reportValidity();
        return;
      }
      updateCharts();
    };
    startInput.addEventListener("change", update);
    endInput.addEventListener("change", update);
  };

  bindDateRange(dateInputs.energyFrom, dateInputs.energyTo, updateEnergyChart);
  bindDateRange(dateInputs.socFrom, dateInputs.socTo, updateSocChart);
  bindDateRange(dateInputs.costFrom, dateInputs.costTo, updateCostChart);
  updateEnergyChart();
  updateSocChart();
  updateCostChart();
  refreshChartsForTheme = () => {
    energyChart.options = makeChartOptions("kWh");
    updateEnergyChart();
    updateSocChart();
    costChart.options = makeChartOptions("AUD", { currency: true });
    updateCostChart();
  };
}

function makeCell(text, className) {
  const cell = document.createElement("td");
  cell.textContent = text;
  if (className) cell.className = className;
  return cell;
}

const NIGHT_CHARGE_COLUMNS = 7;

function makeTrendIcon(trend) {
  const icon = document.createElement("span");
  icon.className = `plan-trend plan-trend-${trend.tone}`;
  icon.textContent = trend.symbol;
  icon.title = trend.title;
  icon.setAttribute("aria-label", trend.title);
  return icon;
}

function makeActualCell(value, trend, note) {
  const cell = document.createElement("td");
  cell.className = "plan-actual";
  if (trend) cell.append(makeTrendIcon(trend));
  cell.append(value);
  if (note) {
    const noteText = document.createElement("span");
    noteText.className = "plan-note";
    noteText.textContent = note;
    cell.append(noteText);
  }
  return cell;
}

function makeDetailsTable(rows, headings = ["", "Forecast", "Worst case", "Actual"]) {
  const table = document.createElement("table");
  table.className = "plan-details-table";
  const headRow = document.createElement("tr");
  for (const heading of headings) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = heading;
    headRow.append(cell);
  }
  const head = document.createElement("thead");
  head.append(headRow);
  const body = document.createElement("tbody");
  body.append(...rows);
  table.append(head, body);
  return table;
}

// ★ at or better than the forecast, ✓ between the forecast and worst case, ✗ at or worse than the worst case.
function rangeTrend(actual, forecast, worst, higherIsGood = true) {
  const values = [actual, forecast, worst].map(numberOrNull);
  if (values.includes(null)) return null;
  const [actualValue, forecastValue, worstValue] = higherIsGood ? values : values.map((value) => -value);
  if (actualValue >= forecastValue) return { symbol: "★", tone: "great", title: "At or better than the forecast" };
  if (actualValue > worstValue) return { symbol: "✓", tone: "good", title: "Between the forecast and the worst case" };
  return { symbol: "✗", tone: "bad", title: "At or worse than the worst case" };
}

const PROJECTED_TITLE = "Projected: load so far plus the rest of today's forecast";
const PROJECTED_SOLAR_TITLE = "Projected: solar generated so far plus the rest of today's forecast";
const TRIGGER_LABELS = { scheduled: "Scheduled", manual: "Manual", replay: "Replay" };

const formatPlanTime = (timestamp) =>
  formatDate(timestamp, { weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

const formatPlanDateTime = (timestamp) => {
  const parts = new Intl.DateTimeFormat("en-AU", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: dashboardTimezone,
  }).formatToParts(new Date(timestamp));
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${values.day} ${values.month} ${values.hour}:${values.minute}`;
};

function describeTrigger(trigger, replayedAt) {
  const label = TRIGGER_LABELS[trigger] ?? "Scheduled";
  return trigger === "replay" && replayedAt ? `${label} (run ${formatPlanTime(replayedAt)})` : label;
}

function makeHistoryTable(history, windowEnd) {
  const endTime = formatDate(windowEnd, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const rows = history.map((run) => {
    const row = document.createElement("tr");
    const time = run.count > 1
      ? `${formatPlanTime(run.from)} – ${formatPlanTime(run.to)} (${run.count} runs)`
      : formatPlanTime(run.from);
    const charging = run.decision === "charge";
    row.append(
      makeCell(time),
      makeCell(charging ? `Aim for ${run.targetSoc}% by ${endTime}` : "No grid top-up needed"),
      makeCell(charging ? formatAmount(run.gridCharge_kWh, " kWh") : "—"),
      makeCell(describeTrigger(run.trigger, run.replayedAt)),
    );
    return row;
  });
  const table = makeDetailsTable(rows, ["Plan time", "Decision", "Grid charge", "How"]);
  table.classList.add("plan-history-table");
  const caption = document.createElement("caption");
  caption.textContent = "Decision history";
  table.prepend(caption);
  return table;
}

function makeRangeLine(label, forecast, worst, actual, suffix, trend, projected = false) {
  const row = document.createElement("tr");
  const name = document.createElement("th");
  name.scope = "row";
  name.textContent = label;
  const actualText = formatAmount(actual, suffix);
  const actualCell = makeCell(projected && actualText !== "—" ? `≈ ${actualText}` : actualText, "plan-details-actual");
  if (projected) actualCell.title = PROJECTED_TITLE;
  if (trend) actualCell.prepend(makeTrendIcon(trend));
  row.append(name, makeCell(formatAmount(forecast, suffix)), makeCell(formatAmount(worst, suffix)), actualCell);
  return row;
}

const formatAmount = (value, suffix = "") => {
  const number = numberOrNull(value);
  return number === null ? "—" : `${number.toLocaleString("en-AU", { maximumFractionDigits: 1 })}${suffix}`;
};

function nightChargeVerdict(verdict, target) {
  switch (verdict) {
    case "ok": return ["No charge – correct", "badge-good"];
    case "missed": return [`No charge – fell below ${target}%`, "badge-bad"];
    case "charge_needed": return ["Charge – correct", "badge-info"];
    case "charge_not_needed": return ["Planned charge – not needed", "badge-warn"];
    default: return ["Pending", "badge-neutral"];
  }
}

function explainNightChargeVerdict(verdict, plan, actual) {
  const target = plan.scenarios.expected.minSocTarget;
  const lowest = formatAmount(actual.minSoc, "%");
  const observation = actual.minSoc == null
    ? "No home-battery SOC reading has been recorded after 06:00 yet."
    : `Lowest measured home-battery SOC ${actual.complete ? "from 06:00 to midnight" : "so far since 06:00"}: ${lowest}.`;
  const threshold = `This night's saved expected-case target: ${target}%.`;
  switch (verdict) {
    case "ok":
      return `No overnight grid charge was recommended. ${observation} It stayed at or above the ${target}% target, so the no-charge advice matched the observed result.`;
    case "missed":
      return `No overnight grid charge was recommended. ${observation} It fell below the ${target}% target, so the no-charge advice missed the target.`;
    case "charge_needed":
      return `The dry-run recommended charging the home battery to ${plan.targetSoc}%. ${observation} It fell below the ${target}% target, so charging was recommended for a reason. This does not mean charging happened or prove it would have prevented the drop.`;
    case "charge_not_needed":
      return `The dry-run recommended charging the home battery to ${plan.targetSoc}%. ${observation} It stayed at or above the ${target}% target. This does not prove charging was unnecessary if you charged the battery yourself; the report does not verify whether the advice was followed.`;
    default:
      return actual.complete
        ? `The day is complete, but there is no usable home-battery SOC reading for a result. ${threshold}`
        : `The 06:00-to-midnight observation period is not complete yet. ${observation} The result will be checked against the ${target}% target once the day ends.`;
  }
}

function renderNightChargeRows(nights, emptyMessage) {
  const body = document.getElementById("night-charge-rows");
  body.replaceChildren();
  if (nights.length === 0) {
    const row = document.createElement("tr");
    const cell = makeCell(emptyMessage, "plan-empty");
    cell.colSpan = NIGHT_CHARGE_COLUMNS;
    row.append(cell);
    body.append(row);
    return;
  }

  const nightFormat = new Intl.DateTimeFormat("en-AU", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  for (const { night, plan, actual, verdict, trigger, history } of nights) {
    const [year, month, day] = night.split("-").map(Number);
    const dateParts = Object.fromEntries(nightFormat.formatToParts(Date.UTC(year, month - 1, day)).map(({ type, value }) => [type, value]));
    const expected = plan.scenarios?.expected ?? {};
    const worst = plan.scenarios?.worstCase ?? {};
    const charging = plan.decision === "charge";
    const [label, badgeClass] = nightChargeVerdict(verdict, expected.minSocTarget);
    const explanation = explainNightChargeVerdict(verdict, plan, actual);
    const soFar = actual.soFar;
    const soFarTime = soFar ? formatDate(soFar.asOf, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) : null;
    const soFarNote = actual.complete ? null : "so far";
    // Until the day ends, show where load is heading rather than a blank.
    const projecting = !actual.complete && numberOrNull(soFar?.loadProjected_kWh) !== null;
    const load06To24 = projecting ? soFar.loadProjected_kWh : actual.load_kWh;
    const loadFullDay = projecting ? soFar.loadDayProjected_kWh : actual.loadDay_kWh;
    const solarAvailable = !actual.complete && numberOrNull(soFar?.pvProjected_kWh) !== null;
    const solar06To24 = solarAvailable ? soFar.pvProjected_kWh : actual.pv_kWh;
    const projectingSolar = solarAvailable && soFar.pvRemainingForecast_kWh > 0;

    const trends = {
      solar: rangeTrend(solar06To24, expected.pvAfterWindow_kWh, worst.pvAfterWindow_kWh),
      solarSoFar: soFar ? rangeTrend(soFar.pv_kWh, soFar.pvForecast_kWh, soFar.pvWorstCase_kWh) : null,
      load: rangeTrend(load06To24, expected.loadAfterWindow_kWh, worst.loadAfterWindow_kWh, false),
      loadSoFar: soFar ? rangeTrend(soFar.load_kWh, soFar.loadForecast_kWh, soFar.loadWorstCase_kWh, false) : null,
      loadDay: rangeTrend(loadFullDay, plan.dailyLoad_kWh?.expected, plan.dailyLoad_kWh?.worstCase, false),
      lowest: rangeTrend(actual.minSoc, expected.minSocWithoutCharge, worst.minSocWithoutCharge),
      peak: rangeTrend(actual.maxSoc, expected.peakSocWithoutCharge, worst.peakSocWithoutCharge),
    };

    const detailsId = `night-charge-details-${night}`;
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "plan-toggle";
    const windowTime = (timestamp) => formatDate(timestamp, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    toggle.textContent = `${dateParts.day} ${dateParts.month} ${dateParts.year}`;
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", detailsId);
    const nightCell = document.createElement("td");
    nightCell.append(toggle);

    const decision = makeCell(charging ? `Aim for ${plan.targetSoc}% by ${windowTime(plan.window.end)}` : "No grid top-up needed");
    if (plan.warnings?.length) {
      const warning = document.createElement("span");
      warning.className = "plan-warning";
      warning.textContent = "⚠";
      warning.title = plan.warnings.join("\n");
      decision.append(warning);
    }
    if (charging) {
      const cost = document.createElement("span");
      cost.className = "plan-note";
      cost.textContent = `${formatAmount(plan.gridCharge_kWh, " kWh")} · ${formatCurrency(plan.estimatedChargeCost_AUD)}`;
      decision.append(cost);
    }
    const madeAt = document.createElement("span");
    madeAt.className = "plan-note";
    madeAt.textContent = `${TRIGGER_LABELS[trigger] ?? "Scheduled"} · ${formatPlanDateTime(plan.generatedAt)}`;
    if (trigger === "replay") {
      const replayedAt = plan.replayedAt ?? plan.forecastFetchedAt;
      madeAt.title = `Recomputed${replayedAt ? ` ${formatPlanTime(replayedAt)}` : ""} from the data at the original plan time`;
    }
    decision.append(madeAt);

    const result = document.createElement("td");
    result.title = explanation;
    const badge = document.createElement("span");
    badge.className = `badge ${badgeClass}`;
    badge.textContent = label;
    badge.tabIndex = 0;
    badge.title = explanation;
    badge.setAttribute("aria-label", `${label}. ${explanation}`);
    result.append(badge);

    const solarCell = solarAvailable
      ? makeActualCell(`${projectingSolar ? "≈ " : ""}${formatAmount(solar06To24, " kWh")}`, trends.solar, projectingSolar ? "projected" : `to ${soFarTime}`)
      : makeActualCell(formatAmount(actual.pv_kWh, " kWh"), trends.solar);
    if (projectingSolar) solarCell.title = PROJECTED_SOLAR_TITLE;

    const loadCell = projecting
      ? makeActualCell(`≈ ${formatAmount(load06To24, " kWh")}`, trends.load, "projected")
      : makeActualCell(formatAmount(actual.load_kWh, " kWh"), trends.load);
    if (projecting) loadCell.title = PROJECTED_TITLE;

    const summary = document.createElement("tr");
    summary.className = "plan-summary";
    summary.append(
      nightCell,
      decision,
      solarCell,
      loadCell,
      makeActualCell(formatAmount(actual.minSoc, "%"), trends.lowest, actual.minSoc == null ? null : soFarNote),
      makeActualCell(formatAmount(actual.maxSoc, "%"), trends.peak, actual.maxSoc == null ? null : soFarNote),
      result,
    );

    const list = makeDetailsTable([
      makeRangeLine("Solar 06–24", expected.pvAfterWindow_kWh, worst.pvAfterWindow_kWh, solar06To24, " kWh", trends.solar, projectingSolar),
      ...(soFar
        ? [makeRangeLine(`Solar 06–${soFarTime}`, soFar.pvForecast_kWh, soFar.pvWorstCase_kWh, soFar.pv_kWh, " kWh", trends.solarSoFar)]
        : []),
      makeRangeLine("Load 06–24", expected.loadAfterWindow_kWh, worst.loadAfterWindow_kWh, load06To24, " kWh", trends.load, projecting),
      ...(numberOrNull(soFar?.loadForecast_kWh) !== null
        ? [makeRangeLine(`Load 06–${soFarTime}`, soFar.loadForecast_kWh, soFar.loadWorstCase_kWh, soFar.load_kWh, " kWh", trends.loadSoFar)]
        : []),
      makeRangeLine("Load full day", plan.dailyLoad_kWh?.expected, plan.dailyLoad_kWh?.worstCase, loadFullDay, " kWh", trends.loadDay, projecting),
      makeRangeLine("Lowest SOC 06–24", expected.minSocWithoutCharge, worst.minSocWithoutCharge, actual.minSoc, "%", trends.lowest),
      makeRangeLine("Peak SOC 06–24", expected.peakSocWithoutCharge, worst.peakSocWithoutCharge, actual.maxSoc, "%", trends.peak),
    ]);
    const detailsCell = document.createElement("td");
    detailsCell.colSpan = NIGHT_CHARGE_COLUMNS;
    const resultReason = document.createElement("p");
    resultReason.className = "plan-result-reason";
    resultReason.textContent = explanation;
    detailsCell.append(list, resultReason);
    if (history?.length) detailsCell.append(makeHistoryTable(history, plan.window.end));
    const details = document.createElement("tr");
    details.className = "plan-details";
    details.id = detailsId;
    details.hidden = true;
    details.append(detailsCell);

    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      summary.classList.toggle("is-open", open);
      details.hidden = !open;
    });
    summary.addEventListener("click", (event) => {
      if (!event.target.closest("button")) toggle.click();
    });

    body.append(summary, details);
  }
}

async function loadNightChargeReport() {
  try {
    const response = await fetch(NIGHT_CHARGE_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const report = await response.json();
    renderNightChargeRows(
      Array.isArray(report.nights) ? report.nights : [],
      "No night-charge plans yet. Plans are made between 22:00 and 06:00.",
    );
  } catch (error) {
    console.warn("Could not load the night-charge report.", error);
    renderNightChargeRows([], "The night-charge report is unavailable.");
  }
}

function renderEvAdvice(plan) {
  const container = document.getElementById("ev-decisions");
  const planTime = document.getElementById("ev-plan-time");
  const warnings = document.getElementById("ev-warnings");
  const formatPlanDay = (day) => new Intl.DateTimeFormat("en-AU", {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
  const tripDate = formatPlanDay(plan.tomorrow.date);
  const expired = Date.now() > new Date(plan.daytime.window.end).getTime();
  if (expired || !plan.dryRun) {
    container.textContent = "No current vehicle charge advice.";
    planTime.textContent = "Awaiting the next vehicle snapshot";
    return;
  }

  planTime.textContent = `Plan made ${formatPlanDateTime(plan.generatedAt)} · Vehicle ${formatAmount(plan.vehicleSoc, "%")} · ${formatAmount(plan.tomorrow.estimatedDistanceKm, " km")} estimated for ${tripDate}`;
  const overnight = document.createElement("div");
  overnight.className = "ev-decision";
  const nightPeriod = document.createElement("p");
  nightPeriod.className = "ev-period";
  nightPeriod.textContent = `Overnight · ${tripDate} · 00–06`;
  const nightSummary = document.createElement("div");
  nightSummary.className = "ev-decision-summary";
  const nightTitle = document.createElement("h4");
  nightTitle.textContent = plan.overnight.windowClosed ? "Window closed"
    : plan.overnight.decision === "charge" ? "Charge from grid" : "No charge";
  nightSummary.append(nightTitle);
  const nightContext = document.createElement("div");
  nightContext.className = "ev-decision-detail";
  const nightDetails = document.createElement("p");
  nightDetails.textContent = plan.overnight.windowClosed
    ? "The cheap-rate window has ended; daytime advice uses the latest vehicle SOC."
    : plan.overnight.decision === "charge"
    ? `${formatPlanTime(plan.overnight.start)}–${formatPlanTime(plan.overnight.end)} · ${plan.overnight.currentA} A · ${plan.overnight.durationMinutes} min · ${formatAmount(plan.overnight.energyFromGrid_kWh, " kWh")} · ${formatCurrency(plan.overnight.cost_AUD)}`
    : `Vehicle charge covers the estimated ${tripDate} drive.`;
  const nightProjection = document.createElement("p");
  nightProjection.className = "group-description";
  nightProjection.textContent = plan.overnight.windowClosed
    ? `Latest vehicle SOC: ${formatAmount(plan.vehicleSoc, "%")} · Reserve ${formatAmount(plan.minimumSoc, "%")}`
    : `After the ${tripDate} drive: ~${formatAmount(plan.tomorrow.socAfterDriving, "%")} · Reserve ${formatAmount(plan.minimumSoc, "%")}`;
  nightContext.append(nightDetails, nightProjection);
  overnight.append(nightPeriod, nightSummary, nightContext);

  const daytime = document.createElement("div");
  daytime.className = "ev-decision";
  const dayPeriod = document.createElement("p");
  dayPeriod.className = "ev-period";
  dayPeriod.textContent = `Daytime · ${tripDate} · ${formatDate(plan.daytime.window.start, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" })}–${formatDate(plan.daytime.window.end, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" })}`;
  const daySummary = document.createElement("div");
  daySummary.className = "ev-decision-summary";
  const dayTitle = document.createElement("h4");
  dayTitle.textContent = plan.daytime.decision === "charge" ? "Solar charging recommended" : "No solar charging recommended";
  const dayDetails = document.createElement("p");
  dayDetails.textContent = plan.daytime.decision === "charge"
    ? `If followed: ~${formatAmount(plan.daytime.energyFromSolar_kWh, " kWh")} AC from forecast surplus · ~${formatCurrency(plan.daytime.opportunityCost_AUD)} foregone export credit`
    : "No usable solar charging slots forecast (6 A minimum), or vehicle at its charge limit.";
  daySummary.append(dayTitle, dayDetails);
  const dayContext = document.createElement("div");
  dayContext.className = "ev-decision-detail";
  const requiredThreeDays = numberOrNull(plan.daytime.requiredSocForNextThreeDays);
  for (const slot of plan.daytime.slots) {
    const detail = document.createElement("p");
    detail.className = "ev-slot";
    detail.textContent = `${formatDate(slot.start, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" })}–${formatDate(slot.end, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" })} · ${slot.currentA} A · ${formatAmount(slot.energyFromSolar_kWh, " kWh")}`;
    dayContext.append(detail);
  }
  if (requiredThreeDays !== null && plan.tomorrow.socAfterDriving > requiredThreeDays) {
    const reserveNote = document.createElement("p");
    reserveNote.className = "group-description ev-reserve-note";
    reserveNote.textContent = plan.overnight.windowClosed
      ? `Without solar charging on ${tripDate}: ~${formatAmount(plan.tomorrow.socAfterDriving, "%")} after the full estimated drive from the latest SOC, above ~${formatAmount(requiredThreeDays, "%")} estimated for ${formatPlanDay(offsetDate(plan.tomorrow.date, 1))}–${formatPlanDay(offsetDate(plan.tomorrow.date, 3))} including reserve.`
      : `Without solar charging on ${tripDate}: ~${formatAmount(plan.tomorrow.socAfterDriving, "%")} after the drive, above ~${formatAmount(requiredThreeDays, "%")} estimated for ${formatPlanDay(offsetDate(plan.tomorrow.date, 1))}–${formatPlanDay(offsetDate(plan.tomorrow.date, 3))} including reserve.`;
    dayContext.append(reserveNote);
  }
  daytime.append(dayPeriod, daySummary, dayContext);
  container.replaceChildren(overnight, daytime);
  if (plan.warnings?.length) {
    warnings.textContent = plan.warnings.join(" ");
    warnings.hidden = false;
  } else {
    warnings.hidden = true;
  }
}

async function loadEvAdvice() {
  try {
    const response = await fetch(EV_CHARGE_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderEvAdvice(await response.json());
  } catch (error) {
    console.warn("Could not load EV charge advice.", error);
    document.getElementById("ev-decisions").textContent = "Vehicle charge advice is unavailable.";
  }
}

async function main() {
  if (typeof Chart === "undefined") {
    showNotice("The chart library could not be loaded. Check your network connection and reload the page.");
    return;
  }

  try {
    const response = await fetch(HISTORY_URL, { cache: "no-cache" });
    if (!response.ok) {
      throw new Error(`Failed to load energy history (${response.status}).`);
    }
    const history = await response.json();
    if (!Array.isArray(history.records)) {
      throw new Error("The energy history file has an invalid format.");
    }
    renderDashboard(
      history.records,
      history.generatedAt ?? new Date().toISOString(),
      history.tariff?.timezone ?? "Australia/Sydney",
      history.costWarnings ?? [],
      history.tariff?.billingCycleStartDay,
    );
  } catch (error) {
    showNotice(`${error.message} Run the “Deploy energy dashboard” workflow on GitHub.`);
    document.getElementById("last-updated").textContent = "Unable to load data";
  }
}

initializeThemeToggle();
main();
loadNightChargeReport();
loadEvAdvice();