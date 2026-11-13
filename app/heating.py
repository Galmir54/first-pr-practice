"""Heizungs-Automation: Handy verlässt das WLAN -> Danfoss-Ally-Thermostate absenken.

Ablauf (alle CHECK_INTERVAL_SECONDS):
- Für jedes eingetragene Handy wird geprüft, ob es im Heimnetz ist (presence.py).
- Wurde *kein* Handy mehr seit `away_delay_min` Minuten gesehen, werden alle
  Thermostate auf "Abwesend" mit der eingestellten Absenktemperatur geschaltet.
  Vorher wird je Thermostat der bisherige Modus (und bei "manuell" die Solltemperatur)
  gemerkt.
- Taucht ein Handy wieder auf, wird jedes Thermostat auf genau diesen Modus
  zurückgesetzt (z.B. zurück in den Wochenplan).

Zustand ("home"/"away") und die gemerkten Werte liegen in der Tabelle `settings`,
damit ein Neustart des Pi mitten in der Abwesenheit nichts durcheinanderbringt.
Ein Befehl, der fehlschlägt (z.B. kein Internet), wird beim nächsten Durchlauf
wiederholt; der Zustand wechselt erst, wenn alle Thermostate umgeschaltet sind.
"""
import asyncio
import json
import logging
import time
from datetime import datetime

from . import ally_client, db, presence

logger = logging.getLogger("energy.heating")

CHECK_INTERVAL_SECONDS = 30
THERMOSTAT_CACHE_SECONDS = 60
# Nach "Jetzt absenken/zurücksetzen" im Web-UI pausiert die Automatik so lange,
# sonst würde sie einen Test sofort wieder rückgängig machen.
MANUAL_HOLD_SECONDS = 10 * 60

DEFAULTS = {"enabled": False, "away_temp": 17.0, "away_delay_min": 15}

_lock = asyncio.Lock()
_started_at = time.time()
_last_seen: dict[str, float] = {}
_present: dict[str, bool] = {}
_last_check: float | None = None
_last_error: str | None = None
_hold_until = 0.0
_thermostat_cache: tuple[float, list[dict]] | None = None
_client: ally_client.AllyClient | None = None
_client_creds: tuple[str, str] | None = None


# --- Einstellungen ---

def _get(cur, key: str) -> str | None:
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    return row["value"] if row else None


def _set(cur, key: str, value: str | None) -> None:
    if value is None:
        cur.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


def load_config() -> dict:
    with db.db_cursor() as cur:
        phones = _get(cur, "heating.phone_ips") or ""
        away_temp = _get(cur, "heating.away_temp")
        delay = _get(cur, "heating.away_delay_min")
        return {
            "enabled": _get(cur, "heating.enabled") == "1",
            "ally_key": _get(cur, "heating.ally_key") or "",
            "ally_secret": _get(cur, "heating.ally_secret") or "",
            "phone_ips": [ip for ip in phones.split(",") if ip],
            "away_temp": float(away_temp) if away_temp else DEFAULTS["away_temp"],
            "away_delay_min": int(delay) if delay else DEFAULTS["away_delay_min"],
        }


def public_config() -> dict:
    """Konfiguration für das Web-UI – das Secret verlässt den Pi nie."""
    cfg = load_config()
    secret = cfg.pop("ally_secret")
    cfg["has_secret"] = bool(secret)
    return cfg


def save_config(enabled: bool, ally_key: str | None, ally_secret: str | None,
                phone_ips: list[str], away_temp: float, away_delay_min: int) -> None:
    with db.db_cursor(commit=True) as cur:
        _set(cur, "heating.enabled", "1" if enabled else "0")
        if ally_key is not None:
            _set(cur, "heating.ally_key", ally_key.strip())
        if ally_secret:  # leer = gespeichertes Secret behalten
            _set(cur, "heating.ally_secret", ally_secret.strip())
        _set(cur, "heating.phone_ips", ",".join(phone_ips))
        _set(cur, "heating.away_temp", str(away_temp))
        _set(cur, "heating.away_delay_min", str(away_delay_min))
    global _thermostat_cache
    _thermostat_cache = None


