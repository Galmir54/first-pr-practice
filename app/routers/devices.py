from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

router = APIRouter()

VALID_DEVICE_TYPES = {"shelly_pro_3em", "shelly_plug_s_gen3"}


class DeviceIn(BaseModel):
    name: str
    device_type: str
    ip_address: str
    utility_type: str = "strom"
    enabled: bool = True


class DeviceOut(DeviceIn):
    id: int
    created_at: str


def _validate_device_type(device_type: str) -> None:
    if device_type not in VALID_DEVICE_TYPES:
        raise HTTPException(400, f"Unbekannter device_type: {device_type}")


@router.get("", response_model=list[DeviceOut])
def list_devices():
    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM devices ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


@router.post("", response_model=DeviceOut, status_code=201)
def create_device(device: DeviceIn):
    _validate_device_type(device.device_type)
    with db.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO devices (name, utility_type, device_type, ip_address, enabled) VALUES (?, ?, ?, ?, ?)",
            (device.name, device.utility_type, device.device_type, device.ip_address, int(device.enabled)),
        )
        new_id = cur.lastrowid
        cur.execute("SELECT * FROM devices WHERE id = ?", (new_id,))
        return dict(cur.fetchone())


@router.put("/{device_id}", response_model=DeviceOut)
def update_device(device_id: int, device: DeviceIn):
    _validate_device_type(device.device_type)
    with db.db_cursor(commit=True) as cur:
        cur.execute("SELECT id FROM devices WHERE id = ?", (device_id,))
        if cur.fetchone() is None:
            raise HTTPException(404, "Gerät nicht gefunden")
        cur.execute(
            "UPDATE devices SET name=?, utility_type=?, device_type=?, ip_address=?, enabled=? WHERE id=?",
            (device.name, device.utility_type, device.device_type, device.ip_address, int(device.enabled), device_id),
        )
        cur.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
        return dict(cur.fetchone())


@router.delete("/{device_id}", status_code=204)
def delete_device(device_id: int):
    with db.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    return None
