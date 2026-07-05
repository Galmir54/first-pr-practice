from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

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
                   MAX(energy_wh_total) AS energy_wh_total
            FROM readings
            WHERE device_id = ? AND ts >= ?
            GROUP BY bucket
            ORDER BY bucket
            """,
            (device_id, since),
        )
        return [dict(r) for r in cur.fetchall()]