def _load_state() -> tuple[str, dict, str | None]:
    with db.db_cursor() as cur:
        state = _get(cur, "heating.state") or "home"
        saved = json.loads(_get(cur, "heating.saved") or "{}")
        changed = _get(cur, "heating.last_change")
    return state, saved, changed


def _save_state(state: str, saved: dict, changed: bool) -> None:
    with db.db_cursor(commit=True) as cur:
        _set(cur, "heating.state", state)
        _set(cur, "heating.saved", json.dumps(saved))
        if changed:
            _set(cur, "heating.last_change", datetime.now().isoformat(timespec="seconds"))


# --- Danfoss ---

def _get_client(cfg: dict) -> ally_client.AllyClient:
    global _client, _client_creds
    creds = (cfg["ally_key"], cfg["ally_secret"])
    if not all(creds):
        raise ally_client.AllyError("API-Schlüssel und Secret sind noch nicht eingetragen")
    if _client is None or _client_creds != creds:
        _client = ally_client.AllyClient(*creds)
        _client_creds = creds
    return _client


async def _thermostats(cfg: dict, fresh: bool = False) -> list[dict]:
    global _thermostat_cache
    if not fresh and _thermostat_cache and time.monotonic() - _thermostat_cache[0] < THERMOSTAT_CACHE_SECONDS:
        return _thermostat_cache[1]
    devices = await _get_client(cfg).list_devices()
    result = [d for d in devices if ally_client.is_thermostat(d)]
    _thermostat_cache = (time.monotonic(), result)
    return result


async def _set_mode(client: ally_client.AllyClient, device_id: str, mode: str) -> None:
    commands: list[tuple[str, object]] = [("mode", mode)]
    if mode in ("at_home", "leaving_home"):
        commands.append(("last_click_time", ally_client.last_click_time(mode)))
    await client.send_commands(device_id, commands)


async def _lower(client: ally_client.AllyClient, device: dict, away_temp: float) -> None:
    status = ally_client.status_map(device)
    value = int(round(away_temp * 10))
    if "leaving_home_setting" in status:
        await _set_mode(client, device["id"], "leaving_home")
        await client.send_commands(device["id"], [("leaving_home_setting", value)])
    else:
        # Geräte ohne Wochenplan-Codes: manuell auf die Absenktemperatur.
        code = "manual_mode_fast" if "manual_mode_fast" in status else "temp_set"
        await _set_mode(client, device["id"], "manual")
        await client.send_commands(device["id"], [(code, value)])


async def _restore(client: ally_client.AllyClient, device_id: str, before: dict) -> None:
    mode = before.get("mode") or "at_home"
    await _set_mode(client, device_id, mode)
    if mode == "manual" and before.get("setpoint_code") and before.get("setpoint") is not None:
        await client.send_commands(device_id, [(before["setpoint_code"], before["setpoint"])])


async def go_away(cfg: dict) -> list[str]:
    """Senkt alle Thermostate ab. Gibt die Fehler je Thermostat zurück (leer = alles ok)."""
    async with _lock:
        state, saved, _ = await asyncio.to_thread(_load_state)
        client = _get_client(cfg)
        errors = []
        for device in await _thermostats(cfg, fresh=True):
            device_id = device["id"]
            name = ally_client.describe(device)["name"]
            if device_id in saved:
                continue  # schon abgesenkt (z.B. vor einem Neustart)
            if not device.get("online"):
                logger.warning("Thermostat '%s' ist offline und wird nicht abgesenkt", name)
                continue
            current = ally_client.describe(device)["setpoint"]
            if current is not None and current <= cfg["away_temp"]:
                # Schon so kalt eingestellt (z.B. Schlafzimmer auf 5 °C): "Absenken"
                # würde den Raum sonst aufheizen.
                continue
            status = ally_client.status_map(device)
            code = "manual_mode_fast" if "manual_mode_fast" in status else "temp_set"
            before = {"name": name, "mode": status.get("mode"), "setpoint_code": code, "setpoint": status.get(code)}
            try:
                await _lower(client, device, cfg["away_temp"])
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                continue
            saved[device_id] = before
            await asyncio.to_thread(_save_state, state, saved, False)
        if not errors:
            await asyncio.to_thread(_save_state, "away", saved, state != "away")
            logger.info("Niemand zu Hause: %d Thermostat(e) auf %.1f °C abgesenkt", len(saved), cfg["away_temp"])
        _invalidate()
        return errors


