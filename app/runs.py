"""Programmläufe von Haushaltsgeräten (Waschmaschine, Trockner, Spülmaschine) aus dem Stromverlauf.

Ein Lauf beginnt, sobald die Steckdose mindestens `on_watts` zieht, und endet, wenn sie länger
als GAP_S darunter bleibt (Pausen im Programm, z.B. Einweichen, werden so überbrückt).

Die Restlaufzeit wird aus früheren Läufen desselben Geräts geschätzt: Von den Läufen, die länger
dauerten als der aktuelle bisher, werden die ähnlichsten gewählt (gleicher Energieverbrauch bis zu
diesem Zeitpunkt = gleiches Programm) und deren mittlere Gesamtdauer abzüglich der verstrichenen
Zeit ergibt den Rest. Ohne genug Vorläufe gibt es keine Schätzung, nur die Laufzeit bisher.
"""

import statistics
import threading
import time
from datetime import datetime, timedelta

from . import db, poller

GAP_S = 6 * 60  # so lange darf die Leistung unter der Schwelle bleiben, ohne dass der Lauf endet
MIN_RUN_S = 8 * 60  # kürzere Ausschläge gelten nicht als Programmlauf (nur für "fertig" und die Historie)
HISTORY_DAYS = 60
MAX_SAMPLE_DT_S = 10 * 60  # größere Lücken in den Messwerten werden nicht als Verbrauch gezählt
FINISHED_SHOW_S = 90 * 60  # so lange wird "fertig" angezeigt
MIN_HISTORY_RUNS = 3
STATE_TTL_S = 8
HISTORY_TTL_S = 600
CURRENT_LOOKBACK_H = 36

_lock = threading.Lock()
_history_cache: dict[int, tuple[float, list[dict]]] = {}
_state_cache: dict[tuple[int, float], tuple[float, dict]] = {}


def _epoch(ts: str) -> float | None:
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (TypeError, ValueError):
        return None


