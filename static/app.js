const REFRESH_MS = 7000;
const HISTORY_REFRESH_MS = 60000;

const state = {
  devices: [],
  currentByDevice: {},
  tariff: null,
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

refreshAll();
setInterval(refreshAll, REFRESH_MS);
