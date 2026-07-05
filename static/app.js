const REFRESH_MS = 7000;
const HISTORY_REFRESH_MS = 60000;
const DEFAULT_LIVE_INTERVAL_MS = 2000;
const MAX_PHASE_POINTS = 90; // Anzahl Messpunkte im Rolling-Fenster, unabhängig vom gewählten Intervall

const PHASE_COLORS = { a: "#22d3ee", b: "#a78bfa", c: "#ff8a5c", sum: "#39ff9d" };
const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

const state = {
  devices: [],
  currentByDevice: {},
  tariff: null,
  historyRange: "day",
  phaseBuffer: [],
  liveIntervalMs: DEFAULT_LIVE_INTERVAL_MS,
  paused: false,
};

let liveTimer = null;

function fmtW(w) {
  if (w === null || w === undefined) return "–";
  return `${Math.round(w)} W`;
}

function fmtKwh(kwh) {
  if (kwh === null || kwh === undefined) return "–";
  return `${kwh.toFixed(2)} kWh`;
}

function fmtEur(eur) {
  if (eur === null || eur === undefined) return "–";
  return `${eur.toFixed(2)} €`;
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    throw new Error(`API-Fehler ${res.status} bei ${path}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

function isStale(reading, thresholdMs = REFRESH_MS * 4) {
  if (!reading || !reading.ts) return true;
  const ts = new Date(reading.ts).getTime();
  return Date.now() - ts > thresholdMs;
}

function drawSparkline(canvas, values) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width = canvas.clientWidth * 2;
  const h = canvas.height = canvas.clientHeight * 2;
  ctx.clearRect(0, 0, w, h);

  const nums = values.filter((v) => v !== null && v !== undefined);
  if (nums.length < 2) return;

  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const range = max - min || 1;
  const stepX = w / (values.length - 1);

  ctx.beginPath();
  values.forEach((v, i) => {
    if (v === null || v === undefined) return;
    const x = i * stepX;
    const y = h - ((v - min) / range) * (h * 0.85) - h * 0.075;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = "#39ff9d";
  ctx.lineWidth = 3;
  ctx.stroke();
}

function drawBigChart(canvas, points, mode) {
  const ctx = canvas.getContext("2d");
  const w = (canvas.width = canvas.clientWidth * 2);
  const h = (canvas.height = canvas.clientHeight * 2);
  ctx.clearRect(0, 0, w, h);

  const values = points.map((p) => p.value).filter((v) => v !== null && v !== undefined);
  if (values.length === 0) return;

  const min = mode === "bar" ? 0 : Math.min(...values);
  const max = Math.max(...values, min + 1);
  const range = max - min || 1;
  const padLeft = 70;
  const padBottom = 40;
  const plotW = w - padLeft - 10;
  const plotH = h - padBottom - 20;

  ctx.strokeStyle = "#163044";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(padLeft, 20);
  ctx.lineTo(padLeft, plotH + 20);
  ctx.lineTo(w - 10, plotH + 20);
  ctx.stroke();

  ctx.fillStyle = "#6f93a8";
  ctx.font = "22px Consolas, monospace";
  ctx.fillText(Math.round(max).toString(), 4, 34);
  ctx.fillText(Math.round(min).toString(), 4, plotH + 20);

  if (mode === "bar") {
    const slot = plotW / points.length;
    const barW = slot * 0.65;
    points.forEach((p, i) => {
      if (p.value === null || p.value === undefined) return;
      const x = padLeft + i * slot + (slot - barW) / 2;
      const barH = ((p.value - min) / range) * plotH;
      ctx.fillStyle = "#39ff9d";
      ctx.fillRect(x, plotH + 20 - barH, barW, barH);
    });
  } else {
    ctx.beginPath();
    let started = false;
    points.forEach((p, i) => {
      if (p.value === null || p.value === undefined) return;
      const x = padLeft + (i / (points.length - 1 || 1)) * plotW;
      const y = plotH + 20 - ((p.value - min) / range) * plotH;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.strokeStyle = "#39ff9d";
    ctx.lineWidth = 4;
    ctx.stroke();
  }

  ctx.fillStyle = "#6f93a8";
  ctx.font = "20px Consolas, monospace";
  const labelIdxs = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  [...new Set(labelIdxs)].forEach((idx) => {
    const p = points[idx];
    if (!p) return;
    const slotCenter =
      mode === "bar" ? padLeft + idx * (plotW / points.length) + plotW / points.length / 2 : padLeft + (idx / (points.length - 1 || 1)) * plotW;
    ctx.fillText(p.label, Math.min(Math.max(slotCenter - 30, 0), w - 60), h - 6);
  });
}

function drawMultiLineChart(canvas, seriesList) {
  const ctx = canvas.getContext("2d");
  const w = (canvas.width = canvas.clientWidth * 2);
  const h = (canvas.height = canvas.clientHeight * 2);
  ctx.clearRect(0, 0, w, h);

  const allValues = seriesList.flatMap((s) => s.values.filter((v) => v !== null && v !== undefined));
  if (allValues.length < 2) return;

  const min = Math.min(...allValues, 0);
  const max = Math.max(...allValues, min + 1);
  const range = max - min || 1;
  const padLeft = 70;
  const plotW = w - padLeft - 10;
  const plotH = h - 30;
  const count = Math.max(...seriesList.map((s) => s.values.length));

  ctx.strokeStyle = "#163044";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(padLeft, 20);
  ctx.lineTo(padLeft, plotH + 20);
  ctx.lineTo(w - 10, plotH + 20);
  ctx.stroke();

  ctx.fillStyle = "#6f93a8";
  ctx.font = "20px Consolas, monospace";
  const gridLines = 4;
  for (let i = 0; i <= gridLines; i++) {
    const frac = i / gridLines;
    const value = max - frac * range;
    const y = 20 + frac * plotH;
    ctx.strokeStyle = "rgba(22, 48, 68, 0.6)";
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(w - 10, y);
    ctx.stroke();
    ctx.fillText(Math.round(value).toString(), 4, y + 6);
  }

  seriesList.forEach((series) => {
    ctx.beginPath();
    let started = false;
    series.values.forEach((v, i) => {
      if (v === null || v === undefined) return;
      const x = padLeft + (i / (count - 1 || 1)) * plotW;
      const y = plotH + 20 - ((v - min) / range) * plotH;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.strokeStyle = series.color;
    ctx.lineWidth = 3;
    ctx.stroke();
  });
}

function mainMeterDevice() {
  return state.devices.find((d) => d.device_type === "shelly_pro_3em") || null;
}

// --- Kopfzeile: Uhr, Verbindungsstatus, Vollbild ---

function updateClock() {
  const now = new Date();
  document.getElementById("clockTime").textContent = now.toLocaleTimeString("de-DE");
  document.getElementById("clockDate").textContent = now.toLocaleDateString("de-DE");
}

function setConnStatus(connected, label) {
  const dot = document.getElementById("connDot");
  const text = document.getElementById("connLabel");
  dot.classList.toggle("offline", !connected);
  text.textContent = label;
}

function updateConnStatusFromReading(reading) {
  const threshold = Math.max(state.liveIntervalMs * 3, 15000);
  const ok = !isStale(reading, threshold);
  setConnStatus(ok, ok ? "Verbunden" : "Getrennt");
}

document.getElementById("fullscreenBtn").addEventListener("click", () => {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else {
    document.exitFullscreen();
  }
});

// --- Live-Tab: Phasen-Karten + kombinierter Chart ---

function redrawPhaseChartOnly() {
  const canvas = document.getElementById("phaseChart");
  drawMultiLineChart(canvas, [
    { color: PHASE_COLORS.a, values: state.phaseBuffer.map((p) => p.a) },
    { color: PHASE_COLORS.b, values: state.phaseBuffer.map((p) => p.b) },
    { color: PHASE_COLORS.c, values: state.phaseBuffer.map((p) => p.c) },
    { color: PHASE_COLORS.sum, values: state.phaseBuffer.map((p) => p.sum) },
  ]);
}

function updatePhaseCards(reading) {
  let meta = null;
  try {
    meta = reading.phase_meta ? JSON.parse(reading.phase_meta) : null;
  } catch {
    meta = null;
  }

  const phases = [
    { key: "a", power: reading.phase_a_w },
    { key: "b", power: reading.phase_b_w },
    { key: "c", power: reading.phase_c_w },
  ];

  phases.forEach(({ key, power }) => {
    const card = document.querySelector(`.phase-card[data-phase="${key}"]`);
    if (!card) return;
    card.querySelector(".phase-power .value").textContent = power !== null && power !== undefined ? Math.round(power) : "–";
    const m = meta ? meta[key] : null;
    card.querySelector('[data-field="voltage"]').textContent = m && m.voltage != null ? `${m.voltage.toFixed(1)} V` : "–";
    card.querySelector('[data-field="current"]').textContent = m && m.current != null ? `${m.current.toFixed(2)} A` : "–";
    card.querySelector('[data-field="pf"]').textContent = m && m.pf != null ? m.pf.toFixed(3) : "–";
    card.querySelector('[data-field="freq"]').textContent = m && m.freq != null ? `${m.freq.toFixed(2)} Hz` : "–";
  });
}

async function pollPhases() {
  const meter = mainMeterDevice();

  if (!meter) {
    state.phaseBuffer = [];
    document.getElementById("phaseChart").getContext("2d").clearRect(0, 0, 1, 1);
    updateConnStatusFromReading(null);
    return;
  }

  let reading;
  try {
    reading = await api(`/api/devices/${meter.id}/current`);
  } catch {
    return;
  }

  updateConnStatusFromReading(reading);
  if (!reading) return;

  state.currentByDevice[meter.id] = reading;
  updatePhaseCards(reading);

  if (reading.phase_a_w !== null && reading.phase_a_w !== undefined) {
    state.phaseBuffer.push({ a: reading.phase_a_w, b: reading.phase_b_w, c: reading.phase_c_w, sum: reading.power_w });
    if (state.phaseBuffer.length > MAX_PHASE_POINTS) {
      state.phaseBuffer.shift();
    }
    redrawPhaseChartOnly();
  }
}

function statCellHud(label, value, sub, accentClass) {
  const div = document.createElement("div");
  div.className = `stat-cell ${accentClass || ""}`;
  div.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub || ""}</div>`;
  return div;
}

async function loadLiveStats() {
  const statBar = document.getElementById("liveStatBar");
  const meter = mainMeterDevice();

  if (!meter) {
    statBar.innerHTML = `<div class="empty-hint">Kein Hauptzähler (Shelly Pro 3EM) eingerichtet.</div>`;
    return;
  }

  const current = state.currentByDevice[meter.id];
  const peakSince = localStorage.getItem("peakResetAt");
  let peakData = { peak_w: null, first_ts: null };
  try {
    const params = new URLSearchParams();
    if (peakSince) params.set("since", peakSince);
    peakData = await api(`/api/devices/${meter.id}/peak?${params.toString()}`);
  } catch {
    // ignorieren, Kennzahlen bleiben leer
  }

  const gesamtKwh = current?.energy_wh_total != null ? current.energy_wh_total / 1000 : null;
  const arbeitspreis = state.tariff?.arbeitspreis_ct_kwh ?? null;
  const grundpreisMonat = state.tariff?.grundpreis_monat ?? null;
  const arbeitskosten = gesamtKwh !== null && arbeitspreis !== null ? (gesamtKwh * arbeitspreis) / 100 : null;

  let gesamtkosten = arbeitskosten;
  if (arbeitskosten !== null && grundpreisMonat !== null && peakData.first_ts) {
    const days = Math.max(1, (Date.now() - new Date(peakData.first_ts).getTime()) / 86400000);
    gesamtkosten = arbeitskosten + (days / 30) * grundpreisMonat;
  }

  statBar.innerHTML = "";
  statBar.appendChild(statCellHud("Gesamt", fmtW(current?.power_w), "aktuelle Last", "accent-green"));
  statBar.appendChild(
    statCellHud("Peak", peakData.peak_w != null ? fmtW(peakData.peak_w) : "–", peakSince ? "seit Reset" : "seit Aufzeichnungsbeginn", "accent-cyan")
  );
  statBar.appendChild(statCellHud("Gesamt kWh", gesamtKwh != null ? fmtKwh(gesamtKwh) : "–", "Lebenszeit-Zähler", ""));
  statBar.appendChild(
    statCellHud("Arbeitskosten", arbeitskosten != null ? fmtEur(arbeitskosten) : "–", arbeitspreis != null ? `${arbeitspreis} ct/kWh` : "", "accent-warn")
  );
  statBar.appendChild(
    statCellHud("Gesamtkosten", gesamtkosten != null ? fmtEur(gesamtkosten) : "–", "inkl. anteiligem Grundpreis", "accent-danger")
  );
}

async function liveTick() {
  if (state.paused) return;
  await Promise.all([pollPhases(), loadLiveStats()]);
}

function restartLiveTimer() {
  if (liveTimer) clearInterval(liveTimer);
  liveTimer = setInterval(() => liveTick().catch(() => {}), state.liveIntervalMs);
}

function updateTariffDisplay() {
  const el = document.getElementById("tariffDisplay");
  if (!state.tariff) {
    el.textContent = "";
    return;
  }
  const namePart = state.tariff.name ? `${state.tariff.name} · ` : "";
  el.textContent = `⚡ ${namePart}${state.tariff.arbeitspreis_ct_kwh} ct/kWh + ${state.tariff.grundpreis_monat} €/Mon`;
}

function downloadCsv() {
  const meter = mainMeterDevice();
  if (!meter) {
    alert("Kein Hauptzähler eingerichtet.");
    return;
  }
  const a = document.createElement("a");
  a.href = `/api/devices/${meter.id}/export.csv?range=all`;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function resetPeak() {
  localStorage.setItem("peakResetAt", new Date().toISOString());
  loadLiveStats().catch(() => {});
}

// --- Verlauf (History) ---

function populateHistoryDeviceSelect() {
  const select = document.getElementById("historyDevice");
  const prevValue = select.value;
  select.innerHTML = state.devices.map((d) => `<option value="${d.id}">${d.name}</option>`).join("");
  if (state.devices.some((d) => String(d.id) === prevValue)) {
    select.value = prevValue;
  } else if (state.devices.length > 0) {
    select.value = String(state.devices[0].id);
  }
}

async function loadHistoryChart() {
  const canvas = document.getElementById("historyChart");
  const summaryEl = document.getElementById("historySummary");
  const select = document.getElementById("historyDevice");

  if (!select.value) {
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    summaryEl.textContent = "Kein Gerät ausgewählt.";
    return;
  }

  const deviceId = parseInt(select.value, 10);
  const points = await api(`/api/devices/${deviceId}/history?range=${state.historyRange}`);

  if (points.length === 0) {
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    summaryEl.textContent = "Noch keine Daten für diesen Zeitraum.";
    return;
  }

  let series;
  if (state.historyRange === "month") {
    series = [];
    for (let i = 1; i < points.length; i++) {
      const prevE = points[i - 1].energy_wh_total;
      const curE = points[i].energy_wh_total;
      const kwh = prevE !== null && curE !== null && prevE !== undefined && curE !== undefined ? Math.max(0, (curE - prevE) / 1000) : null;
      series.push({ label: points[i].bucket.slice(5), value: kwh });
    }
  } else {
    series = points.map((p) => ({
      label: p.bucket.slice(state.historyRange === "day" ? 11 : 5),
      value: p.power_w,
    }));
  }

  if (series.filter((p) => p.value !== null && p.value !== undefined).length < 2) {
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    summaryEl.textContent = "Noch nicht genug Daten für diesen Zeitraum – es sammeln sich mit der Zeit mehr Messwerte.";
    return;
  }

  drawBigChart(canvas, series, state.historyRange === "month" ? "bar" : "line");

  const withEnergy = points.filter((p) => p.energy_wh_total !== null && p.energy_wh_total !== undefined);
  if (withEnergy.length >= 2) {
    const kwh = Math.max(0, (withEnergy[withEnergy.length - 1].energy_wh_total - withEnergy[0].energy_wh_total) / 1000);
    const cost = state.tariff ? (kwh * state.tariff.arbeitspreis_ct_kwh) / 100 : null;
    summaryEl.textContent = `Verbrauch im Zeitraum: ${fmtKwh(kwh)}${cost !== null ? ` · ${fmtEur(cost)}` : ""}`;
  } else {
    summaryEl.textContent = "";
  }
}

// --- Kalender ---

async function renderCalendar() {
  const grid = document.getElementById("calendarGrid");
  const title = document.getElementById("calendarTitle");
  const meter = mainMeterDevice();
  const now = new Date();
  title.textContent = `Kalender · ${now.toLocaleDateString("de-DE", { month: "long", year: "numeric" })}`;

  if (!meter) {
    grid.innerHTML = `<div class="empty-hint">Kein Hauptzähler (Shelly Pro 3EM) eingerichtet.</div>`;
    return;
  }

  let points;
  try {
    points = await api(`/api/devices/${meter.id}/history?range=month`);
  } catch {
    grid.innerHTML = `<div class="empty-hint">Verlauf konnte nicht geladen werden.</div>`;
    return;
  }

  const kwhByDay = {};
  for (let i = 1; i < points.length; i++) {
    const day = parseInt(points[i].bucket.slice(8, 10), 10);
    const prevE = points[i - 1].energy_wh_total;
    const curE = points[i].energy_wh_total;
    if (prevE !== null && curE !== null && prevE !== undefined && curE !== undefined) {
      kwhByDay[day] = Math.max(0, (curE - prevE) / 1000);
    }
  }

  const year = now.getFullYear();
  const month = now.getMonth();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7; // Montag = 0

  grid.innerHTML = "";
  WEEKDAYS.forEach((wd) => {
    const el = document.createElement("div");
    el.className = "calendar-weekday";
    el.textContent = wd;
    grid.appendChild(el);
  });

  for (let i = 0; i < firstWeekday; i++) {
    const el = document.createElement("div");
    el.className = "calendar-day empty";
    grid.appendChild(el);
  }

  for (let day = 1; day <= daysInMonth; day++) {
    const el = document.createElement("div");
    const isToday = day === now.getDate();
    el.className = `calendar-day${isToday ? " today" : ""}`;
    const kwh = kwhByDay[day];
    el.innerHTML = `<div class="day-number">${day}</div><div class="day-kwh">${kwh !== undefined ? kwh.toFixed(1) + " kWh" : "–"}</div>`;
    grid.appendChild(el);
  }
}

// --- Verbraucher-Zusammenfassung (Tarif + Geräte-Karten) ---

async function loadTariffAndDeviceSummary() {
  const today = await api("/api/summary?period=today");
  state.tariff = today.tariff;
  updateTariffDisplay();
  renderDeviceCards(today);
}

function renderDeviceCards(todaySummary) {
  const grid = document.getElementById("deviceGrid");
  grid.innerHTML = "";

  const plugs = state.devices.filter((d) => d.device_type === "shelly_plug_s_gen3");

  if (plugs.length === 0) {
    grid.innerHTML = `<div class="empty-hint">Noch keine Verbraucher eingerichtet. Über das ⚙-Menü Geräte hinzufügen.</div>`;
    return;
  }

  for (const device of plugs) {
    const current = state.currentByDevice[device.id];
    const summary = todaySummary.devices.find((d) => d.device_id === device.id);
    const stale = isStale(current);

    const card = document.createElement("div");
    card.className = "device-card";
    card.innerHTML = `
      <div class="name">
        <span>${device.name}</span>
        <span class="badge ${stale ? "offline" : ""}">${stale ? "offline" : "online"}</span>
      </div>
      <div class="power">${fmtW(current?.power_w)}</div>
      <div class="row"><span>Heute</span><span>${fmtKwh(summary?.kwh)} · ${fmtEur(summary?.cost_eur)}</span></div>
      <canvas></canvas>
    `;
    grid.appendChild(card);

    api(`/api/devices/${device.id}/history?range=day`)
      .then((points) => drawSparkline(card.querySelector("canvas"), points.map((p) => p.power_w)))
      .catch(() => {});
  }
}

async function refreshCurrentReadings() {
  await Promise.all(
    state.devices.map(async (device) => {
      try {
        state.currentByDevice[device.id] = await api(`/api/devices/${device.id}/current`);
      } catch {
        state.currentByDevice[device.id] = null;
      }
    })
  );
}

async function refreshAll() {
  state.devices = await api("/api/devices");
  await refreshCurrentReadings();
  await loadTariffAndDeviceSummary();
  populateHistoryDeviceSelect();
}

// --- Settings modal ---

function openSettings() {
  document.getElementById("settingsModal").classList.remove("hidden");
  renderDeviceList();
  if (state.tariff) {
    document.getElementById("tariffName").value = state.tariff.name || "";
    document.getElementById("tariffGrundpreis").value = state.tariff.grundpreis_monat;
    document.getElementById("tariffArbeitspreis").value = state.tariff.arbeitspreis_ct_kwh;
  }
}

function closeSettings() {
  document.getElementById("settingsModal").classList.add("hidden");
}

function renderDeviceList() {
  const list = document.getElementById("deviceList");
  list.innerHTML = "";
  if (state.devices.length === 0) {
    list.innerHTML = `<div class="empty-hint">Noch keine Geräte angelegt.</div>`;
    return;
  }
  for (const device of state.devices) {
    const row = document.createElement("div");
    row.className = "device-list-item";
    const typeLabel = device.device_type === "shelly_pro_3em" ? "Hauptzähler (Pro 3EM)" : "Plug S (Gen3)";
    row.innerHTML = `
      <div>
        <div>${device.name}</div>
        <div class="meta">${typeLabel} · ${device.ip_address}</div>
      </div>
      <button class="danger-link">Entfernen</button>
    `;
    row.querySelector("button").addEventListener("click", async () => {
      await api(`/api/devices/${device.id}`, { method: "DELETE" });
      await refreshAll();
      renderDeviceList();
    });
    list.appendChild(row);
  }
}

async function addDevice() {
  const name = document.getElementById("newDeviceName").value.trim();
  const device_type = document.getElementById("newDeviceType").value;
  const ip_address = document.getElementById("newDeviceIp").value.trim();
  if (!name || !ip_address) {
    alert("Bitte Name und IP-Adresse angeben.");
    return;
  }
  await api("/api/devices", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, device_type, ip_address }),
  });
  document.getElementById("newDeviceName").value = "";
  document.getElementById("newDeviceIp").value = "";
  document.getElementById("newDeviceType").value = "shelly_plug_s_gen3";
  await refreshAll();
  renderDeviceList();
}

