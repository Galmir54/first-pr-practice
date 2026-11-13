import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import heating, presence

router = APIRouter()


class HeatingConfigIn(BaseModel):
    enabled: bool
    ally_key: str | None = None
    ally_secret: str | None = None  # leer lassen = gespeichertes Secret behalten
    phone_ips: list[str] = []
    away_temp: float = Field(17.0, ge=5.0, le=30.0)
    away_delay_min: int = Field(15, ge=1, le=240)


class HeatingActionIn(BaseModel):
    action: str


@router.get("/config")
def get_config():
    return heating.public_config()


@router.put("/config")
async def set_config(body: HeatingConfigIn):
    ips = [ip.strip() for ip in body.phone_ips if ip.strip()]
    bad = [ip for ip in ips if not presence.valid_ip(ip)]
    if bad:
        raise HTTPException(400, f"Keine gültige IP-Adresse: {', '.join(bad)}")
    # Ally-Thermostate kennen nur halbe Grad.
    away_temp = round(body.away_temp * 2) / 2
    await asyncio.to_thread(
        heating.save_config, body.enabled, body.ally_key, body.ally_secret, ips, away_temp, body.away_delay_min
    )
    return heating.public_config()


@router.get("/status")
async def status():
    return await heating.status()


@router.post("/action")
async def action(body: HeatingActionIn):
    """Zum Ausprobieren: sofort absenken (`away`) oder zurücksetzen (`home`)."""
    if body.action not in ("away", "home"):
        raise HTTPException(400, "action muss 'away' oder 'home' sein")
    try:
        errors = await heating.manual_action(body.action)
    except Exception as exc:
        raise HTTPException(502, str(exc))
    return {"ok": not errors, "errors": errors}
