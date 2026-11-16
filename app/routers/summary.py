"""Kostenberechnung: fasst Verbrauch & Kosten pro Zeitraum zusammen.

Gesamtverbrauch kommt vom Hauptzähler (Shelly Pro 3EM), nicht aus der Summe
der einzelnen Plugs, da nicht alle Verbraucher separat gemessen werden.
"""
from datetime import datetime

from fastapi import APIRouter, Query

from .. import db

router = APIRouter()


def _period_start(period: str) -> datetime:
    now = datetime.now()
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _energy_baseline(cur, device_id: int, start_iso: str) -> float | None:
    cur.execute(
        "SELECT energy_wh_total FROM readings "
        "WHERE device_id=? AND ts<=? AND energy_wh_total IS NOT NULL ORDER BY ts DESC LIMIT 1",
        (device_id, start_iso),
    )
    row = cur.fetchone()
    if row is not None:
        return row["energy_wh_total"]
    # Gerät wurde erst innerhalb des Zeitraums hinzugefügt: ab erster Messung zählen.
    cur.execute(
        "SELECT energy_wh_total FROM readings "
        "WHERE device_id=? AND ts>=? AND energy_wh_total IS NOT NULL ORDER BY ts ASC LIMIT 1",
        (device_id, start_iso),
    )
    row = cur.fetchone()
    return row["energy_wh_total"] if row else None


def _energy_latest(cur, device_id: int) -> float | None:
    cur.execute(
        "SELECT energy_wh_total FROM readings "
        "WHERE device_id=? AND energy_wh_total IS NOT NULL ORDER BY ts DESC LIMIT 1",
        (device_id,),
    )
    row = cur.fetchone()
    return row["energy_wh_total"] if row else None


def _consumption_kwh(cur, device_id: int, start_iso: str) -> float:
    baseline = _energy_baseline(cur, device_id, start_iso)
    latest = _energy_latest(cur, device_id)
    if baseline is None or latest is None:
        return 0.0
    return max(0.0, (latest - baseline) / 1000.0)


def _current_tariff(cur, utility_type: str = "strom") -> dict | None:
    cur.execute(
        "SELECT * FROM tariffs WHERE utility_type=? AND valid_from<=? ORDER BY valid_from DESC LIMIT 1",
        (utility_type, datetime.now().isoformat()),
    )
    row = cur.fetchone()
    return dict(row) if row else None


@router.get("")
def get_summary(period: str = Query("today", pattern="^(today|month)$")):
    start_iso = _period_start(period).isoformat()

    with db.db_cursor() as cur:
        tariff = _current_tariff(cur)
        arbeitspreis = tariff["arbeitspreis_ct_kwh"] if tariff else 0.0
        grundpreis = tariff["grundpreis_monat"] if tariff else 0.0
        tariff_name = tariff["name"] if tariff else None

        def cost(kwh: float) -> float:
            return round(kwh * arbeitspreis / 100.0, 2)

        cur.execute("SELECT * FROM devices WHERE enabled=1 ORDER BY id")
        devices = [dict(r) for r in cur.fetchall()]

        main_meter = next((d for d in devices if d["device_type"] == "shelly_pro_3em"), None)
        plugs = [d for d in devices if d["device_type"] == "shelly_plug_s_gen3"]

        plug_results = []
        tracked_kwh_sum = 0.0
        for p in plugs:
            kwh = _consumption_kwh(cur, p["id"], start_iso)
            tracked_kwh_sum += kwh
            plug_results.append(
                {"device_id": p["id"], "name": p["name"], "kwh": round(kwh, 3), "cost_eur": cost(kwh)}
            )

        main_result = None
        other_result = None
        if main_meter is not None:
            main_kwh = _consumption_kwh(cur, main_meter["id"], start_iso)
            main_result = {
                "device_id": main_meter["id"],
                "name": main_meter["name"],
                "kwh": round(main_kwh, 3),
                "cost_eur": cost(main_kwh),
            }
            other_kwh = max(0.0, main_kwh - tracked_kwh_sum)
            other_result = {"kwh": round(other_kwh, 3), "cost_eur": cost(other_kwh)}

        return {
            "period": period,
            "tariff": {"name": tariff_name, "grundpreis_monat": grundpreis, "arbeitspreis_ct_kwh": arbeitspreis},
            "main_meter": main_result,
            "devices": plug_results,
            "other": other_result,
            "grundpreis_eur": grundpreis if period == "month" else None,
        }
