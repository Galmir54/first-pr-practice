"""Anycubic-Cloud: Druckfortschritt und Restzeit des FDM-Druckers (Kobra 2 usw.).

Anycubic hat keine offizielle Schnittstelle. Das hier nutzt dieselbe Web-Schnittstelle wie die Seite
cloud-universe.anycubic.com (und die Home-Assistant-Integration "hass-anycubic_cloud", von der die Anfrage-Signatur
und die Feldnamen stammen). Gebraucht wird der Web-Token des eigenen Kontos
(im Browser auf cloud-universe.anycubic.com: Konsole -> window.localStorage["XX-Token"]). Er wird in der
Datenbank des Pi gespeichert und nie wieder ausgegeben.

Abgefragt wird nur lesend: Druckerliste und Druckaufträge. Läuft der Drucker (laut Steckdose oder Cloud) alle 60 s,
sonst alle 5 Minuten. Ohne Token passiert nichts.
"""

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
import uuid

import httpx

from . import poller
from .db import db_cursor

logger = logging.getLogger("anycubic")

TOKEN_KEY = "anycubic.token"
PRINTER_KEY = "anycubic.printer_id"
BASE = "https://cloud-universe.anycubic.com/p/p/workbench/api"
# Kennungen der Web-Anwendung (öffentlich im JavaScript der Seite, wie in hass-anycubic_cloud)
APP_ID = "f9b3528877c94d5c9c5af32245db46ef"
APP_SECRET = "0cf75926606049a3937f56b0373b99fb"
APP_VERSION = "1.0.0"
CLIENT_ID_WEB = "672efcd4ec11a66c8513"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
ORIGIN = "https://uc.makeronline.com"

POLL_ACTIVE_S = 60
POLL_IDLE_S = 300
FRESH_ACTIVE_S = 4 * 60  # so alt darf die Auskunft sein, um noch zu gelten
FRESH_IDLE_S = 12 * 60
FINISHED_SHOW_S = 90 * 60

# print_status im Auftrag
PRINTING, COMPLETE, CANCELLED, DOWNLOADING, CHECKING, PREHEATING, SLICING = 1, 2, 3, 4, 5, 6, 7
IN_PROGRESS = (PRINTING, DOWNLOADING, CHECKING, PREHEATING, SLICING)

# Zustand der Verbindung, für die Anzeige im Grundriss-Einstellungsfenster
state: dict = {
    "status": "not_configured",  # not_configured | ok | token_invalid | error
    "message": "",
    "checked_at": None,
    "printers": [],  # [{id, name, model, is_printing}]
    "job": None,  # aktueller/letzter Auftrag des gewählten Druckers (siehe _job_from)
    "job_at": 0.0,  # time.monotonic() der letzten erfolgreichen Auskunft
}
_wakeup: asyncio.Event | None = None  # wird in der Schleife angelegt (gehört zur laufenden Ereignisschleife)


def wake() -> None:
    """Weckt die Schleife sofort (nach neuem Token/Drucker). Nur aus der Ereignisschleife aufrufen."""
    if _wakeup is not None:
        _wakeup.set()


def _load(key: str):
    with db_cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
    return row["value"] if row else None


def _save(key: str, value: str | None) -> None:
    with db_cursor(commit=True) as cur:
        if value is None:
            cur.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


def has_token() -> bool:
    token = _load(TOKEN_KEY)
    return bool(token and token.strip())


def clean_token(raw: str | None) -> str:
    """Eingefügten Token bereinigen: Anführungszeichen, "Bearer ", Leerraum und Zeilenumbrüche (auch mitten drin)."""
    token = (raw or "").strip()
    token = re.sub(r"^(?:bearer|xx-token)\s*[:=]?\s*", "", token, flags=re.I)
    return re.sub(r"[\s'\"`]+", "", token)


def describe_token(token: str) -> str:
    """Kurze Auskunft über die Form des Tokens (ohne ihn preiszugeben), um falsches Kopieren zu erkennen."""
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        return (f"Die Cloud lehnt den eingetragenen Text ({len(token)} Zeichen, kein JWT) ab - "
                "vermutlich der falsche Wert aus dem Browser; bitte neu holen")
    info = f"{len(token)} Zeichen"
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        if isinstance(exp, (int, float)):
            when = time.strftime("%d.%m.%Y %H:%M", time.localtime(exp))
            if exp < time.time():
                return f"Token ist abgelaufen (seit {when}) - neu holen"
            info += f", gültig bis {when}"
    except Exception:
        pass
    return f"Token sieht vollständig aus ({info}), die Cloud lehnt ihn trotzdem ab - nach neuem Login auf der Webseite alten Token verworfen? Neu holen und sofort eintragen"


