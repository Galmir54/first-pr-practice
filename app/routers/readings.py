import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import db, poller

router = APIRouter()

RANGE_TO_TIMEDELTA = {
    "day": timedelta(days=1),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
}

# Bucket-Auflösung je Zeitraum, damit die Antwort auch bei hoher Poll-Frequenz klein bleibt.
# "month" bucket-t auf Tagesebene, damit sich pro Tag ein sinnvoller kWh-Wert berechnen lässt.
BUCKET_FORMAT = {
    "day": "%Y-%m-%d %H:%M",
    "week": "%Y-%m-%d %H",
    "month": "%Y-%m-%d",
}


def _get_device(device_id: int) -> dict:
    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "Gerät nicht gefunden")
        return dict(row)


@router.get("/{device_id}/current")
def current_reading(device_id: int):
    _get_device(device_id)
    # Normalfall: letzter Poll-Wert aus dem Speicher (kein Datenbankzugriff nötig).
    cached = poller.latest.get(device_id)
    if cached is not None:
        return cached
    with db.db_cursor() as cur:
        cur.execute(
            "SELECT * FROM readings WHERE device_id = ? ORDER BY ts DESC LIMIT 1",
            (device_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


@router.get("/{device_id}/history")
def history(device_id: int, range: str = Query("day", pattern="^(day|week|month)$")):
    _get_device(device_id)
    since = (datetime.now() - RANGE_TO_TIMEDELTA[range]).isoformat()
    fmt = BUCKET_FORMAT[range]
    with db.db_cursor() as cur:
        cur.execute(
            f"""
            SELECT strftime('{fmt}', ts) AS bucket,
                   AVG(power_w) AS power_w,
                   MAX(energy_wh_total) AS energy_wh_total,
                   MIN(energy_wh_total) AS energy_wh_total_min
            FROM readings
            WHERE device_id = ? AND ts >= ?
            GROUP BY bucket
            ORDER BY bucket
            """,
            (device_id, since),
        )
        return [dict(r) for r in cur.fetchall()]


@router.get("/{device_id}/peak")
def peak(device_id: int):
    """Höchste gemessene Leistung seit Aufzeichnungsbeginn bzw. seit dem letzten Reset
    (`reset_at`) plus Zeitstempel der allerersten Messung (für die anteilige
    Grundpreis-Berechnung im Frontend). Kommt aus einer laufend mitgeführten
    Statistik-Tabelle, nicht aus einem Scan über alle Messwerte."""
    _get_device(device_id)
    return poller.get_peak_info(device_id)


@router.post("/{device_id}/peak/reset")
def peak_reset(device_id: int):
    _get_device(device_id)
    poller.reset_peak(device_id)
    return poller.get_peak_info(device_id)


CSV_HEADER = ["ts", "power_w", "energy_wh_total", "phase_a_w", "phase_b_w", "phase_c_w"]
CSV_CHUNK_ROWS = 5000


def _csv_rows(device_id: int, since: str | None):
    """Liefert den CSV-Export in Blöcken (Keyset-Paginierung über die id), damit nie
    die komplette Tabelle gleichzeitig im Arbeitsspeicher liegt."""
    buffer = io.StringIO()
    csv.writer(buffer).writerow(CSV_HEADER)
    yield buffer.getvalue()

    last_id = 0
    while True:
        with db.db_cursor() as cur:
            if since:
                cur.execute(
                    "SELECT id, ts, power_w, energy_wh_total, phase_a_w, phase_b_w, phase_c_w FROM readings "
                    "WHERE device_id = ? AND ts >= ? AND id > ? ORDER BY id LIMIT ?",
                    (device_id, since, last_id, CSV_CHUNK_ROWS),
                )
            else:
                cur.execute(
                    "SELECT id, ts, power_w, energy_wh_total, phase_a_w, phase_b_w, phase_c_w FROM readings "
                    "WHERE device_id = ? AND id > ? ORDER BY id LIMIT ?",
                    (device_id, last_id, CSV_CHUNK_ROWS),
                )
            rows = cur.fetchall()
        if not rows:
            return
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for row in rows:
            writer.writerow(
                [row["ts"], row["power_w"], row["energy_wh_total"], row["phase_a_w"], row["phase_b_w"], row["phase_c_w"]]
            )
        last_id = rows[-1]["id"]
        yield buffer.getvalue()


@router.get("/{device_id}/export.csv")
def export_csv(device_id: int, range: str = Query("all", pattern="^(day|week|month|all)$")):
    device = _get_device(device_id)
    since = None if range == "all" else (datetime.now() - RANGE_TO_TIMEDELTA[range]).isoformat()
    filename = f"{device['name'].replace(' ', '_')}_{range}.csv"
    return StreamingResponse(
        _csv_rows(device_id, since),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
