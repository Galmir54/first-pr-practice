"""Aktuelles Wetter für den Grundriss (Open-Meteo, ohne Schlüssel).

Es wird nur ein grober Ort (auf 0,1° gerundet, ca. 10 km) an den Wetterdienst geschickt. Der Server
holt höchstens alle 15 Minuten neu, egal wie viele Geräte den Grundriss offen haben.
"""

import os
import time

import httpx

CACHE_SECONDS = 15 * 60
RETRY_SECONDS = 2 * 60
# Standardort: Raum Mainz (wie die Müllabfuhr-Termine). Mit ENERGY_LAT/ENERGY_LON änderbar.
DEFAULT_LAT = 49.99
DEFAULT_LON = 8.27

_cache: dict = {"at": 0.0, "key": None, "data": None}
_last_failure = 0.0


def default_location() -> tuple[float, float]:
    try:
        return float(os.environ["ENERGY_LAT"]), float(os.environ["ENERGY_LON"])
    except (KeyError, ValueError):
        return DEFAULT_LAT, DEFAULT_LON


def classify(code: int, precipitation: float) -> tuple[str, str]:
    """WMO-Wettercode -> (Art, deutscher Text). Art: clear|partly|cloudy|fog|rain|snow|thunder."""
    if code == 0:
        return "clear", "Klar"
    if code in (1, 2):
        return "partly", "Teils bewölkt"
    if code == 3:
        return "cloudy", "Bedeckt"
    if code in (45, 48):
        return "fog", "Nebel"
    if code in (51, 53, 55, 56, 57):
        return "rain", "Nieselregen"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        strong = code in (65, 67, 82) or precipitation >= 4
        return "rain", "Starker Regen" if strong else "Regen"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow", "Schnee"
    if code in (95, 96, 99):
        return "thunder", "Gewitter"
    return "cloudy", "Bewölkt"


def _round_location(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, 1), round(lon, 1)


async def get_weather(lat: float | None = None, lon: float | None = None) -> dict:
    global _last_failure
    if lat is None or lon is None:
        lat, lon = default_location()
    lat, lon = _round_location(lat, lon)
    key = (lat, lon)
    now = time.monotonic()
    if _cache["data"] and _cache["key"] == key and now - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]
    if now - _last_failure < RETRY_SECONDS:
        return _cache["data"] if _cache["data"] and _cache["key"] == key else {"ok": False, "lat": lat, "lon": lon}
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weather_code,cloud_cover,wind_speed_10m,precipitation,is_day",
                    "timezone": "auto",
                    "forecast_days": 1,
                },
            )
        resp.raise_for_status()
        cur = resp.json()["current"]
        kind, label = classify(int(cur.get("weather_code", 3)), float(cur.get("precipitation") or 0))
        data = {
            "ok": True,
            "lat": lat,
            "lon": lon,
            "temp_c": round(float(cur["temperature_2m"]), 1),
            "code": int(cur.get("weather_code", 3)),
            "kind": kind,
            "label": label,
            "cloud": int(cur.get("cloud_cover") or 0),
            "wind_kmh": round(float(cur.get("wind_speed_10m") or 0), 1),
            "precip_mm": round(float(cur.get("precipitation") or 0), 1),
            "is_day": bool(cur.get("is_day", 1)),
            "fetched_at": time.time(),
        }
    except Exception:
        _last_failure = now
        if _cache["data"] and _cache["key"] == key:
            return {**_cache["data"], "stale": True}
        return {"ok": False, "lat": lat, "lon": lon}
    _cache.update(at=now, key=key, data=data)
    return data
