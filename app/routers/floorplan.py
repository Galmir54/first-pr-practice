import asyncio
import json
import re
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import db_cursor

router = APIRouter()

ROOMS_KEY = "floorplan.rooms"
THERMOSTAT_ROOMS_KEY = "floorplan.thermostat_rooms"
OPENINGS_KEY = "floorplan.openings"
OPENING_STATE_KEY = "floorplan.opening_state"

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


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


class Opening(BaseModel):
    """Eine Tür oder ein Fenster. Position/Maße in Metern wie die 3D-Szene."""

    id: str = Field(pattern=ID_PATTERN.pattern)
    kind: str = Field(pattern="^(door|window)$")
    x: float
    z: float
    width: float = Field(gt=0.2, lt=6)
    # Richtung der Wand: 0 = entlang x, 1 = entlang z (in der Draufsicht senkrecht)
    along: int = Field(ge=0, le=1)
    thick: float = Field(default=0.1, gt=0, lt=1)
    sill: float = Field(default=0, ge=0, lt=3)  # Brüstungshöhe (Tür: 0)
    head: float = Field(default=2.1, gt=0.3, lt=3.5)  # Oberkante der Öffnung
    hinge: int = Field(default=1, ge=-1, le=1)  # auf welcher Seite die Bänder sitzen
    swing: int = Field(default=1, ge=-1, le=1)  # in welche Richtung der Flügel aufschwingt
    name: str = Field(default="", max_length=40)


class OpeningsIn(BaseModel):
    openings: list[Opening] = Field(max_length=120)


class OpeningStateIn(BaseModel):
    open: bool


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


# --- Türen und Fenster -----------------------------------------------------------------------
# Das Layout (wo sitzt was) und der Zustand (offen/zu) liegen getrennt: der Zustand ändert sich
# ständig (später durch Tür-/Fensterkontakte), das Layout nur beim Einrichten.


def _openings_get() -> dict:
    layout = _load(OPENINGS_KEY, [])
    state = _load(OPENING_STATE_KEY, {})
    for item in layout:
        s = state.get(item["id"], {})
        item["open"] = bool(s.get("open", False))
        item["changed_at"] = s.get("changed_at")
    return {"openings": layout}


def _openings_put(items: list[dict]) -> dict:
    _save(OPENINGS_KEY, items)
    ids = {i["id"] for i in items}
    state = _load(OPENING_STATE_KEY, {})
    _save(OPENING_STATE_KEY, {k: v for k, v in state.items() if k in ids})
    return _openings_get()


def _opening_state_put(opening_id: str, is_open: bool) -> dict:
    if not any(i["id"] == opening_id for i in _load(OPENINGS_KEY, [])):
        raise HTTPException(404, "Unbekannte Tür oder unbekanntes Fenster")
    state = _load(OPENING_STATE_KEY, {})
    prev = state.get(opening_id, {})
    if bool(prev.get("open", False)) != is_open or "changed_at" not in prev:
        state[opening_id] = {"open": is_open, "changed_at": int(time.time())}
        _save(OPENING_STATE_KEY, state)
    return {"id": opening_id, "open": is_open}


@router.get("/openings")
async def get_openings():
    return await asyncio.to_thread(_openings_get)


@router.put("/openings")
async def put_openings(body: OpeningsIn):
    ids = [o.id for o in body.openings]
    if len(ids) != len(set(ids)):
        raise HTTPException(400, "IDs müssen eindeutig sein")
    items = [
        {**o.model_dump(), "x": round(o.x, 2), "z": round(o.z, 2), "width": round(o.width, 2), "name": o.name.strip()}
        for o in body.openings
    ]
    return await asyncio.to_thread(_openings_put, items)


@router.put("/openings/{opening_id}/state")
async def put_opening_state(opening_id: str, body: OpeningStateIn):
    """Setzt offen/zu. Wird vom Grundriss (Antippen) und später von Tür-/Fensterkontakten genutzt."""
    if not ID_PATTERN.match(opening_id):
        raise HTTPException(400, "Ungültige ID")
    return await asyncio.to_thread(_opening_state_put, opening_id, body.open)