async function saveTariff() {
  const name = document.getElementById("tariffName").value.trim();
  const grundpreis_monat = parseFloat(document.getElementById("tariffGrundpreis").value);
  const arbeitspreis_ct_kwh = parseFloat(document.getElementById("tariffArbeitspreis").value);
  if (Number.isNaN(grundpreis_monat) || Number.isNaN(arbeitspreis_ct_kwh)) {
    alert("Bitte gültige Zahlen für den Tarif angeben.");
    return;
  }
  await api("/api/tariff", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name || null, grundpreis_monat, arbeitspreis_ct_kwh }),
  });
  await loadTariffAndDeviceSummary();
}

document.getElementById("settingsBtn").addEventListener("click", openSettings);
document.getElementById("closeSettings").addEventListener("click", closeSettings);
document.getElementById("addDeviceBtn").addEventListener("click", addDevice);
document.getElementById("saveTariffBtn").addEventListener("click", saveTariff);

document.getElementById("csvBtn").addEventListener("click", downloadCsv);
document.getElementById("resetPeakBtn").addEventListener("click", resetPeak);

document.getElementById("liveInterval").addEventListener("change", (e) => {
  state.liveIntervalMs = parseInt(e.target.value, 10);
  restartLiveTimer();
});

document.getElementById("pauseBtn").addEventListener("click", () => {
  state.paused = !state.paused;
  const btn = document.getElementById("pauseBtn");
  if (state.paused) {
    btn.textContent = "Verbinden";
    btn.classList.remove("btn-danger");
    btn.classList.add("btn-accent");
    setConnStatus(false, "Pausiert");
  } else {
    btn.textContent = "Trennen";
    btn.classList.remove("btn-accent");
    btn.classList.add("btn-danger");
    liveTick().catch(() => {});
  }
});

