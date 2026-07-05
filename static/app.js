const REFRESH_MS = 7000;
const HISTORY_REFRESH_MS = 60000;

const state = {
  devices: [],
  currentByDevice: {},
  tariff: null,
  historyRange: "day",
};

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

function isStale(reading) {
  if (!reading || !reading.ts) return true;
  const ts = new Date(reading.ts).getTime();
  return Date.now() - ts > REFRESH_MS * 4;
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
  ctx.strokeStyle = "#37c2a3";
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

  ctx.strokeStyle = "#2a3a4a";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(padLeft, 20);
  ctx.lineTo(padLeft, plotH + 20);
  ctx.lineTo(w - 10, plotH + 20);
  ctx.stroke();

  ctx.fillStyle = "#93a5b5";
  ctx.font = "22px sans-serif";
  ctx.fillText(Math.round(max).toString(), 4, 34);
  ctx.fillText(Math.round(min).toString(), 4, plotH + 20);

  if (mode === "bar") {
    const slot = plotW / points.length;
    const barW = slot * 0.65;
    points.forEach((p, i) => {
      if (p.value === null || p.value === undefined) return;
      const x = padLeft + i * slot + (slot - barW) / 2;
      const barH = ((p.value - min) / range) * plotH;
      ctx.fillStyle = "#37c2a3";
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
    ctx.strokeStyle = "#37c2a3";
    ctx.lineWidth = 4;
    ctx.stroke();
  }

  ctx.fillStyle = "#93a5b5";
  ctx.font = "20px sans-serif";
  const labelIdxs = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  [...new Set(labelIdxs)].forEach((idx) => {
    const p = points[idx];
    if (!p) return;
    const slotCenter =
      mode === "bar" ? padLeft + idx * (plotW / points.length) + plotW / points.length / 2 : padLeft + (idx / (points.length - 1 || 1)) * plotW;
    ctx.fillText(p.label, Math.min(Math.max(slotCenter - 30, 0), w - 60), h - 6);
  });
}

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

async function loadOverview() {
  const [today, month] = await Promise.all([
    api("/api/summary?period=today"),
    api("/api/summary?period=month"),
  ]);
  state.tariff = today.tariff;

  const mainPowerW = state.currentByDevice[today.main_meter?.device_id]?.power_w;

  const overview = document.getElementById("overview");
  overview.innerHTML = "";

  overview.appendChild(
    statCard("Aktuelle Gesamtleistung", fmtW(mainPowerW), today.main_meter ? "" : "Kein Hauptzähler eingerichtet")
  );
  overview.appendChild(
    statCard("Heute", fmtKwh(today.main_meter?.kwh), `${fmtEur(today.main_meter?.cost_eur)} · Sonstige: ${fmtKwh(today.other?.kwh)}`)
  );
  overview.appendChild(
    statCard(
      "Diesen Monat",
      fmtKwh(month.main_meter?.kwh),
      `${fmtEur(month.main_meter?.cost_eur)} + ${fmtEur(month.grundpreis_eur)} Grundpreis`
    )
  );

  const totalMonthCost = (month.main_meter?.cost_eur || 0) + (month.grundpreis_eur || 0);
  overview.appendChild(statCard("Monatskosten gesamt", fmtEur(totalMonthCost), `Tarif: ${today.tariff.arbeitspreis_ct_kwh} ct/kWh`));

  renderDeviceCards(today);
}

function statCard(label, value, sub) {
  const div = document.createElement("div");
  div.className = "stat";
  div.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub || ""}</div>`;
  return div;
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
  await loadOverview();
  populateHistoryDeviceSelect();
}

// --- Settings modal ---

function openSettings() {
  document.getElementById("settingsModal").classList.remove("hidden");
  renderDeviceList();
  if (state.tariff) {
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
  const grundpreis_monat = parseFloat(document.getElementById("tariffGrundpreis").value);
  const arbeitspreis_ct_kwh = parseFloat(document.getElementById("tariffArbeitspreis").value);
  if (Number.isNaN(grundpreis_monat) || Number.isNaN(arbeitspreis_ct_kwh)) {
    alert("Bitte gültige Zahlen für den Tarif angeben.");
    return;
  }
  await api("/api/tariff", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ grundpreis_monat, arbeitspreis_ct_kwh }),
  });
  await loadOverview();
}

document.getElementById("settingsBtn").addEventListener("click", openSettings);
document.getElementById("closeSettings").addEventListener("click", closeSettings);
document.getElementById("addDeviceBtn").addEventListener("click", addDevice);
document.getElementById("saveTariffBtn").addEventListener("click", saveTariff);

document.getElementById("historyDevice").addEventListener("change", () => loadHistoryChart().catch(() => {}));
document.querySelectorAll(".range-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".range-tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.historyRange = btn.dataset.range;
    loadHistoryChart().catch(() => {});
  });
});

refreshAll().then(() => loadHistoryChart().catch(() => {}));
setInterval(refreshAll, REFRESH_MS);
setInterval(() => loadHistoryChart().catch(() => {}), HISTORY_REFRESH_MS);