async def go_home(cfg: dict) -> list[str]:
    """Setzt alle abgesenkten Thermostate auf ihren vorherigen Modus zurück."""
    async with _lock:
        state, saved, _ = await asyncio.to_thread(_load_state)
        client = _get_client(cfg)
        errors = []
        for device_id, before in list(saved.items()):
            try:
                await _restore(client, device_id, before)
            except Exception as exc:
                errors.append(f"{before.get('name', device_id)}: {exc}")
                continue
            del saved[device_id]
            await asyncio.to_thread(_save_state, state, saved, False)
        if not errors:
            await asyncio.to_thread(_save_state, "home", saved, state != "home")
            logger.info("Jemand ist zurück: Thermostate wiederhergestellt")
        _invalidate()
        return errors


def _invalidate() -> None:
    global _thermostat_cache
    _thermostat_cache = None


async def manual_action(action: str) -> list[str]:
    global _hold_until
    cfg = await asyncio.to_thread(load_config)
    _hold_until = time.monotonic() + MANUAL_HOLD_SECONDS
    return await (go_away(cfg) if action == "away" else go_home(cfg))


# --- Automatik ---

async def check_once() -> None:
    global _last_check, _last_error
    cfg = await asyncio.to_thread(load_config)
    phones = cfg["phone_ips"]
    if not (cfg["enabled"] and phones and cfg["ally_key"] and cfg["ally_secret"]):
        return

    now = time.time()
    results = await asyncio.gather(*(presence.is_present(ip) for ip in phones))
    seen_now = False
    for ip, present in zip(phones, results):
        _present[ip] = present
        if present:
            _last_seen[ip] = now
            seen_now = True
    _last_check = now

    if time.monotonic() < _hold_until:
        return

    # Ohne bisherige Sichtung zählt der Programmstart, damit nach einem Neustart erst
    # die volle Wartezeit abläuft, bevor abgesenkt wird.
    delay = cfg["away_delay_min"] * 60
    anyone_recent = any(now - _last_seen.get(ip, _started_at) < delay for ip in phones)

    state, saved, _ = await asyncio.to_thread(_load_state)
    errors: list[str] = []
    if state == "home" and not anyone_recent:
        errors = await go_away(cfg)
    elif (state == "away" or saved) and seen_now:
        errors = await go_home(cfg)
    # Ein offener Fehler führt dazu, dass der Wechsel im nächsten Durchlauf erneut
    # versucht wird; ein Durchlauf ohne Fehler heißt: alles erledigt.
    _last_error = "; ".join(errors) or None
    if errors:
        logger.warning("Heizungs-Automation: %s", _last_error)


async def heating_loop() -> None:
    global _last_error
    while True:
        try:
            await check_once()
        except Exception as exc:
            _last_error = str(exc) or type(exc).__name__
            logger.exception("Heizungs-Automation: %s", _last_error)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def status() -> dict:
    cfg = await asyncio.to_thread(load_config)
    state, saved, changed = await asyncio.to_thread(_load_state)
    now = time.time()
    result = {
        "state": state,
        "last_change": changed,
        "lowered": [b.get("name", i) for i, b in saved.items()],
        "last_check": datetime.fromtimestamp(_last_check).isoformat(timespec="seconds") if _last_check else None,
        "last_error": _last_error,
        "hold_minutes": max(0, round((_hold_until - time.monotonic()) / 60)),
        "phones": [
            {
                "ip": ip,
                "present": _present.get(ip),
                "last_seen": datetime.fromtimestamp(_last_seen[ip]).isoformat(timespec="seconds") if ip in _last_seen else None,
                "minutes_since_seen": round((now - _last_seen[ip]) / 60) if ip in _last_seen else None,
            }
            for ip in cfg["phone_ips"]
        ],
        "thermostats": [],
        "thermostat_error": None,
    }
    if cfg["ally_key"] and cfg["ally_secret"]:
        try:
            result["thermostats"] = [ally_client.describe(d) for d in await _thermostats(cfg)]
        except Exception as exc:
            result["thermostat_error"] = str(exc)
    return result
