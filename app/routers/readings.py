import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .. import db

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
def peak(device_id: int, since: str | None = Query(None)):
    """Höchste je gemessene Leistung (optional ab einem Reset-Zeitpunkt) plus
    Zeitstempel der allerersten Messung überhaupt (unabhängig von `since`),
    letzteres dient dem Frontend zur anteiligen Grundpreis-Berechnung."""
    _get_device(device_id)
    with db.db_cursor() as cur:
        if since:
            cur.execute(
                "SELECT MAX(power_w) AS peak_w FROM readings WHERE device_id = ? AND ts >= ?",
                (device_id, since),
            )
        else:
            cur.execute("SELECT MAX(power_w) AS peak_w FROM readings WHERE device_id = ?", (device_id,))
        peak_row = cur.fetchone()

        cur.execute("SELECT MIN(ts) AS first_ts FROM readings WHERE device_id = ?", (device_id,))
        first_row = cur.fetchone()

        return {
            "peak_w": peak_row["peak_w"] if peak_row else None,
            "first_ts": first_row["first_ts"] if first_row else None,
        }


@router.get("/{device_id}/export.csv")
def export_csv(device_id: int, range: str = Query("all", pattern="^(day|week|month|all)$")):
    device = _get_device(device_id)
    with db.db_cursor() as cur:
        if range == "all":
            cur.execute(
                "SELECT ts, power_w, energy_wh_total, phase_a_w, phase_b_w, phase_c_w "
                "FROM readings WHERE device_id = ? ORDER BY ts",
                (device_id,),
            )
        else:
            since = (datetime.now() - RANGE_TO_TIMEDELTA[range]).isoformat()
            cur.execute(
                "SELECT ts, power_w, energy_wh_total, phase_a_w, phase_b_w, phase_c_w "
                "FROM readings WHERE device_id = ? AND ts >= ? ORDER BY ts",
                (device_id, since),
            )
        rows = cur.fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ts", "power_w", "energy_wh_total", "phase_a_w", "phase_b_w", "phase_c_w"])
    for row in rows:
        writer.writerow(
            [row["ts"], row["power_w"], row["energy_wh_total"], row["phase_a_w"], row["phase_b_w"], row["phase_c_w"]]
        )

    filename = f"{device['name'].replace(' ', '_')}_{range}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
