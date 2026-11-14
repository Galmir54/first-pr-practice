"""Müllabfuhr-Erinnerung.

Holt die Abfuhrtermine für einen Ort aus der öffentlichen Schnittstelle der KAW
(Kommunale Abfallwirtschaft Mainz und Mainz-Bingen AöR), speichert sie lokal und
berechnet, ob gerade eine Erinnerung fällig ist:

- am Vortag ab WASTE_REMIND_FROM_HOUR Uhr ("Morgen ist Müllabfuhr")
- am Abfuhrtag bis WASTE_REMIND_UNTIL_HOUR Uhr ("Heute ist Müllabfuhr")

Eine Erinnerung bleibt so lange fällig, bis sie quittiert wird (`ack`). Alles, was
den Wohnort verrät, liegt nur in der lokalen Datenbank, nicht im Quellcode.
"""
import asyncio
import logging
import time
from datetime import date, datetime, timedelta

import httpx

from . import config, db

logger = logging.getLogger("energy.waste")

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

_options_cache: dict | None = None
_options_cached_at = 0.0
_OPTIONS_TTL_SECONDS = 24 * 3600


# --- Einstellungen ---

def _get_setting(cur, key: str) -> str | None:
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    return row["value"] if row else None


def get_config() -> dict:
    with db.db_cursor() as cur:
        district_id = _get_setting(cur, "waste.district_id")
        city_id = _get_setting(cur, "waste.city_id")
        return {
            "configured": district_id is not None and city_id is not None,
            "district_id": int(district_id) if district_id else None,
            "city_id": int(city_id) if city_id else None,
            "district_name": _get_setting(cur, "waste.district_name"),
            "city_name": _get_setting(cur, "waste.city_name"),
            "last_sync": _get_setting(cur, "waste.last_sync"),
        }


def save_config(district_id: int, city_id: int, district_name: str, city_name: str) -> None:
    with db.db_cursor(commit=True) as cur:
        for key, value in (
            ("waste.district_id", str(district_id)),
            ("waste.city_id", str(city_id)),
            ("waste.district_name", district_name),
            ("waste.city_name", city_name),
        ):
            cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        # Termine eines anderen Ortes sind wertlos.
        cur.execute("DELETE FROM waste_dates")
        cur.execute("DELETE FROM settings WHERE key = 'waste.last_sync'")


# --- Abruf der KAW-Daten ---

async def fetch_options(client: httpx.AsyncClient | None = None) -> dict:
    """Abfuhrbezirke und Orte (für die Auswahl in den Einstellungen), 24 h zwischengespeichert."""
    global _options_cache, _options_cached_at
    if _options_cache is not None and time.monotonic() - _options_cached_at < _OPTIONS_TTL_SECONDS:
        return _options_cache

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        resp = await client.get(f"{config.WASTE_API_URL}/settings", params={"Filter.IncludeStaticObjects": "true"})
        resp.raise_for_status()
        data = resp.json()["Data"]
    finally:
        if own_client:
            await client.aclose()

    _options_cache = {
        "districts": [{"id": d["Id"], "name": d["Name"]} for d in data["Districts"] if d["Id"] > 0],
        "cities": [
            {"id": c["Id"], "name": c["Name"], "district_id": c["DistrictId"]} for c in data["Cities"] if c["Id"] > 0
        ],
    }
    _options_cached_at = time.monotonic()
    return _options_cache


async def _fetch_dates(
    client: httpx.AsyncClient, district_id: int, city_id: int, date_from: date, date_to: date
) -> list[tuple[str, int, str]]:
    params = {
        "Filter.SearchTerm": "",
        "Filter.DistrictId": district_id,
        "Filter.CityId": city_id,
        "Filter.StreetId": 0,
        "Filter.DateFrom": date_from.isoformat(),
        "Filter.DateTo": date_to.isoformat(),
        "Filter.WasteTypeIds": ",".join(str(t) for t in config.WASTE_TYPE_IDS),
        "Filter.ShowGroupedResults": "false",
        "Filter.RecordsPerPage": 999999,
        "Filter.CurrentPage": 1,
        "Filter.SortColumn": "Date",
    }
    resp = await client.get(f"{config.WASTE_API_URL}/collectiondates", params=params)
    resp.raise_for_status()
    body = resp.json()
    if body.get("ReturnCode") not in (0, 990):
        raise RuntimeError(f"KAW-Schnittstelle meldet Fehler: {body.get('Message') or body.get('ReturnCode')}")

    rows = []
    for item in body.get("DataList") or []:
        day = datetime.strptime(item["Date"], "%d.%m.%Y").date()
        rows.append((day.isoformat(), int(item["WasteTypeId"]), item["WasteTypeName"]))
    return rows


