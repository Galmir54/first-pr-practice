import asyncio
import json
import re
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import poller
from ..db import db_cursor

router = APIRouter()

ROOMS_KEY = "floorplan.rooms"
THERMOSTAT_ROOMS_KEY = "floorplan.thermostat_rooms"
OPENINGS_KEY = "floorplan.openings"
OPENING_STATE_KEY = "floorplan.opening_state"
CABINETS_KEY = "floorplan.cabinets"
TVS_KEY = "floorplan.tvs"

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
    kind: str = Field(pattern="^(door|window|cabinet)$")
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
    # nur für Schranktüren (kind "cabinet"): Aussehen der Front
    style: str = Field(default="white", pattern="^(white|mirror|oak)$")


class Cabinet(BaseModel):
    """Ein Schrank: feste Teile (Korpus, Böden, Schubladen). Die Türen sind eigene Einträge
    (kind "cabinet") in den Türen/Fenstern, damit jede Tür ihren eigenen Kontakt hat."""

    id: str = Field(pattern=ID_PATTERN.pattern)
    name: str = Field(default="", max_length=40)
    x_front: float  # Vorderkante (zum Raum hin, in +x)
    x_back: float  # Rückwand (an der Wand)
    z_min: float
    z_max: float
    height: float = Field(gt=0.3, lt=3.5)
    dividers: list[float] = Field(default_factory=list, max_length=12)  # z-Lage der Trennwände
    drawers: list["DrawerBlock"] = Field(default_factory=list, max_length=6)


class DrawerBlock(BaseModel):
    z_min: float
    z_max: float
    count: int = Field(default=3, ge=1, le=6)
    height: float = Field(default=0.78, gt=0.1, lt=2)


Cabinet.model_rebuild()


class CabinetsIn(BaseModel):
    cabinets: list[Cabinet] = Field(max_length=10)


class Tv(BaseModel):
    """Fernseher auf einem Unterschrank. Ob er an ist, wird aus der Leistung einer Shelly-Steckdose
    abgeleitet (`device_id`): ab `on_watts` gilt er als an."""

    id: str = Field(pattern=ID_PATTERN.pattern)
    name: str = Field(default="Fernseher", max_length=40)
    x_front: float  # Vorderkante des Unterschranks (zum Raum hin, in -x)
    x_back: float  # Rückseite an der Wand
    z_min: float
    z_max: float
    base: float = Field(default=0.18, ge=0, lt=1)  # Unterkante des Korpus (Sockel darunter)
    top: float = Field(default=0.71, gt=0.2, lt=1.5)  # Oberkante des Unterschranks
    door_split: float | None = None  # z-Lage, ab der rechts Schubladen statt Türen sitzen
    tv_z: float
    tv_width: float = Field(default=1.0, gt=0.3, lt=3)
    tv_height: float = Field(default=0.57, gt=0.2, lt=2)
    tv_gap: float = Field(default=0.08, ge=0, lt=0.5)  # Abstand TV-Unterkante zum Schrank
    soundbar: bool = True
    device_id: int | None = None
    on_watts: float = Field(default=40, gt=0, lt=5000)


class TvsIn(BaseModel):
    tvs: list[Tv] = Field(max_length=6)


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


@router.get("/cabinets")
async def get_cabinets():
    return {"cabinets": await asyncio.to_thread(_load, CABINETS_KEY, [])}


@router.put("/cabinets")
async def put_cabinets(body: CabinetsIn):
    items = [c.model_dump() for c in body.cabinets]
    await asyncio.to_thread(_save, CABINETS_KEY, items)
    return {"cabinets": items}


def _tv_state(tv: dict) -> dict:
    """Ergänzt `on` (True/False, None = unbekannt) und `power_w` aus dem letzten Messwert."""
    out = dict(tv)
    out["on"] = None
    out["power_w"] = None
    device_id = tv.get("device_id")
    reading = poller.latest.get(device_id) if device_id is not None else None
    if reading and reading.get("power_w") is not None:
        out["power_w"] = round(float(reading["power_w"]), 1)
        out["on"] = out["power_w"] >= float(tv.get("on_watts", 40))
    return out


@router.get("/tvs")
def get_tvs():
    return {"tvs": [_tv_state(t) for t in _load(TVS_KEY, [])]}


@router.put("/tvs")
async def put_tvs(body: TvsIn):
    items = [t.model_dump() for t in body.tvs]
    await asyncio.to_thread(_save, TVS_KEY, items)
    return {"tvs": [_tv_state(t) for t in items]}


@router.put("/openings/{opening_id}/state")
async def put_opening_state(opening_id: str, body: OpeningStateIn):
    """Setzt offen/zu. Wird vom Grundriss (Antippen) und später von Tür-/Fensterkontakten genutzt."""
    if not ID_PATTERN.match(opening_id):
        raise HTTPException(400, "Ungültige ID")
    return await asyncio.to_thread(_opening_state_put, opening_id, body.open)
