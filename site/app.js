const HISTORY_URL = "data/history.json";
const DAY_MS = 24 * 60 * 60 * 1000;

const FIELDS = {
  pv: "photovoltaicPowerGenerationToday_kWh",
  consumption: "totalConsumptionToday_kWh",
  bought: "buyElectricityToday_kWh",
  sold: "sellingElectricityToday_kWh",
  soc: "batterySoc_percent",
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
  soc: "--series-soc",
  socFill: "--series-soc-fill",
};

let refreshChartsForTheme = () => {};

const numberOrNull = (value) => {
  const number = Number(value);
  return value !== null && value !== "" && Number.isFinite(number) ? number : null;
};

const localDay = (timestamp) => {
  const date = new Date(timestamp);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
};

const dateInputValue = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

const offsetDate = (dateValue, days) => {
  const [year, month, day] = dateValue.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  date.setDate(date.getDate() + days);
  return dateInputValue(date);
};

const formatDate = (timestamp, options) =>
  new Intl.DateTimeFormat("en-AU", options).format(new Date(timestamp));

const themeColor = (property) =>
  getComputedStyle(document.documentElement).getPropertyValue(property).trim();

function updateThemeControls() {
  const dark = document.documentElement.dataset.theme === "dark";
  document.getElementById("theme-icon").textContent = dark ? "☀" : "☾";
  document.getElementById("theme-label").textContent = dark ? "Light mode" : "Dark mode";
  document.getElementById("theme-toggle").setAttribute(
    "aria-label",
    `Switch to ${dark ? "light" : "dark"} mode`,
  );
  document.querySelector('meta[name="theme-color"]').content = dark ? "#10191d" : "#edf4f2";
}

function initializeThemeToggle() {
  const button = document.getElementById("theme-toggle");
  updateThemeControls();
  button.addEventListener("click", () => {
    const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = nextTheme;
    updateThemeControls();
    try {
      localStorage.setItem("esy-theme", nextTheme);
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

function makeChartOptions(unit, { percent = false } = {}) {
  const textColor = themeColor("--chart-text");
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
            const label = items[0]?.label;
            if (!label) return "";
            const date = new Date(label);
            return Number.isNaN(date.getTime())
              ? label
              : formatDate(date, { dateStyle: "medium", timeStyle: percent ? "short" : undefined });
          },
          label(context) {
            return `${context.dataset.label}: ${context.parsed.y ?? "—"} ${unit}`;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        border: { display: false },
        ticks: {
          color: textColor,
          maxTicksLimit: percent ? 5 : 10,
          maxRotation: 0,
          font: { family: "DM Sans", size: 9 },
          callback(value) {
            const label = this.getLabelForValue(value);
            const date = new Date(label);
            if (Number.isNaN(date.getTime())) return label;
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
        ticks: { color: textColor, maxTicksLimit: 5, font: { family: "DM Sans", size: 9 }, callback: (value) => `${value}${percent ? "%" : ""}` },
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
    tension: 0.28,
    fill: false,
    spanGaps: true,
  };
}

function showNotice(message) {
  const notice = document.getElementById("notice");
  notice.textContent = message;
  notice.hidden = false;
}

function renderDashboard(records, generatedAt) {
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
  setMetric("metric-soc", numberOrNull(latest[FIELDS.soc]), "%");
  document.getElementById("last-updated").textContent =
    `Updated ${formatDate(latestTimestamp, { dateStyle: "medium", timeStyle: "short" })}`;
  document.getElementById("snapshot-count").textContent =
    `${recent.length.toLocaleString("en-AU")} snapshots · generated ${formatDate(generatedAt, { dateStyle: "medium", timeStyle: "short" })}`;

  const latestByDay = new Map();
  for (const record of recent) {
    latestByDay.set(localDay(record.timestamp ?? record.mqttCurrentTime), record);
  }
  const dailyRecords = [...latestByDay.values()];
  const today = dateInputValue(new Date(now));
  const earliest = dateInputValue(new Date(now - 90 * DAY_MS));
  const defaultStart = offsetDate(today, -6);
  const dateInputs = {
    energyFrom: document.getElementById("energy-from"),
    energyTo: document.getElementById("energy-to"),
    socFrom: document.getElementById("soc-from"),
    socTo: document.getElementById("soc-to"),
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
    ];
    energyChart.update();
  };

  const updateSocChart = () => {
    const selectedSnapshots = recent.filter((record) => {
      const day = localDay(record.timestamp ?? record.mqttCurrentTime);
      return day >= dateInputs.socFrom.value && day <= dateInputs.socTo.value;
    });
    socChart.data.labels = selectedSnapshots.map((record) => record.timestamp ?? record.mqttCurrentTime);
    socChart.data.datasets = [
      {
        ...makeDataset("Battery charge", selectedSnapshots.map((record) => numberOrNull(record[FIELDS.soc])), themeColor(COLORS.soc), themeColor(COLORS.socFill)),
        fill: true,
      },
    ];
    socChart.update();
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
  updateEnergyChart();
  updateSocChart();
  refreshChartsForTheme = () => {
    energyChart.options = makeChartOptions("kWh");
    socChart.options = makeChartOptions("%", { percent: true });
    updateEnergyChart();
    updateSocChart();
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
    renderDashboard(history.records, history.generatedAt ?? new Date().toISOString());
  } catch (error) {
    showNotice(`${error.message} Run the “Deploy energy dashboard” workflow on GitHub.`);
    document.getElementById("last-updated").textContent = "Unable to load data";
  }
}

initializeThemeToggle();
main();
