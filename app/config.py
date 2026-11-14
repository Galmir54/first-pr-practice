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

# Müllabfuhr-Erinnerung (Termine der KAW Mainz und Mainz-Bingen AöR)
WASTE_API_URL = os.environ.get(
    "ENERGY_WASTE_API_URL", "https://abfallkalender-api-lk.kaw-mainz-bingen.de/public/frontend"
)
# Abfallarten, an die erinnert wird (KAW-IDs: 1 Restmüll, 2 Biomüll, 3 Gelbe Tonne,
# 4 Papiertonne, 5 Sperrmüll, 6 Problemmüllbus). Sperrmüll/Problemmüll werden nicht
# an die Straße gestellt und lösen daher kein Popup aus.
WASTE_TYPE_IDS = tuple(int(x) for x in os.environ.get("ENERGY_WASTE_TYPE_IDS", "1,2,3,4").split(",") if x.strip())
# Popup ab dieser Uhrzeit am Vortag ...
WASTE_REMIND_FROM_HOUR = int(os.environ.get("ENERGY_WASTE_REMIND_FROM_HOUR", "16"))
# ... und am Abfuhrtag bis zu dieser Uhrzeit (die Abholung beginnt früh morgens).
WASTE_REMIND_UNTIL_HOUR = int(os.environ.get("ENERGY_WASTE_REMIND_UNTIL_HOUR", "8"))
WASTE_SYNC_INTERVAL_HOURS = float(os.environ.get("ENERGY_WASTE_SYNC_HOURS", "12"))
