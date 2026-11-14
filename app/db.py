import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from . import config

# Jeder Thread bekommt seine eigene SQLite-Verbindung. Im WAL-Modus blockieren sich
# lesende und schreibende Verbindungen nicht gegenseitig, daher braucht es keine
# globale Sperre mehr (die hatte den ganzen Server lahmgelegt, sobald eine einzelne
# Abfrage lange dauerte).
_local = threading.local()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    utility_type TEXT NOT NULL DEFAULT 'strom',
    device_type TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    power_w REAL,
    energy_wh_total REAL,
    phase_a_w REAL,
    phase_b_w REAL,
    phase_c_w REAL,
    phase_meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_readings_device_ts ON readings(device_id, ts);

CREATE TABLE IF NOT EXISTS tariffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utility_type TEXT NOT NULL DEFAULT 'strom',
    name TEXT,
    grundpreis_monat REAL NOT NULL,
    arbeitspreis_ct_kwh REAL NOT NULL,
    valid_from TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Höchste gemessene Leistung je Gerät, laufend mitgeführt (statt bei jeder Anfrage
-- per MAX() über alle Messwerte zu scannen).
CREATE TABLE IF NOT EXISTS peak_stats (
    device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    peak_w REAL,
    reset_at TEXT
);

-- Kleiner Schlüssel/Wert-Speicher für den Fortschritt der Wartungsläufe.
CREATE TABLE IF NOT EXISTS maintenance (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Allgemeine Einstellungen (u.a. Ort für die Müllabfuhr-Erinnerung).
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Abfuhrtermine (Zwischenspeicher der KAW-Daten, damit die Erinnerung auch ohne
-- Internet funktioniert) und welche Termine bereits als erledigt quittiert wurden.
CREATE TABLE IF NOT EXISTS waste_dates (
    date TEXT NOT NULL,
    waste_type_id INTEGER NOT NULL,
    waste_type TEXT NOT NULL,
    PRIMARY KEY (date, waste_type_id)
);
CREATE TABLE IF NOT EXISTS waste_ack (
    date TEXT PRIMARY KEY,
    acked_at TEXT NOT NULL
);
"""

# Default-Tarif, damit die Kostenberechnung sofort nutzbar ist.
DEFAULT_GRUNDPREIS_MONAT = 15.53
DEFAULT_ARBEITSPREIS_CT_KWH = 16.47


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(config.DB_PATH), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


@contextmanager
def db_cursor(commit: bool = False):
    conn = get_conn()
    cur = conn.cursor()
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def _ensure_column(cur: sqlite3.Cursor, table: str, column: str, column_def: str) -> None:
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in cur.fetchall()}
    if column not in existing:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")


def init_db() -> None:
    conn = get_conn()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    with db_cursor(commit=True) as cur:
        # Nachträglich hinzugekommene Spalten: CREATE TABLE IF NOT EXISTS legt sie bei
        # bereits existierenden Datenbanken (z.B. auf dem Pi) nicht automatisch an.
        _ensure_column(cur, "readings", "phase_meta", "TEXT")
        _ensure_column(cur, "tariffs", "name", "TEXT")

        cur.execute("SELECT COUNT(*) AS c FROM tariffs")
        if cur.fetchone()["c"] == 0:
            cur.execute(
                "INSERT INTO tariffs (utility_type, grundpreis_monat, arbeitspreis_ct_kwh, valid_from) "
                "VALUES (?, ?, ?, ?)",
                ("strom", DEFAULT_GRUNDPREIS_MONAT, DEFAULT_ARBEITSPREIS_CT_KWH, datetime.now().isoformat()),
            )
