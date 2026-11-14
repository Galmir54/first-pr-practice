"""Arbeitsplatz im Schlafzimmer (Nordwest-Ecke) als Prop + Wand-Fernseher.
Alle Maße geschätzt aus Foto und STL-Block (Fläche x -2,10..-1,20, z 0,26..1,70, Höhe 0,8 m).
Aufruf: py scripts/seed_arbeitsplatz.py http://host:8000
"""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")

WX = -2.10   # Innenseite Westwand
NZ = 0.25    # Innenseite Nordwand
parts = []


def box(x0, x1, z0, z1, y0, y1, mat="white", rot=0):
    parts.append(dict(x0=round(x0, 3), x1=round(x1, 3), z0=round(z0, 3), z1=round(z1, 3),
                      y0=round(y0, 3), y1=round(y1, 3), mat=mat, rot=rot))


def oriented(cx, cz, w, d, y0, y1, mat, rot):
    """Quader um die Mitte (cx, cz): Breite w entlang z', Tiefe d entlang x' (vor Drehung)."""
    box(cx - d / 2, cx + d / 2, cz - w / 2, cz + w / 2, y0, y1, mat, rot)


TOP0, TOP1 = 0.73, 0.76
# weiße Eck-Platte: Arm an der Westwand + Arm an der Nordwand
box(WX, -1.40, NZ, 1.70, TOP0, TOP1)
box(-1.40, -1.00, NZ, 0.95, TOP0, TOP1)
# Beine (dünne weiße Rohre) an den freien Ecken
for lx, lz in [(-1.43, 1.67), (-1.03, 0.92), (-1.43, 0.92)]:
    box(lx - 0.02, lx + 0.02, lz - 0.02, lz + 0.02, 0, TOP0, "white")

# drei Monitore (schwarz) mit Fuß
def monitor(cx, cz, w, rot):
    oriented(cx, cz, 0.24, 0.18, TOP1, TOP1 + 0.012, "black", rot)  # Fußplatte
    oriented(cx, cz, w, 0.035, TOP1 + 0.14, TOP1 + 0.14 + 0.37, "black", rot)  # Bildschirm
    oriented(cx, cz, 0.05, 0.03, TOP1 + 0.01, TOP1 + 0.14, "black", rot)  # Standrohr

import math
# Ecke (WX, NZ); Diagonale d zeigt in den Raum (45 Grad), p liegt quer dazu
D = (math.sqrt(0.5), math.sqrt(0.5))
P = (math.sqrt(0.5), -math.sqrt(0.5))
mx, mz = WX + D[0] * 0.85, NZ + D[1] * 0.85
SPACING = 0.34
for off, ang in ((-1, 23), (0, 45), (1, 67)):
    monitor(mx + P[0] * SPACING * 1.4 * off, mz + P[1] * SPACING * 1.4 * off, 0.54, -ang)

# Regal mit Schiffsmodellen an der Westwand über dem Schreibtisch
box(WX, WX + 0.02, 1.16, 1.86, 1.05, 1.95, "wood")
for y in (1.10, 1.38, 1.66, 1.94):
    box(WX + 0.02, WX + 0.16, 1.16, 1.86, y - 0.01, y + 0.01, "wood")
    box(WX + 0.045, WX + 0.115, 1.22, 1.80, y + 0.01, y + 0.07, "ship")

prop = dict(id="arbeitsplatz", name="Arbeitsplatz Schlafzimmer", parts=parts,
            cutout=dict(x0=-2.12, x1=-1.12, z0=0.20, z1=1.76))

def req(method, url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())

req("PUT", base + "/api/floorplan/props", {"props": [prop]})

tvs = [t for t in req("GET", base + "/api/floorplan/tvs")["tvs"] if t["id"] != "tv2"]
tvs = [{k: v for k, v in t.items() if k not in ("on", "power_w", "source")} for t in tvs]
tvs.append(dict(id="tv2", name="Fernseher Schlafzimmer (LG)", x_front=-1.925, x_back=-0.975, z_min=0.29, z_max=0.34,
                tv_z=0.0, tv_width=0.95, tv_height=0.56, soundbar=False, mount="wall", facing="+z", yaw=45, arm=0.75,
                wall_x=round(WX + D[0] * 0.75, 3), wall_z=round(NZ + D[1] * 0.75, 3), y_bottom=1.32,
                device_id=5, on_watts=150, ip=None))  # Steckdose "Computer und Fernseher": ab 150 W gilt er als an
out = req("PUT", base + "/api/floorplan/tvs", {"tvs": tvs})
print("parts", len(parts), "tvs", [t["id"] for t in out["tvs"]])
