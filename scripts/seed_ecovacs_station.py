"""Ladestation des ECOVACS-Saugroboters (Omni-Station) im Schlafzimmer, rechts hinter der Tür t8 an der Nordwand.

Lage (gemessen): Nordwand innen z 0,18, Tür t8 x -0,83..-0,09, Bett erst ab z 1,16; die Station steht an der Wand
östlich der Tür, Front nach Süden (+z). Der Roboter dockt in der Mitte der unteren Bucht an: Mitte x 0,22 / z 0,46
(= dock_x/dock_z der Kalibrierung in app/ecovacs.py). Maße ungefähr nach den Omni-Stationen (ca. 42 x 50 x 52 cm),
nicht gemessen: untere Bucht für den Roboter mit Seitenwänden, darüber Wasserbehälter/Staubbeutel-Block mit Deckel.

Aufruf: py -I scripts/seed_ecovacs_station.py http://host:8000   (ersetzt nur das eigene Prop)
"""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")

X0, X1 = 0.01, 0.43  # Breite 42 cm, Mitte x 0,22
ZW = 0.185  # Rückseite an der Wand (Innenseite z 0,18)
ZF = 0.69  # Vorderkante des Sockels (Tiefe ca. 50 cm)

parts = []


def box(x0, x1, z0, z1, y0, y1, mat="white", **kw):
    parts.append(dict(x0=round(x0, 3), x1=round(x1, 3), z0=round(z0, 3), z1=round(z1, 3),
                      y0=round(y0, 3), y1=round(y1, 3), mat=mat, **kw))


# Sockel (Auffahrplatte) und die Bucht, in die der Roboter fährt: Seitenwände und Rückwand
box(X0, X1, ZW, ZF, 0.0, 0.02, "gray")
box(X0, X0 + 0.03, ZW, 0.62, 0.02, 0.15, "white")
box(X1 - 0.03, X1, ZW, 0.62, 0.02, 0.15, "white")
box(X0 + 0.03, X1 - 0.03, ZW, 0.27, 0.02, 0.15, "white")
# Aufbau über der Bucht: Wasserbehälter und Staubbeutel, vorn eine getönte Scheibe und eine Anzeige
box(X0, X1, ZW, 0.58, 0.15, 0.52, "white")
box(X0, X1, ZW, 0.58, 0.52, 0.545, "gray")  # Deckel
box(X0 + 0.04, X1 - 0.04, 0.58, 0.585, 0.19, 0.46, "glass")  # Scheibe
box(0.17, 0.27, 0.58, 0.585, 0.47, 0.50, "black")  # Anzeige

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
