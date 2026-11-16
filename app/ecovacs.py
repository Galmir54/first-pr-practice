"""ECOVACS-Saugroboter (Deebot) im Grundriss: Status und Position zum Ansehen (nur Lesen).

Es gibt keine offizielle lokale Schnittstelle, der Weg geht über die ECOVACS-Cloud mit dem eigenen Konto. Die Bibliothek
dafür (deebot-client, wie in Home Assistant) braucht seit dem neuen Login Python >= 3.14, der Server läuft aber auf
einem älteren Python. Deshalb legt dieses Modul bei Bedarf ein zweites Python 3.14 in data/ecovacs/ an (mit uv, komplett
im Datenordner, jederzeit löschbar) und startet darin den Hilfsprozess robot/ecovacs_worker.py. Der Hauptserver und sein
Update bleiben davon unberührt; schlägt etwas fehl, zeigt nur der Status im Grundriss den Fehler.

Zugangsdaten: E-Mail und Land liegen in der Datenbank. Das Passwort wird nur für die erste Anmeldung im Speicher gehalten
(als MD5-Wert, wie ECOVACS es verlangt) und danach verworfen; gespeichert wird nur der Zugang (Token), mit dem sich der
Hilfsprozess ohne Passwort erneuern kann. Bei einem neuen Gerät schickt ECOVACS einen Code per E-Mail, den man eingibt.

Die Roboter-Position kommt in Karten-Koordinaten des Roboters (mm, y nach oben) relativ zur Ladestation. Sie wird mit
einer Kalibrierung (Lage der Station im Plan, Drehung, Spiegelung, Maßstab) in Plan-Koordinaten umgerechnet.
"""

import asyncio
import hashlib
import json
import logging
import math
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from . import config
from .db import db_cursor

logger = logging.getLogger("ecovacs")

EMAIL_KEY = "ecovacs.email"
COUNTRY_KEY = "ecovacs.country"
DEVICE_ID_KEY = "ecovacs.device_id"
ACCOUNT_KEY = "ecovacs.account"
SELECTED_KEY = "ecovacs.selected"
CALIBRATION_KEY = "ecovacs.calibration"

RUNTIME_DIR = config.DATA_DIR / "ecovacs"
VENV_DIR = RUNTIME_DIR / "venv"
WORKER = config.BASE_DIR / "robot" / "ecovacs_worker.py"
LIB_SPEC = "deebot-client>=18.7,<19"
PYTHON_VERSION = "3.14"
# Zum Ausprobieren ohne Konto und ohne Bibliothek: ein erfundener Roboter (läuft mit dem Python des Servers)
SIMULATE = bool(os.environ.get("ENERGY_ECOVACS_SIMULATE"))

STALE_AFTER_S = 150  # so lange darf die letzte Meldung her sein, bevor die Anzeige "veraltet" sagt
TRAIL_MAX = 600
TRAIL_MIN_STEP_MM = 80

# Lage der Ladestation im Plan (Mitte des Roboters, wenn er andockt) und Umrechnung der Roboter-Karte:
# Schlafzimmer, an der Ostwand (Wand innen x 1,31) bei z 1,08, Front nach Westen (vom Nutzer im Plan eingekreist, 16.11.);
# Roboter-Karte: x nach rechts, y nach oben, Plan: x nach rechts, z nach unten (Süden) -> y wird gespiegelt; Einheit mm.
# Die Drehung 90 ist ein erster Versuch (der Roboter fährt aus der Station nach Westen); die echte Lage der Roboter-Karte
# ist unbekannt und wird mit dem ersten Reinigungslauf eingestellt.
DEFAULT_CALIBRATION = {"dock_x": 1.03, "dock_z": 1.08, "rot": 90.0, "flip_y": True, "scale": 0.001}

state: dict = {
    "status": "not_configured",  # not_configured | installing | login | verify_required | connecting | ok | auth_failed | error
    "message": "",
    "devices": [],
    "selected": None,
    "robot": None,  # letzter Zustand vom Hilfsprozess (Karten-Koordinaten)
    "robot_at": 0.0,  # time.monotonic() der letzten Meldung
    "runtime": {"installed": False, "step": ""},
}

