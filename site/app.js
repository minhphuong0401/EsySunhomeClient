const HISTORY_URL = "data/history.json";
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

const formatDate = (timestamp, options) =>
  new Intl.DateTimeFormat("en-AU", { ...options, timeZone: dashboardTimezone }).format(new Date(timestamp));

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

function renderDashboard(records, generatedAt, timeZone, costWarnings = []) {
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
    latestByDay.set(localDay(record.timestamp ?? record.mqttCurrentTime), record);
  }
  const dailyRecords = [...latestByDay.values()];
  if (costWarnings.length > 0) {
    const warningDates = costWarnings.map((warning) => warning.date).join(", ");
    showNotice(`Some daily cost estimates may be incomplete due to missing or reset meter readings (${warningDates}).`);
  }
  const today = dateInputValue(new Date(now));
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
    );
  } catch (error) {
    showNotice(`${error.message} Run the “Deploy energy dashboard” workflow on GitHub.`);
    document.getElementById("last-updated").textContent = "Unable to load data";
  }
}

initializeThemeToggle();
main();
