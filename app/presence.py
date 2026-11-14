"""Erkennt, ob ein Handy im Heimnetz ist.

Handys antworten im Standby oft nicht auf Ping, halten aber das WLAN und beantworten
ARP-Anfragen. Darum wird pro Prüfung:
1. ein Ping geschickt (Antwort -> anwesend),
2. ein UDP-Paket an Port 5353 (mDNS) geschickt; das zwingt den Pi, die MAC-Adresse
   per ARP neu zu erfragen,
3. kurz gewartet und in der Nachbartabelle (`ip neigh`) nachgesehen, ob das Handy
   geantwortet hat (Zustand REACHABLE).

Ein einzelner Fehlschlag heißt noch nicht "weg": die Absenkung greift erst, wenn ein
Handy eine einstellbare Zeit lang gar nicht mehr gesehen wurde (siehe heating.py).
Voraussetzung: das Handy hat im Router eine feste IP (DHCP-Reservierung).
"""
import asyncio
import ipaddress
import shutil
import socket
import subprocess
import sys

_IS_WINDOWS = sys.platform.startswith("win")


def valid_ip(ip: str) -> bool:
    try:
        ipaddress.IPv4Address(ip)
        return True
    except ValueError:
        return False


def _run_sync(args: tuple[str, ...], timeout: float) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    return proc.returncode, proc.stdout.decode(errors="replace")


async def _run(*args: str, timeout: float = 4) -> tuple[int, str]:
    # In einem Thread statt mit asyncio-Subprozessen: die gehen unter Windows mit dem
    # Event-Loop von `uvicorn --reload` nicht (NotImplementedError).
    return await asyncio.to_thread(_run_sync, args, timeout)


async def _ping(ip: str) -> bool:
    args = ["ping", "-n", "1", "-w", "1000", ip] if _IS_WINDOWS else ["ping", "-c", "1", "-W", "1", ip]
    code, out = await _run(*args)
    # Windows meldet auch "Zielhost nicht erreichbar" mit Exit-Code 0; echte Antworten
    # enthalten "TTL=".
    return code == 0 and (not _IS_WINDOWS or "TTL=" in out.upper())


def _poke_udp(ip: str) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(b"\x00", (ip, 5353))
    except OSError:
        pass


async def _neighbor_reachable(ip: str) -> bool:
    ip_cmd = shutil.which("ip") or "/usr/sbin/ip"
    code, out = await _run(ip_cmd, "neigh", "show", ip)
    if code != 0:
        return False
    return "REACHABLE" in out.split()


async def is_present(ip: str) -> bool:
    if not valid_ip(ip):
        return False
    if await _ping(ip):
        return True
    if _IS_WINDOWS:
        return False
    _poke_udp(ip)
    await asyncio.sleep(2)
    return await _neighbor_reachable(ip)