document.querySelectorAll(".section-tab").forEach((btn) => {
  if (btn.disabled) return;
  btn.addEventListener("click", () => {
    document.querySelectorAll(".section-tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const panelName = btn.dataset.panel;
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
    document.getElementById(`panel-${panelName}`).classList.remove("hidden");

    // Canvas-Charts brauchen eine sichtbare (nicht display:none) Fläche, um korrekt
    // zu zeichnen, daher hier gezielt neu laden/zeichnen statt auf den nächsten Timer zu warten.
    if (panelName === "live") {
      if (state.paused) {
        redrawPhaseChartOnly();
      } else {
        liveTick().catch(() => {});
      }
    }
    if (panelName === "consumers") loadTariffAndDeviceSummary().catch(() => {});
    if (panelName === "history") loadHistoryChart().catch(() => {});
    if (panelName === "calendar") renderCalendar().catch(() => {});
  });
});

document.getElementById("historyDevice").addEventListener("change", () => loadHistoryChart().catch(() => {}));
document.querySelectorAll(".range-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".range-tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.historyRange = btn.dataset.range;
    loadHistoryChart().catch(() => {});
  });
});

updateClock();
setInterval(updateClock, 1000);

refreshAll().then(() => {
  loadHistoryChart().catch(() => {});
  liveTick().catch(() => {});
});
setInterval(refreshAll, REFRESH_MS);
setInterval(() => loadHistoryChart().catch(() => {}), HISTORY_REFRESH_MS);
restartLiveTimer();