def set_token(token: str | None) -> None:
    token = clean_token(token)
    _save(TOKEN_KEY, token or None)
    state.update(status="not_configured" if not token else "error", message="" if not token else "noch nicht geprüft",
                 printers=[], job=None, job_at=0.0)
    if not token:
        state["checked_at"] = None


def selected_printer_id() -> int | None:
    value = _load(PRINTER_KEY)
    try:
        return int(value) if value else None
    except ValueError:
        return None


def set_printer_id(printer_id: int | None) -> None:
    _save(PRINTER_KEY, str(printer_id) if printer_id is not None else None)
    state["job"] = None
    state["job_at"] = 0.0


def _headers(token: str) -> dict[str, str]:
    nonce = str(uuid.uuid1())
    stamp = str(int(time.time() * 1000))
    signature = hashlib.md5(f"{APP_ID}{stamp}{APP_VERSION}{APP_SECRET}{nonce}{APP_ID}".encode()).hexdigest()
    return {
        "User-Agent": USER_AGENT,
        "Origin": ORIGIN,
        "Xx-Device-Type": "web",
        "Xx-Is-Cn": "1",
        "Xx-Nonce": nonce,
        "Xx-Signature": signature,
        "Xx-Timestamp": stamp,
        "Xx-Version": APP_VERSION,
        "Content-Type": "application/json",
        "XX-LANGUAGE": "US",
        "XX-Token": token,
    }


class TokenInvalid(Exception):
    pass


async def _get(client: httpx.AsyncClient, token: str, path: str, params: dict | None = None) -> dict:
    resp = await client.get(BASE + path, params=params, headers=_headers(token))
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"Antwort von Anycubic ist kein JSON (HTTP {resp.status_code})")
    if not isinstance(data, dict):
        raise RuntimeError("Unerwartete Antwort von Anycubic")
    return data


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _job_from(project: dict) -> dict:
    """Auftrag -> {status, progress (0..1), remaining_s, elapsed_s, started_at, ended_at, name, paused}."""
    status = _int(project.get("print_status"), 0)
    remain_min = _int(project.get("remain_time"))
    elapsed_min = _int(project.get("print_time"))
    progress = _int(project.get("progress"))
    name = str(project.get("gcode_name") or project.get("name") or "")
    if name.lower().endswith(".gcode"):
        name = name[:-6]
    return {
        "status": status,
        "in_progress": status in IN_PROGRESS,
        "paused": bool(_int(project.get("pause"), 0)) and status in IN_PROGRESS,
        "progress": progress / 100 if progress is not None and 0 <= progress <= 100 else None,
        "remaining_s": remain_min * 60 if remain_min and remain_min > 0 else None,  # 0/-1 = noch keine Schätzung
        "elapsed_s": elapsed_min * 60 if elapsed_min is not None else None,
        "started_at": _int(project.get("start_time")) or _int(project.get("create_time")),
        "ended_at": _int(project.get("end_time")) or None,
        "name": name,
        "preparing": status in (DOWNLOADING, CHECKING, PREHEATING, SLICING),
    }


