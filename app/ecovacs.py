"""ECOVACS-Saugroboter (Deebot) im Grundriss: Status und Position zum Ansehen (nur Lesen).

Es gibt keine offizielle lokale Schnittstelle, der Weg geht über die ECOVACS-Cloud mit dem eigenen Konto. Die Bibliothek
dafür (deebot-client, wie in Home Assistant) braucht seit dem neuen Login (2026) Python 3.14 oder neuer.

Stand dieser Datei: nur Umgebungsauskunft, damit klar ist, was auf dem Pi läuft, bevor etwas installiert wird.
"""

import platform
import shutil
import sys


def environment() -> dict:
    """Welche Python-Umgebung läuft hier? (keine Geheimnisse, nur Versionen und Pfade)"""
    usage = shutil.disk_usage("/") if sys.platform != "win32" else shutil.disk_usage("C:\\")
    return {
        "python": platform.python_version(),
        "python_ok_for_deebot_client": sys.version_info >= (3, 14),
        "machine": platform.machine(),
        "system": f"{platform.system()} {platform.release()}",
        "uv": shutil.which("uv"),
        "python3_14": shutil.which("python3.14"),
        "free_disk_mb": round(usage.free / 1e6),
    }