_trail: deque = deque(maxlen=TRAIL_MAX)  # [x, y] in Karten-Koordinaten (mm)
_last_charger: dict | None = None
_pending_hash: str | None = None  # Passwort-MD5 bis zur ersten erfolgreichen Anmeldung (nur im Speicher)
_proc: subprocess.Popen | None = None
_wake: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None
_restart_requested = False
_stop_requested = False
_blocked_until = 0.0  # time.monotonic(): bis dahin nicht neu versuchen
_stderr_tail: deque = deque(maxlen=12)


# ---------------------------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------------------------
def _load(key: str, default=None):
    with db_cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
    return row["value"] if row else default


def _save(key: str, value: str | None) -> None:
    with db_cursor(commit=True) as cur:
        if value is None:
            cur.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


def _load_json(key: str):
    raw = _load(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def calibration() -> dict:
    stored = _load_json(CALIBRATION_KEY) or {}
    return {**DEFAULT_CALIBRATION, **{k: v for k, v in stored.items() if k in DEFAULT_CALIBRATION}}


def set_calibration(values: dict) -> dict:
    merged = {**calibration(), **{k: v for k, v in values.items() if k in DEFAULT_CALIBRATION and v is not None}}
    _save(CALIBRATION_KEY, json.dumps(merged))
    return merged


def _configured() -> bool:
    return bool(_load(EMAIL_KEY) and (_load(ACCOUNT_KEY) or _pending_hash))


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    name, domain = email.split("@", 1)
    return f"{name[:1]}***@{domain}"


# ---------------------------------------------------------------------------------------------
# Plan-Koordinaten
# ---------------------------------------------------------------------------------------------
def _to_plan(cal: dict, origin: dict, pos: dict) -> tuple[float, float]:
    dx = (pos["x"] - origin["x"]) * cal["scale"]
    dz = (pos["y"] - origin["y"]) * cal["scale"]
    if cal["flip_y"]:
        dz = -dz
    angle = math.radians(cal["rot"])
    x = dx * math.cos(angle) - dz * math.sin(angle)
    z = dx * math.sin(angle) + dz * math.cos(angle)
    return cal["dock_x"] + x, cal["dock_z"] + z


def _heading(cal: dict, heading_deg: float) -> list[float]:
    phi = math.radians(heading_deg)
    vx, vz = math.cos(phi), math.sin(phi)
    if cal["flip_y"]:
        vz = -vz
    angle = math.radians(cal["rot"])
    return [round(vx * math.cos(angle) - vz * math.sin(angle), 4), round(vx * math.sin(angle) + vz * math.cos(angle), 4)]


def public_state() -> dict:
    """Für die Anzeige im Grundriss (nie Passwort oder Token)."""
    cal = calibration()
    robot = state["robot"]
    age = time.monotonic() - state["robot_at"] if state["robot_at"] else None
    out_robot = None
    plan = None
    trail: list = []
    if robot:
        out_robot = {
            "available": robot.get("available"),
            "state": robot.get("state"),
            "battery": robot.get("battery"),
            "error": robot.get("error"),
            "area": robot.get("area"),
            "time": robot.get("time"),
            "stale": age is None or age > STALE_AFTER_S,
        }
        pos = robot.get("pos")
        origin = robot.get("charger") or _last_charger
        if origin is None and pos and robot.get("state") == "docked":
            origin = pos
        if pos and origin:
            x, z = _to_plan(cal, origin, pos)
            plan = {"x": round(x, 3), "z": round(z, 3), "heading": _heading(cal, pos.get("a", 0))}
            points = list(_trail)
            step = max(1, len(points) // 300)
            trail = [[round(v, 3) for v in _to_plan(cal, origin, {"x": p[0], "y": p[1]})] for p in points[::step]]
    return {
        "configured": state["status"] != "not_configured",
        "status": state["status"],
        "message": state["message"],
        "email": _mask(_load(EMAIL_KEY)),
        "country": _load(COUNTRY_KEY) or "DE",
        "devices": state["devices"],
        "selected": state["selected"],
        "robot": out_robot,
        "plan": plan,
        "trail": trail,
        "calibration": cal,
        "runtime": state["runtime"],
        "simulate": SIMULATE,
    }


# ---------------------------------------------------------------------------------------------
# Eingaben von außen (Router)
# ---------------------------------------------------------------------------------------------
def wake() -> None:
    """Weckt die Schleife (aus jedem Thread aufrufbar)."""
    if _wake is not None and _loop is not None:
        _loop.call_soon_threadsafe(_wake.set)


def login(email: str, password: str, country: str) -> None:
    """Neue Anmeldung: speichert E-Mail/Land, merkt sich den Passwort-Hash nur im Speicher."""
    global _pending_hash, _restart_requested, _blocked_until
    _save(EMAIL_KEY, email.strip())
    _save(COUNTRY_KEY, country.strip().upper() or "DE")
    if not _load(DEVICE_ID_KEY):
        _save(DEVICE_ID_KEY, uuid.uuid4().hex)
    _save(ACCOUNT_KEY, None)  # ein neues Passwort ersetzt den alten Zugang
    _save(SELECTED_KEY, None)
    _pending_hash = hashlib.md5(password.encode("utf-8")).hexdigest()  # noqa: S324 - verlangt die ECOVACS-Anmeldung
    state.update(status="login", message="Anmeldung wird gestartet", devices=[], selected=None, robot=None, robot_at=0.0)
    _trail.clear()
    _blocked_until = 0.0
    _restart_requested = True
    wake()


def verify(code: str) -> bool:
    return _send({"cmd": "verify", "code": code.strip()})


def resend_code() -> bool:
    return _send({"cmd": "resend"})


def select_device(did: str) -> None:
    global _restart_requested
    _save(SELECTED_KEY, did)
    state["selected"] = did
    state["robot"] = None
    state["robot_at"] = 0.0
    _trail.clear()
    _restart_requested = True
    wake()


def retry() -> None:
    """Erneuter Versuch (z. B. nach einem Netzfehler oder einer fehlgeschlagenen Einrichtung)."""
    global _blocked_until
    _blocked_until = 0.0
    wake()


def remove() -> None:
    """Alles vergessen: Zugang, E-Mail, Auswahl. (Das zweite Python bleibt liegen, es stört nicht.)"""
    global _pending_hash, _stop_requested, _last_charger
    for key in (EMAIL_KEY, COUNTRY_KEY, ACCOUNT_KEY, SELECTED_KEY):
        _save(key, None)
    _pending_hash = None
    _last_charger = None
    _trail.clear()
    state.update(status="not_configured", message="", devices=[], selected=None, robot=None, robot_at=0.0)
    _stop_requested = True
    wake()


def _send(command: dict) -> bool:
    proc = _proc
    if proc is None or proc.poll() is not None or proc.stdin is None:
        return False
    try:
        proc.stdin.write(json.dumps(command) + "\n")
        proc.stdin.flush()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------------------------
# Zweites Python 3.14 einrichten
# ---------------------------------------------------------------------------------------------
def environment() -> dict:
    """Welche Python-Umgebung läuft hier? (keine Geheimnisse, nur Versionen und Pfade)"""
    usage = shutil.disk_usage("C:\\" if sys.platform == "win32" else "/")
    return {
        "python": platform.python_version(),
        "python_ok_for_deebot_client": sys.version_info >= (3, 14),
        "machine": platform.machine(),
        "system": f"{platform.system()} {platform.release()}",
        "uv": shutil.which("uv"),
        "python3_14": shutil.which("python3.14"),
        "free_disk_mb": round(usage.free / 1e6),
        "runtime_python": str(venv_python()) if venv_python().exists() else None,
    }


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


async def _run(command: list[str], *, timeout: int, env: dict | None = None) -> tuple[int, str]:
    """Führt einen Befehl aus, ohne den Server zu blockieren; gibt (Exitcode, letzte Ausgabe) zurück."""

    def work() -> tuple[int, str]:
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, f"{type(exc).__name__}: {exc}"
        return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()[-400:]

    return await asyncio.to_thread(work)


async def _runtime_ready() -> bool:
    python = venv_python()
    if not python.exists():
        return False
    code, _ = await _run([str(python), "-c", "import deebot_client"], timeout=60)
    return code == 0


async def ensure_runtime() -> bool:
    """Sorgt dafür, dass data/ecovacs/venv ein Python 3.14 mit deebot-client enthält. False = fehlgeschlagen (Status gesetzt)."""
    if SIMULATE:
        state["runtime"] = {"installed": True, "step": "Simulation"}
        return True
    if await _runtime_ready():
        state["runtime"] = {"installed": True, "step": ""}
        return True

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "UV_PYTHON_INSTALL_DIR": str(RUNTIME_DIR / "python"),  # alles im Datenordner, nichts im Home-Verzeichnis
        "UV_CACHE_DIR": str(RUNTIME_DIR / "uv-cache"),
    }

    def step(text: str) -> None:
        state.update(status="installing", message=text)
        state["runtime"] = {"installed": False, "step": text}

    step("Hilfsprogramm uv wird bereitgestellt (1/3)")
    uv = [shutil.which("uv")] if shutil.which("uv") else None
    if uv is None:
        code, output = await _run([sys.executable, "-m", "pip", "install", "--quiet", "uv"], timeout=300, env=env)
        if code != 0:
            return _fail(f"uv konnte nicht installiert werden: {output}")
        uv = [sys.executable, "-m", "uv"]

    step(f"Python {PYTHON_VERSION} wird eingerichtet (2/3, kann einige Minuten dauern)")
    if not venv_python().exists():
        code, output = await _run([*uv, "venv", str(VENV_DIR), "--python", PYTHON_VERSION], timeout=900, env=env)
        if code != 0:
            return _fail(f"Python {PYTHON_VERSION} konnte nicht eingerichtet werden: {output}")

    step("ECOVACS-Bibliothek wird installiert (3/3)")
    code, output = await _run([*uv, "pip", "install", "--python", str(venv_python()), LIB_SPEC], timeout=900, env=env)
    if code != 0:
        return _fail(f"deebot-client konnte nicht installiert werden: {output}")
    if not await _runtime_ready():
        return _fail("deebot-client ist installiert, lässt sich aber nicht laden")
    state["runtime"] = {"installed": True, "step": ""}
    return True


def _fail(message: str) -> bool:
    global _blocked_until
    logger.warning("ECOVACS-Einrichtung fehlgeschlagen: %s", message)
    state.update(status="error", message=message[:300])
    state["runtime"] = {"installed": False, "step": ""}
    _blocked_until = time.monotonic() + 900  # in 15 Minuten wieder, oder sofort per "Neu versuchen"
    return False


# ---------------------------------------------------------------------------------------------
# Hilfsprozess starten und überwachen
# ---------------------------------------------------------------------------------------------
def _handle(message: dict) -> None:
    """Verarbeitet eine Meldung des Hilfsprozesses."""
    global _pending_hash, _last_charger, _blocked_until
    kind = message.get("type")
    if kind == "status":
        status = message.get("status")
        if status in ("login", "verify_required", "connecting", "ok"):
            state.update(status=status, message=message.get("message") or "")
            if status == "ok":
                _pending_hash = None  # ab jetzt genügt der gespeicherte Zugang
    elif kind == "account":
        _save(ACCOUNT_KEY, json.dumps({"access_token": message["access_token"], "user_id": message["user_id"]}))
        _pending_hash = None
    elif kind == "devices":
        state["devices"] = message.get("devices") or []
        selected = message.get("selected")
        state["selected"] = selected
        if selected and not _load(SELECTED_KEY):
            _save(SELECTED_KEY, selected)
    elif kind == "robot":
        previous = (state["robot"] or {}).get("state")
        robot = {key: message.get(key) for key in ("available", "state", "battery", "error", "area", "time", "pos", "charger")}
        state["robot"] = robot
        state["robot_at"] = time.monotonic()
        if robot.get("charger"):
            _last_charger = robot["charger"]
        if previous == "docked" and robot.get("state") in ("cleaning", "returning"):
            _trail.clear()  # neuer Reinigungslauf: Spur von vorn
        pos = robot.get("pos")
        if pos and robot.get("state") in ("cleaning", "returning", "paused", "error"):
            last = _trail[-1] if _trail else None
            if last is None or math.hypot(pos["x"] - last[0], pos["y"] - last[1]) >= TRAIL_MIN_STEP_MM:
                _trail.append([pos["x"], pos["y"]])
    elif kind == "fatal":
        problem = message.get("message") or "unbekannter Fehler"
        if message.get("kind") == "auth":
            state.update(status="auth_failed", message=problem)
            _pending_hash = None
            _blocked_until = float("inf")  # erst nach neuer Anmeldung wieder
        else:
            state.update(status="error", message=problem[:300])


async def _run_worker() -> str:
    """Startet den Hilfsprozess und liest seine Meldungen, bis er endet (oder ein Neustart/Stopp verlangt wird).
    Gibt "ended" (von selbst beendet), "restart" oder "stop" zurück."""
    global _proc, _restart_requested, _stop_requested, _blocked_until
    python = sys.executable if SIMULATE else str(venv_python())
    command = [python, "-u", str(WORKER)]
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _stderr_tail.clear()

    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    _proc = proc

    def read_stdout() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            loop.call_soon_threadsafe(queue.put_nowait, line)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    def read_stderr() -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            _stderr_tail.append(line.rstrip()[:200])

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()

    account = _load_json(ACCOUNT_KEY)
    _restart_requested = False
    _send(
        {
            "cmd": "start",
            "email": _load(EMAIL_KEY),
            "country": _load(COUNTRY_KEY) or "DE",
            "device_id": _load(DEVICE_ID_KEY),
            "password_hash": _pending_hash,
            "account": account,
            "selected": _load(SELECTED_KEY),
            "simulate": SIMULATE,
        }
    )
    started = time.monotonic()
    try:
        while True:
            if _restart_requested or _stop_requested:
                break
            try:
                line = await asyncio.wait_for(queue.get(), timeout=1)
            except asyncio.TimeoutError:
                if proc.poll() is not None and queue.empty():
                    break
                continue
            if line is None:
                break
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict):
                try:
                    _handle(message)
                except Exception:
                    logger.exception("ECOVACS-Meldung nicht verarbeitbar")
    finally:
        _send({"cmd": "stop"})
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        _proc = None

    if _stop_requested:
        _stop_requested = False
        return "stop"
    if _restart_requested:
        return "restart"
    # Prozess ist von selbst zu Ende gegangen
    if state["status"] == "verify_required":
        state.update(status="auth_failed", message="Die Bestätigung wurde abgebrochen - bitte neu anmelden")
        _blocked_until = float("inf")
    elif state["status"] not in ("auth_failed", "error"):
        tail = " | ".join(list(_stderr_tail)[-2:])
        state.update(status="error", message=("Verbindung beendet" + (f": {tail}" if tail else ""))[:300])
    if time.monotonic() - started < 20 and _blocked_until != float("inf"):
        _blocked_until = max(_blocked_until, time.monotonic() + 60)
    return "ended"


