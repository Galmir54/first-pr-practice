"""Heizkörper im Kinderzimmer, unter dem Fenster an der Nordwand (Öffnung "f1": x -3,86, z -5,15, Breite 1,14 m,
Brüstung 0,94 m, Wand 10 cm dick, Raum auf der +z-Seite, Innenseite der Wand also bei z = -5,10).

Doppelplatten-Heizkörper, ca. 90 x 52 x 8 cm, mit Konvektorgitter oben und Thermostatkopf rechts. Die Platten
haben die Animation "heat": rötlich, wenn der Thermostat des Raums (Prop.heat_room = "Kinderzimmer") gerade heizt
(Ally work_state Heat), sonst bläulich. Maße geschätzt.

Aufruf: py -I scripts/seed_kinderzimmer_heizkoerper.py http://host:8000   (ersetzt nur das eigene Prop)
"""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")

XC = -3.86  # Mitte des Fensters
HALF = 0.45
X0, X1 = XC - HALF, XC + HALF
Z_WALL = -5.10  # Innenseite der Nordwand
Y0, Y1 = 0.14, 0.66  # unter der Fensterbank (0,94 m)

parts = []


def box(x0, x1, z0, z1, y0, y1, mat="white", **kw):
    parts.append(dict(x0=round(x0, 3), x1=round(x1, 3), z0=round(z0, 3), z1=round(z1, 3),
                      y0=round(y0, 3), y1=round(y1, 3), mat=mat, **kw))


# zwei Platten hintereinander (vorn größer), dazwischen ein dunkler Spalt
box(X0, X1, Z_WALL + 0.012, Z_WALL + 0.040, Y0, Y1, "gray", anim="heat")
box(X0 + 0.01, X1 - 0.01, Z_WALL + 0.040, Z_WALL + 0.048, Y0 + 0.02, Y1 - 0.02, "black")
box(X0, X1, Z_WALL + 0.048, Z_WALL + 0.076, Y0, Y1, "gray", anim="heat")
# Konvektorgitter oben, Seitenblenden
box(X0 + 0.005, X1 - 0.005, Z_WALL + 0.012, Z_WALL + 0.078, Y1, Y1 + 0.015, "black")
for sx in (X0 - 0.008, X1):
    box(sx, sx + 0.008, Z_WALL + 0.012, Z_WALL + 0.078, Y0 + 0.005, Y1 + 0.01, "white")
# senkrechte Sicken in der Frontplatte (dünne dunkle Streifen)
n = 6
for k in range(1, n):
    x = X0 + (X1 - X0) * k / n
    box(x - 0.003, x + 0.003, Z_WALL + 0.076, Z_WALL + 0.079, Y0 + 0.03, Y1 - 0.03, "black")
# Thermostatkopf rechts (Ally), Ventil darunter
parts.append(dict(x0=round(X1, 3), x1=round(X1 + 0.085, 3), z0=round(Z_WALL + 0.02, 3), z1=round(Z_WALL + 0.07, 3),
                  y0=round(Y0 + 0.28, 3), y1=round(Y0 + 0.33, 3), mat="white", shape="cyl", axis="x"))
box(X1, X1 + 0.02, Z_WALL + 0.035, Z_WALL + 0.055, Y0 + 0.05, Y0 + 0.28, "chrome")

prop = dict(id="kinderzimmer_heizkoerper", name="Heizkörper Kinderzimmer", parts=parts, heat_room="Kinderzimmer")


def req(method, url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())


existing = req("GET", base + "/api/floorplan/props")["props"]
keep = [{k: v for k, v in p.items() if k not in ("on", "power_w", "run")} for p in existing if p["id"] != prop["id"]]
out = req("PUT", base + "/api/floorplan/props", {"props": keep + [prop]})
print({p["id"]: len(p["parts"]) for p in out["props"]})