def _store_dates(rows: list[tuple[str, int, str]], date_from: date) -> None:
    with db.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM waste_dates WHERE date >= ?", (date_from.isoformat(),))
        cur.executemany(
            "INSERT OR REPLACE INTO waste_dates (date, waste_type_id, waste_type) VALUES (?, ?, ?)", rows
        )
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('waste.last_sync', ?)",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        # Alte Quittierungen aufräumen.
        cur.execute("DELETE FROM waste_ack WHERE date < ?", ((date_from - timedelta(days=30)).isoformat(),))


async def sync_once() -> bool:
    """Holt die Termine neu. Gibt False zurück, wenn der Abruf fehlschlug (dann bleibt der alte Stand)."""
    cfg = await asyncio.to_thread(get_config)
    if not cfg["configured"]:
        return True

    today = date.today()
    date_to = date(today.year + 1, 12, 31)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            rows = await _fetch_dates(client, cfg["district_id"], cfg["city_id"], today, date_to)
    except Exception as exc:
        logger.warning("Müllabfuhr-Termine konnten nicht geladen werden: %s", exc)
        return False

    await asyncio.to_thread(_store_dates, rows, today)
    logger.info("Müllabfuhr: %d Termine für %s aktualisiert", len(rows), cfg["city_name"])
    return True


async def waste_loop() -> None:
    await asyncio.sleep(15)  # erst den Server hochfahren lassen
    while True:
        try:
            ok = await sync_once()
        except Exception:
            logger.exception("Unerwarteter Fehler beim Abruf der Müllabfuhr-Termine")
            ok = False
        await asyncio.sleep(config.WASTE_SYNC_INTERVAL_HOURS * 3600 if ok else 900)


# --- Auswertung ---

def grouped_dates(from_date: date, to_date: date) -> list[dict]:
    """Termine im Zeitraum, je Tag zusammengefasst und nach Abfallarten gefiltert."""
    with db.db_cursor() as cur:
        placeholders = ",".join("?" for _ in config.WASTE_TYPE_IDS)
        cur.execute(
            f"SELECT date, waste_type_id, waste_type FROM waste_dates "
            f"WHERE date >= ? AND date <= ? AND waste_type_id IN ({placeholders}) ORDER BY date, waste_type_id",
            (from_date.isoformat(), to_date.isoformat(), *config.WASTE_TYPE_IDS),
        )
        rows = cur.fetchall()
        cur.execute("SELECT date FROM waste_ack WHERE date >= ?", (from_date.isoformat(),))
        acked = {row["date"] for row in cur.fetchall()}

    groups: dict[str, dict] = {}
    for row in rows:
        day = date.fromisoformat(row["date"])
        group = groups.setdefault(
            row["date"],
            {
                "date": row["date"],
                "weekday": WEEKDAYS[day.weekday()],
                "date_display": day.strftime("%d.%m."),
                "types": [],
                "acked": row["date"] in acked,
            },
        )
        group["types"].append({"id": row["waste_type_id"], "name": row["waste_type"]})
    return list(groups.values())


def compute_reminder(now: datetime) -> dict:
    """Aktuell fällige Erinnerung (oder None) und der nächste Termin."""
    today = now.date()
    groups = grouped_dates(today, today + timedelta(days=45))

    due = None
    for group in groups:
        day = date.fromisoformat(group["date"])
        if group["acked"]:
            continue
        if day == today and now.hour < config.WASTE_REMIND_UNTIL_HOUR:
            due = {**group, "label": "Heute", "phase": "morning"}
        elif day == today + timedelta(days=1) and now.hour >= config.WASTE_REMIND_FROM_HOUR:
            due = {**group, "label": "Morgen", "phase": "evening"}
        if due:
            break

    next_group = None
    for group in groups:
        day = date.fromisoformat(group["date"])
        if day > today or (day == today and now.hour < config.WASTE_REMIND_UNTIL_HOUR):
            next_group = group
            break

    return {"due": due, "next": next_group}


def ack(day_iso: str) -> None:
    date.fromisoformat(day_iso)  # ValueError bei ungültigem Datum
    with db.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT OR REPLACE INTO waste_ack (date, acked_at) VALUES (?, ?)",
            (day_iso, datetime.now().isoformat(timespec="seconds")),
        )
