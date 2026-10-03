"""Wartung der Messwert-Tabelle.

Dünnt Rohmesswerte, die älter als THIN_AFTER_DAYS sind, auf einen Wert je
THIN_BUCKET_SECONDS aus. Pro Zeitfenster bleibt der jeweils letzte Messwert eines
Buckets erhalten; da `energy_wh_total` ein fortlaufender Zählerstand ist, bleiben
Verbrauchsberechnungen (Differenzen zweier Zählerstände) exakt, nur die zeitliche
Dichte sinkt.

Gearbeitet wird in kleinen Stundenfenstern mit je einem eigenen Commit, damit der
Poller und die API währenddessen nie lange auf die Datenbank warten müssen. Der
Fortschritt wird gespeichert, ein Abbruch (z.B. Neustart) ist daher unkritisch.
Beim Durchlaufen der Historie wird nebenbei die höchste Leistung in `peak_stats`
übernommen, bevor die Rohwerte verschwinden.
"""
import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta

from . import config, db

logger = logging.getLogger("energy.maintenance")

_stop = threading.Event()
_HOUR = timedelta(hours=1)


def request_stop() -> None:
    _stop.set()


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _thin_window(device_id: int, start: str, end: str) -> int:
    with db.db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT MAX(power_w) AS m FROM readings WHERE device_id = ? AND ts >= ? AND ts < ?",
            (device_id, start, end),
        )
        window_peak = cur.fetchone()["m"]
        if window_peak is not None:
            cur.execute(
                "INSERT OR IGNORE INTO peak_stats (device_id, peak_w, reset_at) VALUES (?, NULL, NULL)",
                (device_id,),
            )
            # Nur Werte aus Zeiträumen nach einem eventuellen Peak-Reset zählen.
            cur.execute(
                "UPDATE peak_stats SET peak_w = MAX(COALESCE(peak_w, 0), ?) "
                "WHERE device_id = ? AND (reset_at IS NULL OR reset_at < ?)",
                (window_peak, device_id, start),
            )

        cur.execute(
            """
            DELETE FROM readings
            WHERE device_id = ? AND ts >= ? AND ts < ?
              AND id NOT IN (
                  SELECT MAX(id) FROM readings
                  WHERE device_id = ? AND ts >= ? AND ts < ?
                  GROUP BY CAST(strftime('%s', ts) AS INTEGER) / ?
              )
            """,
            (device_id, start, end, device_id, start, end, config.THIN_BUCKET_SECONDS),
        )
        deleted = cur.rowcount
        cur.execute(
            "INSERT OR REPLACE INTO maintenance (key, value) VALUES (?, ?)",
            (f"thinned_until:{device_id}", end),
        )
    return deleted


def _thin_device(device_id: int, cutoff: datetime) -> int:
    key = f"thinned_until:{device_id}"
    with db.db_cursor() as cur:
        cur.execute("SELECT value FROM maintenance WHERE key = ?", (key,))
        row = cur.fetchone()
        if row is not None:
            start_iso = row["value"]
        else:
            cur.execute("SELECT MIN(ts) AS t FROM readings WHERE device_id = ?", (device_id,))
            start_iso = cur.fetchone()["t"]
    if start_iso is None:
        return 0

    window_start = datetime.fromisoformat(start_iso).replace(minute=0, second=0, microsecond=0)
    deleted_total = 0
    while window_start + _HOUR <= cutoff and not _stop.is_set():
        window_end = window_start + _HOUR
        deleted_total += _thin_window(device_id, _iso(window_start), _iso(window_end))
        window_start = window_end
        time.sleep(0.02)  # dem Poller/der API Luft lassen
    return deleted_total


def run_thinning_pass() -> int:
    cutoff = (datetime.now() - timedelta(days=config.THIN_AFTER_DAYS)).replace(
        minute=0, second=0, microsecond=0
    )
    with db.db_cursor() as cur:
        cur.execute("SELECT id FROM devices")
        device_ids = [row["id"] for row in cur.fetchall()]
    return sum(_thin_device(device_id, cutoff) for device_id in device_ids)


async def maintenance_loop() -> None:
    await asyncio.sleep(30)  # erst den Server hochfahren lassen
    while not _stop.is_set():
        try:
            started = time.monotonic()
            deleted = await asyncio.to_thread(run_thinning_pass)
            if deleted:
                logger.info(
                    "Wartung: %d alte Messwerte ausgedünnt (%.0f s)", deleted, time.monotonic() - started
                )
        except Exception:
            logger.exception("Fehler im Wartungslauf")
        await asyncio.sleep(3600)
