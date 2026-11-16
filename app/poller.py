"""Hintergrund-Task, der aktive Shelly-Geräte periodisch abfragt.

- Der jeweils letzte Messwert liegt im Speicher (`latest`), damit die Live-Ansicht
  ohne Datenbankzugriff bedient werden kann.
- In die Datenbank wird nur alle STORE_INTERVAL_SECONDS ein Messwert geschrieben.
- Die Spitzenleistung (Peak) wird bei jedem Poll mitgeführt, nicht aus der Historie
  berechnet.
- Alle Datenbankzugriffe laufen in Threads, damit der Event-Loop nie blockiert.
- Nicht erreichbare Geräte werden mit wachsender Wartezeit abgefragt, damit ein
  ausgefallenes Gerät die Abfrage der anderen nicht ausbremst.
"""
import asyncio
import json
import logging
import time
from datetime import datetime

import httpx

from . import config, db, shelly_client

logger = logging.getLogger("energy.poller")

# Letzter Messwert je Gerät (Form entspricht einer Zeile der Tabelle `readings`).
latest: dict[int, dict] = {}

_last_store: dict[int, float] = {}
_peak: dict[int, float] = {}
_fail_count: dict[int, int] = {}
_next_attempt: dict[int, float] = {}


# --- Peak ---

def _load_peaks() -> None:
    with db.db_cursor() as cur:
        cur.execute("SELECT device_id, peak_w FROM peak_stats WHERE peak_w IS NOT NULL")
        for row in cur.fetchall():
            _peak[row["device_id"]] = row["peak_w"]


def get_peak_info(device_id: int) -> dict:
    with db.db_cursor() as cur:
        cur.execute("SELECT peak_w, reset_at FROM peak_stats WHERE device_id = ?", (device_id,))
        peak_row = cur.fetchone()
        cur.execute("SELECT MIN(ts) AS first_ts FROM readings WHERE device_id = ?", (device_id,))
        first_row = cur.fetchone()
    return {
        "peak_w": peak_row["peak_w"] if peak_row else None,
        "reset_at": peak_row["reset_at"] if peak_row else None,
        "first_ts": first_row["first_ts"] if first_row else None,
    }


def reset_peak(device_id: int) -> None:
    current = latest.get(device_id)
    value = current["power_w"] if current and current.get("power_w") is not None else 0.0
    with db.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO peak_stats (device_id, peak_w, reset_at) VALUES (?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET peak_w = excluded.peak_w, reset_at = excluded.reset_at",
            (device_id, value, datetime.now().isoformat()),
        )
    _peak[device_id] = value


# --- Abfrage + Speichern ---

def _persist(device_id: int, row: dict, store_row: bool) -> None:
    power = row["power_w"]
    with db.db_cursor(commit=True) as cur:
        if store_row:
            cur.execute(
                "INSERT INTO readings (device_id, ts, power_w, energy_wh_total, phase_a_w, phase_b_w, phase_c_w, phase_meta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    device_id,
                    row["ts"],
                    power,
                    row["energy_wh_total"],
                    row["phase_a_w"],
                    row["phase_b_w"],
                    row["phase_c_w"],
                    row["phase_meta"],
                ),
            )
        known_peak = _peak.get(device_id)
        if power is not None and (known_peak is None or power > known_peak):
            # MAX() im SQL, damit ein zwischenzeitlich durch die Wartung angehobener
            # Wert nie von einem niedrigeren überschrieben wird.
            cur.execute(
                "INSERT INTO peak_stats (device_id, peak_w, reset_at) VALUES (?, ?, NULL) "
                "ON CONFLICT(device_id) DO UPDATE SET peak_w = MAX(COALESCE(peak_w, 0), excluded.peak_w)",
                (device_id, power),
            )
            _peak[device_id] = power


async def _poll_and_store(client: httpx.AsyncClient, device: dict) -> None:
    device_id = device["id"]
    now = time.monotonic()
    if now < _next_attempt.get(device_id, 0.0):
        return

    try:
        reading = await shelly_client.poll_device(client, device)
    except Exception as exc:
        fails = _fail_count.get(device_id, 0) + 1
        _fail_count[device_id] = fails
        _next_attempt[device_id] = now + min(60.0, 5.0 * fails)
        if fails == 1:
            logger.warning("Gerät '%s' (%s) nicht erreichbar: %s", device["name"], device["ip_address"], exc)
        return

    if _fail_count.get(device_id):
        logger.info("Gerät '%s' (%s) ist wieder erreichbar", device["name"], device["ip_address"])
        _fail_count[device_id] = 0
        _next_attempt.pop(device_id, None)

    phase_meta = reading.get("phase_meta")
    row = {
        "device_id": device_id,
        "ts": datetime.now().isoformat(),
        "power_w": reading["power_w"],
        "energy_wh_total": reading["energy_wh_total"],
        "phase_a_w": reading["phase_a_w"],
        "phase_b_w": reading["phase_b_w"],
        "phase_c_w": reading["phase_c_w"],
        "phase_meta": json.dumps(phase_meta) if phase_meta is not None else None,
    }
    latest[device_id] = row

    store_row = now - _last_store.get(device_id, float("-inf")) >= config.STORE_INTERVAL_SECONDS
    if store_row:
        _last_store[device_id] = now
    await asyncio.to_thread(_persist, device_id, row, store_row)


def _load_devices() -> list[dict]:
    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM devices WHERE enabled = 1")
        return [dict(row) for row in cur.fetchall()]


async def poll_once(client: httpx.AsyncClient) -> None:
    devices = await asyncio.to_thread(_load_devices)
    if not devices:
        return
    await asyncio.gather(*(_poll_and_store(client, device) for device in devices))


async def poller_loop() -> None:
    await asyncio.to_thread(_load_peaks)
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await poll_once(client)
            except Exception:
                logger.exception("Unerwarteter Fehler im Poller-Durchlauf")
            await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
