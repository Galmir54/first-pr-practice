"""Hintergrund-Task, der aktive Shelly-Geräte periodisch abfragt und Messwerte speichert."""
import asyncio
import json
import logging
from datetime import datetime

import httpx

from . import config, db, shelly_client

logger = logging.getLogger("energy.poller")


async def _poll_and_store(client: httpx.AsyncClient, device: dict) -> None:
    try:
        reading = await shelly_client.poll_device(client, device)
    except Exception:
        logger.warning(
            "Abfrage fehlgeschlagen für Gerät '%s' (%s)", device["name"], device["ip_address"], exc_info=True
        )
        return

    ts = datetime.now().isoformat()
    phase_meta = reading.get("phase_meta")
    with db.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO readings (device_id, ts, power_w, energy_wh_total, phase_a_w, phase_b_w, phase_c_w, phase_meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                device["id"],
                ts,
                reading["power_w"],
                reading["energy_wh_total"],
                reading["phase_a_w"],
                reading["phase_b_w"],
                reading["phase_c_w"],
                json.dumps(phase_meta) if phase_meta is not None else None,
            ),
        )


async def poll_once(client: httpx.AsyncClient) -> None:
    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM devices WHERE enabled = 1")
        devices = [dict(row) for row in cur.fetchall()]

    if not devices:
        return

    await asyncio.gather(*(_poll_and_store(client, device) for device in devices))


async def poller_loop() -> None:
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await poll_once(client)
            except Exception:
                logger.exception("Unerwarteter Fehler im Poller-Durchlauf")
            await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
