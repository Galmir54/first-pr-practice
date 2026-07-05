"""Client für die lokale Gen2/Gen3-RPC-API von Shelly-Geräten.

Unterstützte Gerätetypen:
- shelly_plug_s_gen3: Switch-Komponente (Switch.GetStatus)
- shelly_pro_3em:     EM/EMData-Komponenten (3-phasiger Hauptzähler)
"""
from typing import Any

import httpx

from . import config


class ShellyError(Exception):
    pass


async def _rpc_get(client: httpx.AsyncClient, ip: str, method: str, params: dict | None = None) -> dict:
    url = f"http://{ip}/rpc/{method}"
    try:
        resp = await client.get(url, params=params, timeout=config.HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise ShellyError(f"Anfrage an {ip} ({method}) fehlgeschlagen: {exc}") from exc


async def poll_plug_s(client: httpx.AsyncClient, ip: str) -> dict[str, Any]:
    data = await _rpc_get(client, ip, "Switch.GetStatus", {"id": 0})
    return {
        "power_w": data.get("apower"),
        "energy_wh_total": (data.get("aenergy") or {}).get("total"),
        "phase_a_w": None,
        "phase_b_w": None,
        "phase_c_w": None,
    }


async def poll_pro_3em(client: httpx.AsyncClient, ip: str) -> dict[str, Any]:
    em = await _rpc_get(client, ip, "EM.GetStatus", {"id": 0})
    emdata = await _rpc_get(client, ip, "EMData.GetStatus", {"id": 0})
    return {
        "power_w": em.get("total_act_power"),
        "energy_wh_total": emdata.get("total_act"),
        "phase_a_w": em.get("a_act_power"),
        "phase_b_w": em.get("b_act_power"),
        "phase_c_w": em.get("c_act_power"),
    }


POLLERS = {
    "shelly_plug_s_gen3": poll_plug_s,
    "shelly_pro_3em": poll_pro_3em,
}


async def poll_device(client: httpx.AsyncClient, device: dict) -> dict[str, Any]:
    fn = POLLERS.get(device["device_type"])
    if fn is None:
        raise ShellyError(f"Unbekannter device_type: {device['device_type']}")
    return await fn(client, device["ip_address"])
