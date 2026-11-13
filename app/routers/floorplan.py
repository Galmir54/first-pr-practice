import asyncio
import json

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db import db_cursor

router = APIRouter()

ROOMS_KEY = "floorplan.rooms"
THERMOSTAT_ROOMS_KEY = "floorplan.thermostat_rooms"


class Room(BaseModel):
    # Position im Modell in Metern, gleiche Koordinaten wie die 3D-Szene (x = rechts, z = nach unten
    # in der Draufsicht, Ursprung = Mitte der Wohnung).
    x: float
    z: float
    name: str = Field(default="", max_length=40)


class RoomsIn(BaseModel):
    rooms: list[Room] = Field(max_length=60)
    # Feste Zuordnung Thermostat-ID -> Raumname. Wird gebraucht, wenn der Name in der Danfoss-Cloud
    # nicht stimmt (z.B. zwei Thermostate heißen gleich). Fehlt das Feld, bleibt die Zuordnung wie sie ist.
    thermostat_rooms: dict[str, str] | None = Field(default=None, max_length=60)


def _load(key: str, default):
    with db_cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return default


def _save(key: str, value) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )


def _get() -> dict:
    return {"rooms": _load(ROOMS_KEY, []), "thermostat_rooms": _load(THERMOSTAT_ROOMS_KEY, {})}


def _put(rooms: list[dict], thermostat_rooms: dict[str, str] | None) -> dict:
    _save(ROOMS_KEY, rooms)
    if thermostat_rooms is not None:
        _save(THERMOSTAT_ROOMS_KEY, {k: v.strip() for k, v in thermostat_rooms.items() if v.strip()})
    return _get()


@router.get("/rooms")
async def get_rooms():
    return await asyncio.to_thread(_get)


@router.put("/rooms")
async def put_rooms(body: RoomsIn):
    rooms = [{"x": round(r.x, 2), "z": round(r.z, 2), "name": r.name.strip()} for r in body.rooms]
    return await asyncio.to_thread(_put, rooms, body.thermostat_rooms)
