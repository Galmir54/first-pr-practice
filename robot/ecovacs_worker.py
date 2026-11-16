"""ECOVACS-Hilfsprozess: spricht mit der ECOVACS-Cloud und meldet den Zustand des Saugroboters als JSON-Zeilen.

Läuft in einem eigenen Python (>= 3.14, wegen deebot-client) unter dem Dashboard-Server (app/ecovacs.py startet und
überwacht ihn). Der Hauptserver bleibt dadurch auf seinem Python.

Protokoll (eine JSON-Zeile pro Nachricht):

  Server -> Hilfsprozess (stdin):
    {"cmd": "start", "email", "country", "device_id", "password_hash"|null, "account": {"access_token","user_id"}|null,
     "selected": did|null, "simulate": bool}
    {"cmd": "verify", "code": "123456"}      # E-Mail-Code zur Bestätigung des Geräts
    {"cmd": "resend"}                        # Code erneut anfordern
    {"cmd": "stop"}                          # (auch Ende von stdin)

  Hilfsprozess -> Server (stdout):
    {"type": "status", "status": "login"|"verify_required"|"connecting"|"ok", "message": "..."}
    {"type": "account", "access_token", "user_id"}      # Zugang ohne Passwort (der Server speichert ihn)
    {"type": "devices", "devices": [{"did","name","model","supported"}], "selected": did}
    {"type": "robot", ...Zustand...}
    {"type": "fatal", "kind": "auth"|"network"|"unsupported"|"library"|"bug", "message": "..."}

Das Passwort wird nur für die erste Anmeldung benutzt (als MD5-Wert) und nie gespeichert; danach genügt der Zugang.
Mit "simulate" läuft ein erfundener Roboter (zum Testen ohne Konto, ohne Bibliothek).
"""

import asyncio
import json
import logging
import math
import os
import sys
import time

STATE_NAMES = {1: "idle", 2: "cleaning", 3: "returning", 4: "docked", 5: "error", 6: "paused"}
ROBOT_KEYS = ("available", "state", "battery", "error", "area", "time", "pos", "charger")


