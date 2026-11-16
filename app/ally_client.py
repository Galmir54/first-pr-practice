"""Client für die Danfoss Ally Cloud-API (api.danfoss.com).

Anmeldung per OAuth2 "client credentials": API-Schlüssel und Secret aus dem Danfoss
Developer Portal gehen als HTTP-Basic-Auth an /oauth2/token, zurück kommt ein
Bearer-Token mit Laufzeit (`expires_in`).

Format der Antworten (so verwendet es auch die Home-Assistant-Bibliothek pydanfossally,
die offizielle Doku war nicht erreichbar):
- GET /ally/devices -> {"result": [{"id", "name", "online", "device_type", "status":
  [{"code": ..., "value": ...}, ...]}, ...]}
- Temperaturen sind Zehntelgrad (215 = 21,5 °C), sowohl beim Lesen als auch beim Setzen.
- POST /ally/devices/{id}/commands mit {"commands": [{"code": ..., "value": ...}]}
"""
import base64
import time
from datetime import datetime

import httpx

API_HOST = "https://api.danfoss.com"
TOKEN_URL = f"{API_HOST}/oauth2/token"
TIMEOUT_SECONDS = 15

# Codes, die eine Solltemperatur (Zehntelgrad) enthalten.
SETPOINT_CODES = (
    "manual_mode_fast",
    "at_home_setting",
    "leaving_home_setting",
    "pause_setting",
    "holiday_setting",
    "temp_set",
)


class AllyError(Exception):
    pass


class AllyClient:
    def __init__(self, key: str, secret: str):
        self._key = key
        self._secret = secret
        self._token: str | None = None
        self._token_valid_until = 0.0

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.monotonic() < self._token_valid_until:
            return self._token
        basic = base64.b64encode(f"{self._key}:{self._secret}".encode()).decode()
        resp = await client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}", "Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code in (400, 401, 403):
            raise AllyError("Anmeldung bei Danfoss abgelehnt – API-Schlüssel/Secret prüfen")
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_valid_until = time.monotonic() + max(60, int(data.get("expires_in", 3600)) - 60)
        return self._token

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        async with httpx.AsyncClient() as client:
            token = await self._get_token(client)
            resp = await client.request(
                method,
                f"{API_HOST}{path}",
                json=json,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=TIMEOUT_SECONDS,
            )
            if resp.status_code == 401:
                # Token abgelaufen/widerrufen: einmal neu anmelden.
                self._token = None
                token = await self._get_token(client)
                resp = await client.request(
                    method,
                    f"{API_HOST}{path}",
                    json=json,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=TIMEOUT_SECONDS,
                )
            if resp.status_code == 429:
                raise AllyError("Danfoss-API: zu viele Anfragen, später erneut")
            resp.raise_for_status()
            return resp.json()

    async def list_devices(self) -> list[dict]:
        data = await self._request("GET", "/ally/devices")
        if "result" not in data:
            raise AllyError(f"Unerwartete Antwort der Danfoss-API: {str(data)[:200]}")
        return data["result"]

    async def send_commands(self, device_id: str, commands: list[tuple[str, object]]) -> None:
        body = {"commands": [{"code": code, "value": value} for code, value in commands]}
        data = await self._request("POST", f"/ally/devices/{device_id}/commands", json=body)
        if data.get("result") is False:
            raise AllyError(f"Befehl wurde abgelehnt: {str(data)[:200]}")


def status_map(device: dict) -> dict:
    return {s.get("code"): s.get("value") for s in device.get("status") or [] if isinstance(s, dict)}


def tenths_to_c(value) -> float | None:
    try:
        return float(value) / 10
    except (TypeError, ValueError):
        return None


def is_thermostat(device: dict) -> bool:
    status = status_map(device)
    return any(code in status for code in SETPOINT_CODES)


def describe(device: dict) -> dict:
    """Die für das Dashboard wichtigen Werte eines Thermostats."""
    status = status_map(device)
    mode = status.get("mode")
    if mode == "manual" and "manual_mode_fast" in status:
        setpoint = tenths_to_c(status["manual_mode_fast"])
    elif mode == "leaving_home" and "leaving_home_setting" in status:
        setpoint = tenths_to_c(status["leaving_home_setting"])
    elif "temp_set" in status:
        setpoint = tenths_to_c(status["temp_set"])
    else:
        setpoint = tenths_to_c(status.get("at_home_setting"))
    return {
        "id": device.get("id"),
        "name": (device.get("name") or "").strip() or device.get("id"),
        "online": bool(device.get("online")),
        "mode": mode,
        "room_temp": tenths_to_c(status.get("temp_current")),
        "setpoint": setpoint,
        "battery": status.get("battery_percentage"),
        # "Heat" = das Ventil heizt gerade, "NoHeat" = nicht
        "heating": status.get("work_state") == "Heat",
    }


def last_click_time(mode: str) -> str:
    """Zusatzwert, den die Ally-App beim Umschalten auf "Zuhause"/"Abwesend" mitschickt
    (von pydanfossally übernommen), damit der Wochenplan den Modus nicht gleich wieder
    überschreibt."""
    suffix = "010000" if mode == "at_home" else "000101"
    return datetime.now().strftime("%Y%m%d%H%M") + suffix
