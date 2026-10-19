const SETTINGS_URL = "data/settings.json";
const GROUP_IDS = ["electricity", "home-battery", "vehicle"];

const settingsThemeMedia = window.matchMedia("(prefers-color-scheme: dark)");

function updateThemeControls() {
  const dark = document.documentElement.dataset.theme === "dark";
  const mode = document.documentElement.dataset.themeMode ?? "auto";
  document.getElementById("theme-icon").textContent = dark ? "☀" : "☾";
  document.getElementById("theme-label").textContent =
    mode === "auto" ? "Auto" : mode === "light" ? "Light" : "Dark";
  document.getElementById("theme-toggle").setAttribute("aria-label", `Theme mode: ${mode === "auto" ? "Auto" : mode === "light" ? "Light" : "Dark"}`);
  document.querySelector('meta[name="theme-color"]').content = dark ? "#10191d" : "#edf4f2";
}

settingsThemeMedia.addEventListener("change", (event) => {
  if (document.documentElement.dataset.themeMode !== "auto") return;
  document.documentElement.dataset.theme = event.matches ? "dark" : "light";
  updateThemeControls();
});
document.getElementById("theme-toggle").addEventListener("click", () => {
  const current = document.documentElement.dataset.themeMode ?? "auto";
  const next = current === "auto" ? "light" : current === "light" ? "dark" : "auto";
  document.documentElement.dataset.themeMode = next;
  document.documentElement.dataset.theme = next === "auto" ? (settingsThemeMedia.matches ? "dark" : "light") : next;
  updateThemeControls();
  try {
    if (next === "auto") localStorage.removeItem("esy-theme");
    else localStorage.setItem("esy-theme", next);
  } catch (error) {
    console.warn("Could not save the theme preference.", error);
  }
});
updateThemeControls();

function renderGroup(group, id) {
  const section = document.createElement("section");
  section.className = "settings-group";
  section.id = id;
  section.setAttribute("aria-labelledby", `${id}-title`);

  const header = document.createElement("header");
  header.className = "settings-group-heading";
  const title = document.createElement("h2");
  title.id = `${id}-title`;
  title.textContent = group.title;
  const description = document.createElement("p");
  description.textContent = group.description;
  header.append(title, description);

  const list = document.createElement("dl");
  list.className = "settings-list";
  for (const setting of group.items) {
    const row = document.createElement("div");
    row.className = "settings-row";
    const label = document.createElement("dt");
    label.textContent = setting.label;
    const detail = document.createElement("small");
    detail.textContent = setting.detail;
    label.append(detail);
    const value = document.createElement("dd");
    value.textContent = setting.value;
    row.append(label, value);
    list.append(row);
  }
  section.append(header, list);

  if (group.schedule?.length) {
    const table = document.createElement("table");
    table.className = "settings-schedule";
    const caption = document.createElement("caption");
    caption.textContent = "Import prices by time";
    const head = document.createElement("thead");
    const headingRow = document.createElement("tr");
    for (const text of ["Time", "Period", "Price"]) {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = text;
      headingRow.append(cell);
    }
    head.append(headingRow);
    const body = document.createElement("tbody");
    for (const period of group.schedule) {
      const row = document.createElement("tr");
      for (const value of [period.hours, period.name, period.price]) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      }
      body.append(row);
    }
    table.append(caption, head, body);
    section.append(table);
  }
  return section;
}

async function loadSettings() {
  const content = document.getElementById("settings-content");
  try {
    const response = await fetch(SETTINGS_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const report = await response.json();
    if (!Array.isArray(report.groups) || report.groups.length !== GROUP_IDS.length ||
        report.groups.some((group) => !Array.isArray(group.items))) {
      throw new Error("Invalid settings report");
    }
    const index = document.getElementById("settings-index");
    for (const [position, group] of report.groups.entries()) {
      const link = document.createElement("a");
      link.href = `#${GROUP_IDS[position]}`;
      link.textContent = group.title;
      index.append(link);
    }
    content.replaceChildren(...report.groups.map((group, position) => renderGroup(group, GROUP_IDS[position])));
    index.hidden = false;
    const links = [...index.querySelectorAll("a")];
    const sections = GROUP_IDS.map((id) => document.getElementById(id));
    const setActive = (position) => {
      for (const [linkPosition, link] of links.entries()) {
        if (linkPosition === position) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      }
    };
    const trackSection = () => {
      const threshold = index.getBoundingClientRect().bottom + 44;
      let active = 0;
      for (const [position, section] of sections.entries()) {
        if (section.getBoundingClientRect().top > threshold) break;
        active = position;
      }
      setActive(active);
    };
    links.forEach((link, position) => link.addEventListener("click", () => setActive(position)));
    window.addEventListener("scroll", trackSection, { passive: true });
    window.addEventListener("resize", trackSection);
    if (GROUP_IDS.includes(location.hash.slice(1))) {
      document.getElementById(location.hash.slice(1)).scrollIntoView();
    }
    trackSection();
  } catch (error) {
    console.warn("Could not load the settings report.", error);
    content.querySelector(".settings-feedback").textContent = "Settings are unavailable. The published configuration report could not be loaded.";
  }
}

loadSettings();