async def _sleep(seconds: float) -> None:
    assert _wake is not None
    try:
        await asyncio.wait_for(_wake.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    _wake.clear()


async def ecovacs_loop() -> None:
    """Hintergrundschleife: richtet bei Bedarf das Python ein und hält den Hilfsprozess am Laufen."""
    global _wake, _loop, _stop_requested, _blocked_until
    _wake = asyncio.Event()
    _loop = asyncio.get_running_loop()
    failures = 0
    try:
        while True:
            try:
                if not await asyncio.to_thread(_configured):
                    if state["status"] not in ("not_configured",):
                        state.update(status="not_configured", message="")
                    await _sleep(5)
                    continue
                if _blocked_until > time.monotonic():
                    await _sleep(min(30, _blocked_until - time.monotonic()) if _blocked_until != float("inf") else 30)
                    continue
                if not await ensure_runtime():
                    await _sleep(30)
                    continue
                _stop_requested = False
                if state["status"] in ("installing", "not_configured", "error"):
                    state.update(status="login", message="")
                reason = await _run_worker()
                if reason != "ended":
                    failures = 0
                    continue  # gewollter Neustart oder Stopp: gleich weiter
                failures = 0 if state["status"] == "ok" else failures + 1
                await _sleep(min(300, 5 * 2 ** min(failures, 6)))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ECOVACS-Schleife")
                state.update(status="error", message="interner Fehler (siehe Server-Log)")
                await _sleep(60)
    finally:
        proc = _proc
        if proc is not None and proc.poll() is None:
            _send({"cmd": "stop"})
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