async def refresh() -> None:
    """Eine Abfrage: Druckerliste und neuester Auftrag des gewählten Druckers."""
    token = await asyncio.to_thread(_load, TOKEN_KEY)
    token = clean_token(token)
    if not token:
        state.update(status="not_configured", message="", printers=[], job=None)
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            printers_resp = await _get(client, token, "/work/printer/getPrinters")
            raw = printers_resp.get("data")
            if not isinstance(raw, list):
                # abgelaufener/falscher Token: die Cloud antwortet ohne Druckerliste
                info = await _get(client, token, "/user/profile/userInfo")
                data = info.get("data")
                if not isinstance(data, dict) or data.get("id") is None:
                    raise TokenInvalid()
                raise RuntimeError("Druckerliste fehlt in der Antwort")
            printers = [
                {
                    "id": _int(p.get("id")),
                    "name": str(p.get("name") or ""),
                    "model": str(p.get("model") or p.get("machine_name") or ""),
                    "is_printing": _int(p.get("is_printing"), 0) == 2,
                }
                for p in raw
                if isinstance(p, dict) and _int(p.get("id")) is not None
            ]
            chosen = selected_printer_id()
            if chosen is None or chosen not in {p["id"] for p in printers}:
                chosen = (next((p for p in printers if p["is_printing"]), None) or (printers[0] if printers else {})).get("id")

            job = None
            if chosen is not None:
                projects = await _get(client, token, "/work/project/getProjects", {"page": "1", "limit": "20"})
                for project in projects.get("data") or []:
                    if isinstance(project, dict) and _int(project.get("printer_id")) == chosen:
                        job = _job_from(project)
                        break
    except TokenInvalid:
        state.update(status="token_invalid", message=describe_token(token), checked_at=time.time(), job=None)
        return
    except Exception as exc:
        logger.warning("Anycubic-Abfrage fehlgeschlagen: %s", exc)
        state.update(status="error", message=str(exc)[:200], checked_at=time.time())
        return

    state.update(status="ok", message="", checked_at=time.time(), printers=printers, job=job, job_at=time.monotonic(),
                 selected_id=chosen)


def printing_now() -> bool:
    job = state.get("job")
    return bool(job and job.get("in_progress") and state.get("status") == "ok")


async def anycubic_loop() -> None:
    """Hintergrundschleife: häufig, solange gedruckt wird (laut Cloud oder Steckdose), sonst selten."""
    global _wakeup
    _wakeup = asyncio.Event()
    while True:
        try:
            if await asyncio.to_thread(has_token):
                await refresh()
        except Exception:
            logger.exception("Anycubic-Schleife")
        plug = poller.latest.get(6)
        plug_active = bool(plug and (plug.get("power_w") or 0) >= 20)
        wait = POLL_ACTIVE_S if (printing_now() or plug_active) else POLL_IDLE_S
        _wakeup.clear()
        try:
            await asyncio.wait_for(_wakeup.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass


def cloud_run_state() -> dict | None:
    """Laufzustand des Druckers aus der Cloud im Format von runs.run_state (mit source "cloud"),
    None, wenn keine frische Auskunft vorliegt (dann gilt der Verlauf der Steckdose)."""
    if state.get("status") != "ok" or not state.get("job"):
        return None
    job = state["job"]
    age = time.monotonic() - state.get("job_at", 0.0)
    now = time.time()
    if job["in_progress"]:
        if age > FRESH_ACTIVE_S:
            return None
        elapsed = job["elapsed_s"]
        if elapsed is None and job["started_at"]:
            elapsed = max(0, now - job["started_at"])
        remaining = job["remaining_s"]
        # seit der Abfrage vergangene Zeit abziehen
        if remaining is not None:
            remaining = max(60, int(remaining - age))
        if elapsed is not None:
            elapsed = int(elapsed + age)
        progress = job["progress"]
        if progress is None and elapsed and remaining:
            progress = elapsed / (elapsed + remaining)
        out = {
            "state": "running",
            "source": "cloud",
            "paused": job["paused"],
            "preparing": job["preparing"],
            "job": job["name"],
            "elapsed_s": elapsed,
            "remaining_s": remaining,
            "progress": round(progress, 3) if progress is not None else None,
            "confidence": "Cloud",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(job["started_at"] or now)),
            "energy_wh": None,
        }
        if remaining:
            out["finish_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now + remaining))
        return out
    if job["status"] == COMPLETE and job["ended_at"]:
        since = now - job["ended_at"]
        if 0 <= since <= FINISHED_SHOW_S and age <= FRESH_IDLE_S:
            started = job["started_at"] or job["ended_at"]
            return {
                "state": "done",
                "source": "cloud",
                "job": job["name"],
                "since_s": int(since),
                "duration_s": int(job["elapsed_s"] if job["elapsed_s"] else max(0, job["ended_at"] - started)),
                "energy_wh": None,
            }
    return None


def public_state() -> dict:
    """Für die Anzeige im Einstellungsfenster (ohne Token)."""
    return {
        "configured": state["status"] != "not_configured",
        "status": state["status"],
        "message": state["message"],
        "checked_at": state["checked_at"],
        "printers": state["printers"],
        "selected_id": state.get("selected_id"),
        "job": state["job"],
    }