def _load_rows(device_id: int, since: datetime) -> list[tuple[float, float]]:
    with db.db_cursor() as cur:
        cur.execute(
            "SELECT ts, power_w FROM readings WHERE device_id = ? AND ts >= ? AND power_w IS NOT NULL ORDER BY ts",
            (device_id, since.isoformat()),
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        t = _epoch(r["ts"])
        if t is not None:
            out.append((t, float(r["power_w"])))
    return out


def segment_runs(rows: list[tuple[float, float]], on_watts: float) -> list[dict]:
    """Zerlegt (zeit, watt)-Messwerte in Läufe. Jeder Lauf: start, end (= letzter aktiver Messwert),
    energy_wh und profile = [(sekunden seit Start, kumulierte Wh)]."""
    runs: list[dict] = []
    cur: dict | None = None
    prev: tuple[float, float] | None = None
    for t, p in rows:
        active = p >= on_watts
        if cur is not None and t - cur["end"] > GAP_S:
            runs.append(cur)
            cur = None
        if active:
            if cur is None:
                cur = {"start": t, "end": t, "energy_wh": 0.0, "profile": [(0.0, 0.0)]}
            else:
                dt = t - prev[0] if prev else 0.0
                if dt <= MAX_SAMPLE_DT_S:
                    cur["energy_wh"] += (p + prev[1]) / 2 * dt / 3600
                cur["end"] = t
                cur["profile"].append((t - cur["start"], cur["energy_wh"]))
        elif cur is not None:
            # Pause im Programm: Verbrauch läuft weiter, das Ende bleibt der letzte aktive Messwert
            dt = t - prev[0] if prev else 0.0
            if dt <= MAX_SAMPLE_DT_S:
                cur["energy_wh"] += (p + prev[1]) / 2 * dt / 3600
        prev = (t, p)
    if cur is not None:
        runs.append(cur)
    return runs


def _energy_at(run: dict, offset_s: float) -> float:
    prof = run["profile"]
    if offset_s <= 0 or len(prof) == 1:
        return 0.0
    for i in range(1, len(prof)):
        if prof[i][0] >= offset_s:
            t0, e0 = prof[i - 1]
            t1, e1 = prof[i]
            if t1 == t0:
                return e1
            return e0 + (e1 - e0) * (offset_s - t0) / (t1 - t0)
    return prof[-1][1]


def _history(device_id: int, on_watts: float, before: float) -> list[dict]:
    """Abgeschlossene frühere Läufe (Dauer >= MIN_RUN_S), die vor `before` endeten."""
    now = time.monotonic()
    with _lock:
        cached = _history_cache.get(device_id)
    if cached and now - cached[0] < HISTORY_TTL_S:
        runs = cached[1]
    else:
        since = datetime.now() - timedelta(days=HISTORY_DAYS)
        runs = [r for r in segment_runs(_load_rows(device_id, since), on_watts) if r["end"] - r["start"] >= MIN_RUN_S]
        with _lock:
            _history_cache[device_id] = (now, runs)
    return [r for r in runs if r["end"] < before]


def estimate_remaining(elapsed_s: float, energy_so_far: float, history: list[dict]) -> dict | None:
    """Schätzt die Restzeit. None, wenn zu wenig Vergleichsläufe vorliegen."""
    if len(history) < MIN_HISTORY_RUNS:
        return None
    longer = [r for r in history if (r["end"] - r["start"]) > elapsed_s + 30]
    if not longer:
        return {"longer_than_usual": True}

    def distance(r: dict) -> float:
        e = _energy_at(r, elapsed_s)
        return abs(e - energy_so_far) / (max(e, energy_so_far) + 5.0)

    ranked = sorted(longer, key=distance)
    limit = distance(ranked[0]) * 2 + 0.12  # nur Läufe mit ähnlichem Verbrauch = gleiches Programm
    best = [r for r in ranked if distance(r) <= limit][:5]
    durations = sorted(r["end"] - r["start"] for r in best)
    total = statistics.median(durations)
    spread = (durations[-1] - durations[0]) / total if total else 1.0
    return {
        "remaining_s": int(max(60.0, total - elapsed_s)),
        "confidence": "sicher" if len(best) >= 3 and spread < 0.2 else "grob",
    }


def run_state(device_id: int, on_watts: float = 8.0, name: str = "") -> dict:
    """Aktueller Zustand des Geräts: idle | running | done (mit Laufzeit, Restzeit, Verbrauch)."""
    key = (device_id, float(on_watts))
    mono = time.monotonic()
    with _lock:
        cached = _state_cache.get(key)
    if cached and mono - cached[0] < STATE_TTL_S:
        return cached[1]
    state = _compute_state(device_id, float(on_watts))
    with _lock:
        _state_cache[key] = (mono, state)
    return state


def _compute_state(device_id: int, on_watts: float) -> dict:
    now = time.time()
    rows = _load_rows(device_id, datetime.now() - timedelta(hours=CURRENT_LOOKBACK_H))
    reading = poller.latest.get(device_id)
    if reading and reading.get("power_w") is not None:
        t = _epoch(reading.get("ts"))
        if t is not None and (not rows or t > rows[-1][0]):
            rows.append((t, float(reading["power_w"])))
    runs = segment_runs(rows, on_watts)
    last = runs[-1] if runs else None
    idle = {"state": "idle"}
    if last is None:
        return idle

    ended_ago = now - last["end"]
    duration = last["end"] - last["start"]
    if ended_ago <= GAP_S:
        # läuft (oder macht gerade eine kurze Pause)
        power = float(reading["power_w"]) if reading and reading.get("power_w") is not None else None
        elapsed = now - last["start"]
        out = {
            "state": "running",
            "paused": power is not None and power < on_watts,
            "started_at": datetime.fromtimestamp(last["start"]).isoformat(timespec="seconds"),
            "elapsed_s": int(elapsed),
            "energy_wh": round(last["energy_wh"], 1),
            "remaining_s": None,
            "finish_at": None,
            "progress": None,
            "confidence": None,
            "runs_known": 0,
        }
        history = _history(device_id, on_watts, last["start"])
        out["runs_known"] = len(history)
        est = estimate_remaining(elapsed, last["energy_wh"], history)
        if est:
            if est.get("longer_than_usual"):
                out["longer_than_usual"] = True
            else:
                out["remaining_s"] = est["remaining_s"]
                out["confidence"] = est["confidence"]
                out["finish_at"] = datetime.fromtimestamp(now + est["remaining_s"]).isoformat(timespec="seconds")
                out["progress"] = round(elapsed / (elapsed + est["remaining_s"]), 3)
        return out

    if duration >= MIN_RUN_S and ended_ago <= FINISHED_SHOW_S:
        return {
            "state": "done",
            "started_at": datetime.fromtimestamp(last["start"]).isoformat(timespec="seconds"),
            "ended_at": datetime.fromtimestamp(last["end"]).isoformat(timespec="seconds"),
            "since_s": int(ended_ago),
            "duration_s": int(duration),
            "energy_wh": round(last["energy_wh"], 1),
        }
    return idle
