import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ENERGY_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "energy.db"

STATIC_DIR = BASE_DIR / "static"

POLL_INTERVAL_SECONDS = float(os.environ.get("ENERGY_POLL_INTERVAL", "2"))

# Die Live-Ansicht nutzt jeden Poll-Wert (im Speicher), in die Datenbank wird aber nur
# alle STORE_INTERVAL_SECONDS ein Messwert geschrieben - sonst wächst sie bei 2s-Takt
# um ~45.000 Zeilen pro Gerät und Tag.
STORE_INTERVAL_SECONDS = float(os.environ.get("ENERGY_STORE_INTERVAL", "30"))

# Wartung: Rohmesswerte, die älter als THIN_AFTER_DAYS sind, werden auf einen Wert je
# THIN_BUCKET_SECONDS ausgedünnt (Zählerstände bleiben exakt, nur die Dichte sinkt).
THIN_AFTER_DAYS = float(os.environ.get("ENERGY_THIN_AFTER_DAYS", "2"))
THIN_BUCKET_SECONDS = int(os.environ.get("ENERGY_THIN_BUCKET_SECONDS", "300"))
HTTP_TIMEOUT_SECONDS = float(os.environ.get("ENERGY_HTTP_TIMEOUT", "5"))
