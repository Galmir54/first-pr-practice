"""Ladestation des ECOVACS-Saugroboters (Omni-Station) im Schlafzimmer, an der Ostwand im freien Streifen.

Lage (Nutzer hat sie im Plan eingekreist, 16.11.): an der Ostwand (Wand innen x 1,31), in der Höhe z ca. 0,9..1,3,
Rückseite an der Wand, Front nach Westen (-x). Der Roboter dockt in der Mitte der unteren Bucht an: Mitte x 1,03 /
z 1,08 (= dock_x/dock_z der Kalibrierung in app/ecovacs.py). Maße ungefähr nach den Omni-Stationen (ca. 42 x 50 x 52 cm),
nicht gemessen: untere Bucht mit Seitenwänden, darüber Wasserbehälter/Staubbeutel-Block mit Deckel.

Bodenhöhe: Das 3D-Modell hatte dort durch einen groben Bettklotz einen schrägen "Boden" (bis 0,36 m); seit
flattenFloor() in static/floorplan.js (16.11.) ist er eben (ca. 0,107 m), die Station steht direkt auf dem Boden
(LIFT 0). Der Roboter folgt im Browser der echten Bodenhöhe.

Aufruf: py -I scripts/seed_ecovacs_station.py http://host:8000   (ersetzt nur das eigene Prop)
"""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")

XW = 1.305  # Rückseite an der Ostwand (Wand innen x 1,31)
ZC = 1.08  # Mitte der Station entlang der Wand
LIFT = 0.0  # Sockelhöhe über FLOOR_TOP (0,10 m); der Boden ist eben, also kein Sockel nötig

parts = []


def box(u0, u1, d0, d1, y0, y1, mat="white"):
    """u = entlang der Wand (z), d = Abstand von der Wand nach Westen (x), y = Höhe über dem Sockel."""
    parts.append(dict(x0=round(XW - d1, 3), x1=round(XW - d0, 3), z0=round(ZC + u0, 3), z1=round(ZC + u1, 3),
                      y0=round(LIFT + y0, 3), y1=round(LIFT + y1, 3), mat=mat))


W = 0.21  # halbe Breite
# Sockel unter allem (nur wenn der Boden wieder uneben sein sollte): füllt den Raum zwischen Boden und Auffahrplatte
if LIFT > 0:
    parts.append(dict(x0=round(XW - 0.505, 3), x1=round(XW, 3), z0=round(ZC - W, 3), z1=round(ZC + W, 3), y0=0.0,
                      y1=round(LIFT, 3), mat="gray"))
# Auffahrplatte und die Bucht, in die der Roboter fährt: Seitenwände und Rückwand
box(-W, W, 0.0, 0.505, 0.0, 0.02, "gray")
box(-W, -W + 0.03, 0.0, 0.435, 0.02, 0.15, "white")
box(W - 0.03, W, 0.0, 0.435, 0.02, 0.15, "white")
box(-W + 0.03, W - 0.03, 0.0, 0.085, 0.02, 0.15, "white")
# Aufbau über der Bucht: Wasserbehälter und Staubbeutel, vorn eine getönte Scheibe und eine Anzeige
box(-W, W, 0.0, 0.395, 0.15, 0.52, "white")
box(-W, W, 0.0, 0.395, 0.52, 0.545, "gray")  # Deckel
box(-W + 0.04, W - 0.04, 0.395, 0.40, 0.19, 0.46, "glass")  # Scheibe
box(-0.05, 0.05, 0.395, 0.40, 0.47, 0.50, "black")  # Anzeige

prop = dict(id="ecovacs_station", name="Saugroboter-Station", parts=parts)


def req(method, url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())


existing = req("GET", base + "/api/floorplan/props")["props"]
keep = [{k: v for k, v in p.items() if k not in ("on", "power_w", "run")} for p in existing if p["id"] != prop["id"]]
out = req("PUT", base + "/api/floorplan/props", {"props": keep + [prop]})
print({p["id"]: len(p["parts"]) for p in out["props"]})