def emit(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class Commands:
    """Liest Befehle vom Server (stdin) in eine Warteschlange; Ende von stdin = stop."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()

    async def pump(self) -> None:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                self.queue.put_nowait({"cmd": "stop"})
                return
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict):
                self.queue.put_nowait(message)

    async def next(self, *names: str) -> dict:
        """Wartet auf einen der Befehle `names` (oder "stop", das immer durchkommt)."""
        while True:
            message = await self.queue.get()
            if message.get("cmd") in names or message.get("cmd") == "stop":
                return message


class Snapshot:
    """Letzter bekannter Zustand des Roboters; `dirty` heißt: seit der letzten Meldung geändert."""

    def __init__(self) -> None:
        self.data: dict = {key: None for key in ROBOT_KEYS}
        self.dirty = True

    def update(self, **values) -> None:
        for key, value in values.items():
            if self.data.get(key) != value:
                self.data[key] = value
                self.dirty = True

    def message(self) -> dict:
        self.dirty = False
        return {"type": "robot", **self.data, "ts": time.time()}


async def emit_loop(snapshot: Snapshot) -> None:
    """Meldet Änderungen gebündelt (höchstens alle 0,4 s) und sonst alle 30 s als Lebenszeichen."""
    last = 0.0
    while True:
        await asyncio.sleep(0.4)
        if snapshot.dirty or time.monotonic() - last > 30:
            emit(snapshot.message())
            last = time.monotonic()


# ----------------------------------------------------------------------------------------------------------------
# Simulation (ohne Konto und ohne Bibliothek): ein erfundener Roboter fährt in Karten-Koordinaten (mm, y nach oben)
# vom Ladepunkt (0, 0) nach "unten" (-y) in einen Raum und zurück.
# ----------------------------------------------------------------------------------------------------------------
async def simulate(cfg: dict, cmds: Commands) -> None:
    emit({"type": "account", "access_token": "simulation", "user_id": "simulation"})
    emit({"type": "status", "status": "ok", "message": "Simulation"})
    emit({"type": "devices", "devices": [{"did": "sim", "name": "Simulierter Roboter", "model": "Simulation", "supported": True}],
          "selected": "sim"})
    snapshot = Snapshot()
    snapshot.update(available=True, state="docked", battery=100, error=None, area=0, time=0,
                    pos={"x": 0, "y": 0, "a": 270}, charger={"x": 0, "y": 0, "a": 270})
    asyncio.create_task(emit_loop(snapshot))

    # Bahn: aus dem Dock nach -y, dann in Schlangenlinien durch ein Rechteck von 2,4 m (x) mal 2,0 m (y nach unten)
    path = [(0, 0), (0, -700)]
    for row in range(5):
        y = -700 - row * 400
        xs = (-1000, 1400) if row % 2 == 0 else (1400, -1000)
        path += [(xs[0], y), (xs[1], y)]
    path += [(0, -700), (0, 0)]
    segments = []
    for a, b in zip(path, path[1:]):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length:
            segments.append((a, b, length))
    total = sum(s[2] for s in segments)

    def point_at(distance: float):
        for a, b, length in segments:
            if distance <= length:
                t = distance / length
                heading = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
                return int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(heading) % 360
            distance -= length
        return 0, 0, 270

    speed = 300.0  # mm/s
    stop = asyncio.create_task(cmds.next())
    while True:
        # im Dock warten (und laden)
        for _ in range(8):
            snapshot.update(state="docked", pos={"x": 0, "y": 0, "a": 270}, battery=100)
            if stop.done():
                return
            await asyncio.sleep(1)
        travelled = 0.0
        started = time.monotonic()
        while travelled < total:
            if stop.done():
                return
            travelled = (time.monotonic() - started) * speed
            x, y, a = point_at(min(travelled, total - 1))
            returning = travelled > total - 1400
            elapsed = int(time.monotonic() - started)
            snapshot.update(state="returning" if returning else "cleaning", pos={"x": x, "y": y, "a": a},
                            battery=max(20, 100 - elapsed // 8), area=int(elapsed * 0.12), time=elapsed)
            await asyncio.sleep(1)


# ----------------------------------------------------------------------------------------------------------------
# Echter Betrieb mit deebot-client
# ----------------------------------------------------------------------------------------------------------------
async def real(cfg: dict, cmds: Commands) -> None:
    try:
        import aiohttp
        from deebot_client.api_client import ApiClient
        from deebot_client.authentication import Authenticator, create_rest_config
        from deebot_client.device import Device
        from deebot_client.events import (
            AvailabilityEvent,
            BatteryEvent,
            ErrorEvent,
            PositionsEvent,
            StateEvent,
            StatsEvent,
        )
        from deebot_client.exceptions import (
            ApiError,
            AuthenticationError,
            DeviceVerificationRequiredError,
            InvalidAuthenticationError,
            InvalidVerificationCodeError,
        )
        from deebot_client.models import AccountCredentials
        from deebot_client.mqtt_client import MqttClient, create_mqtt_config
        from deebot_client.util import md5
    except Exception as exc:  # Bibliothek fehlt oder passt nicht zum Python
        emit({"type": "fatal", "kind": "library", "message": f"deebot-client nicht nutzbar: {type(exc).__name__}: {exc}"})
        return

    country = str(cfg.get("country") or "DE").upper()
    email = str(cfg.get("email") or "")
    account = cfg.get("account") or None
    password_hash = cfg.get("password_hash") or ""
    if not email or not (account or password_hash):
        emit({"type": "fatal", "kind": "auth", "message": "E-Mail und Passwort fehlen"})
        return

    session = aiohttp.ClientSession()
    auth = Authenticator(
        create_rest_config(session, device_id=cfg["device_id"], alpha_2_country=country),
        email,
        password_hash,
        account_credentials=AccountCredentials(access_token=account["access_token"], user_id=account["user_id"])
        if account
        else None,
    )

    async def on_account(credentials) -> None:
        emit({"type": "account", "access_token": credentials.access_token, "user_id": credentials.user_id})

    auth.subscribe_account_credentials(on_account)

    mqtt = None
    device = None
    try:
        emit({"type": "status", "status": "login", "message": "Anmeldung bei ECOVACS"})
        while True:
            try:
                await auth.authenticate()
                break
            except DeviceVerificationRequiredError:
                # neue Geräte-Kennung: ECOVACS schickt einen Code per E-Mail
                emit({"type": "status", "status": "verify_required",
                      "message": "ECOVACS hat einen Bestätigungscode an deine E-Mail-Adresse geschickt"})
                await auth.request_device_verification_code()
                verified = False
                while not verified:
                    command = await cmds.next("verify", "resend")
                    if command.get("cmd") == "stop":
                        return
                    if command.get("cmd") == "resend":
                        await auth.request_device_verification_code()
                        emit({"type": "status", "status": "verify_required", "message": "Code erneut gesendet"})
                        continue
                    try:
                        await auth.verify_device(str(command.get("code", "")))
                        verified = True
                    except InvalidVerificationCodeError:
                        emit({"type": "status", "status": "verify_required",
                              "message": "Der Code ist falsch oder abgelaufen - bitte erneut eingeben"})
                break

        emit({"type": "status", "status": "connecting", "message": "Suche den Roboter"})
        devices = await ApiClient(auth).get_devices()
        listing = [{"did": d.api["did"], "name": d.api.get("nick") or d.api.get("name") or "",
                    "model": d.api.get("deviceName") or d.api.get("class") or "", "supported": True} for d in devices.mqtt]
        listing += [{"did": d.get("did", ""), "name": d.get("nick") or d.get("name") or "",
                     "model": d.get("deviceName") or d.get("class") or "", "supported": False} for d in devices.xmpp + devices.not_supported]
        info = next((d for d in devices.mqtt if d.api["did"] == cfg.get("selected")), None) or (devices.mqtt[0] if devices.mqtt else None)
        emit({"type": "devices", "devices": listing, "selected": info.api["did"] if info else None})
        if info is None:
            emit({"type": "fatal", "kind": "unsupported",
                  "message": "Kein unterstützter Roboter im Konto gefunden" if not listing else "Der Roboter wird von der Bibliothek nicht unterstützt"})
            return

        device = Device(info, auth)
        mqtt = MqttClient(create_mqtt_config(device_id=cfg["device_id"], country=country), auth)
        snapshot = Snapshot()

        async def on_battery(event) -> None:
            snapshot.update(battery=int(event.value))

        async def on_state(event) -> None:
            snapshot.update(state=STATE_NAMES.get(int(event.state), str(event.state)))

        async def on_error(event) -> None:
            snapshot.update(error=None if not event.code else {"code": int(event.code), "text": event.description})

        async def on_stats(event) -> None:
            snapshot.update(area=event.area, time=event.time)

        async def on_availability(event) -> None:
            snapshot.update(available=bool(event.available))

        async def on_positions(event) -> None:
            found = {}
            for position in event.positions:
                kind = str(position.type).upper()
                key = "pos" if "DEEBOT" in kind else "charger" if "CHARGER" in kind else None
                if key:
                    found[key] = {"x": int(position.x), "y": int(position.y), "a": int(position.a)}
            snapshot.update(**found)

        await device.initialize(mqtt)
        device.events.subscribe(BatteryEvent, on_battery)
        device.events.subscribe(StateEvent, on_state)
        device.events.subscribe(ErrorEvent, on_error)
        device.events.subscribe(StatsEvent, on_stats)
        device.events.subscribe(AvailabilityEvent, on_availability)
        device.events.subscribe(PositionsEvent, on_positions)
        emit({"type": "status", "status": "ok", "message": ""})
        asyncio.create_task(emit_loop(snapshot))

        stop = asyncio.create_task(cmds.next())
        ticks = 0
        while not stop.done():
            active = snapshot.data["state"] in ("cleaning", "returning")
            device.events.request_refresh(PositionsEvent)
            if active:
                device.events.request_refresh(StatsEvent)
            elif ticks % 12 == 0:
                device.events.request_refresh(StateEvent)
                device.events.request_refresh(BatteryEvent)
            ticks += 1
            await asyncio.wait({stop}, timeout=4 if active else 5)
    except InvalidAuthenticationError as exc:
        emit({"type": "fatal", "kind": "auth", "message": f"Anmeldung abgelehnt: {exc}"})
    except AuthenticationError as exc:
        emit({"type": "fatal", "kind": "auth", "message": f"Anmeldung fehlgeschlagen: {exc}"})
    except (ApiError, OSError, TimeoutError) as exc:
        emit({"type": "fatal", "kind": "network", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        for step in (device.teardown() if device else None, mqtt.disconnect() if mqtt else None, auth.teardown(), session.close()):
            if step is None:
                continue
            try:
                await step
            except Exception:  # beim Aufräumen nichts mehr melden
                pass


async def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    commands = Commands()
    asyncio.create_task(commands.pump())
    try:
        first = await asyncio.wait_for(commands.next("start"), timeout=30)
    except TimeoutError:
        return
    if first.get("cmd") != "start":
        return
    try:
        if first.get("simulate") or os.environ.get("ECOVACS_SIMULATE"):
            await simulate(first, commands)
        else:
            await real(first, commands)
    except Exception as exc:  # unerwartet: dem Server melden, der den Prozess neu startet
        emit({"type": "fatal", "kind": "bug", "message": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        sys.stdout.flush()
        os._exit(0)  # das Warten auf stdin (Hintergrund-Thread) soll das Beenden nicht aufhalten
