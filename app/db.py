import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

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
    phase_c_w REAL
);
CREATE INDEX IF NOT EXISTS idx_readings_device_ts ON readings(device_id, ts);

CREATE TABLE IF NOT EXISTS tariffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utility_type TEXT NOT NULL DEFAULT 'strom',
    grundpreis_monat REAL NOT NULL,
    arbeitspreis_ct_kwh REAL NOT NULL,
    valid_from TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Default-Tarif, damit die Kostenberechnung sofort nutzbar ist.
DEFAULT_GRUNDPREIS_MONAT = 15.53
DEFAULT_ARBEITSPREIS_CT_KWH = 16.47


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


@contextmanager
def db_cursor(commit: bool = False):
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        finally:
            cur.close()


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT COUNT(*) AS c FROM tariffs")
        if cur.fetchone()["c"] == 0:
            cur.execute(
                "INSERT INTO tariffs (utility_type, grundpreis_monat, arbeitspreis_ct_kwh, valid_from) "
                "VALUES (?, ?, ?, ?)",
                ("strom", DEFAULT_GRUNDPREIS_MONAT, DEFAULT_ARBEITSPREIS_CT_KWH, datetime.now().isoformat()),
            )
