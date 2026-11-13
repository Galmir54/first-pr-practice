import asyncio
import json

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db import db_cursor

router = APIRouter()

ROOMS_KEY = "floorplan.rooms"


class Room(BaseModel):
    # Position im Modell in Metern, gleiche Koordinaten wie die 3D-Szene (x = rechts, z = nach unten
    # in der Draufsicht, Ursprung = Mitte der Wohnung).
    x: float
    z: float
    name: str = Field(default="", max_length=40)


class RoomsIn(BaseModel):
    rooms: list[Room] = Field(max_length=60)


def _load() -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key = ?", (ROOMS_KEY,))
        row = cur.fetchone()
    if not row:
        return []
    try:
        return json.loads(row["value"])
    except ValueError:
        return []


def _save(rooms: list[dict]) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (ROOMS_KEY, json.dumps(rooms, ensure_ascii=False)),
        )


@router.get("/rooms")
async def get_rooms():
    return {"rooms": await asyncio.to_thread(_load)}


@router.put("/rooms")
async def put_rooms(body: RoomsIn):
    rooms = [{"x": round(r.x, 2), "z": round(r.z, 2), "name": r.name.strip()} for r in body.rooms]
    await asyncio.to_thread(_save, rooms)
    return {"rooms": rooms}
