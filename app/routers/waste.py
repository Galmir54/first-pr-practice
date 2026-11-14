import asyncio
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import waste

router = APIRouter()


class WasteConfigIn(BaseModel):
    district_id: int
    city_id: int


class WasteAckIn(BaseModel):
    date: str


@router.get("/options")
async def options():
    try:
        return await waste.fetch_options()
    except Exception as exc:
        raise HTTPException(502, f"Orte konnten nicht vom Landkreis geladen werden: {exc}")


@router.get("/config")
def get_config():
    return waste.get_config()


@router.put("/config")
async def set_config(body: WasteConfigIn):
    try:
        options = await waste.fetch_options()
    except Exception as exc:
        raise HTTPException(502, f"Orte konnten nicht vom Landkreis geladen werden: {exc}")

    city = next((c for c in options["cities"] if c["id"] == body.city_id and c["district_id"] == body.district_id), None)
    district = next((d for d in options["districts"] if d["id"] == body.district_id), None)
    if city is None or district is None:
        raise HTTPException(400, "Unbekannte Kombination aus Abfuhrbezirk und Ort")

    await asyncio.to_thread(waste.save_config, body.district_id, body.city_id, district["name"], city["name"])
    synced = await waste.sync_once()
    return {**await asyncio.to_thread(waste.get_config), "synced": synced}


@router.get("/reminder")
def reminder():
    """Fällige Erinnerung (`due`, sonst null) und nächster Abfuhrtermin (`next`).
    Das Dashboard fragt das einmal pro Minute ab."""
    cfg = waste.get_config()
    return {"configured": cfg["configured"], "city_name": cfg["city_name"], **waste.compute_reminder(datetime.now())}


@router.get("/upcoming")
def upcoming(days: int = 30):
    today = date.today()
    return waste.grouped_dates(today, today + timedelta(days=max(1, min(days, 400))))


@router.post("/ack")
def acknowledge(body: WasteAckIn):
    try:
        waste.ack(body.date)
    except ValueError:
        raise HTTPException(400, "Ungültiges Datum, erwartet wird JJJJ-MM-TT")
    return {"ok": True}
