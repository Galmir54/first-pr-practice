import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ENERGY_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "energy.db"

STATIC_DIR = BASE_DIR / "static"

POLL_INTERVAL_SECONDS = float(os.environ.get("ENERGY_POLL_INTERVAL", "2"))
HTTP_TIMEOUT_SECONDS = float(os.environ.get("ENERGY_HTTP_TIMEOUT", "5"))
