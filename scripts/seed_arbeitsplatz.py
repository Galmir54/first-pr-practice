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
SHIP_X = WX + 0.085  # Mitte der Regalbretter (Tiefe 0,14 m)


def ship(zc, length, kind, yb):
    """Kleines Modellschiff aus Quadern auf einem Brett (Bug zeigt nach +z, yb = Oberkante Brett)."""
    L = length

    def b(dz, w, l, y0, y1, mat):
        box(SHIP_X - w / 2, SHIP_X + w / 2, zc + dz - l / 2, zc + dz + l / 2, yb + y0, yb + y1, mat)

    hull = "ship" if kind == "steamer" else "hull"
    # Rumpf: Kiel, Mittelteil, Deck, spitzer Bug und Heckaufbau
    b(0, 0.030, 0.72 * L, 0.000, 0.012, hull)
    b(0, 0.050, 0.90 * L, 0.012, 0.026, hull)
    b(0, 0.062, L, 0.026, 0.040, hull)
    b(0.5 * L + 0.012, 0.034, 0.05, 0.026, 0.040, hull)
    b(0.5 * L + 0.034, 0.014, 0.04, 0.032, 0.040, hull)
    b(0, 0.064, 0.96 * L, 0.033, 0.037, "red" if kind != "sloop" else "white")  # Zierstreifen
    b(-0.40 * L, 0.060, 0.18 * L, 0.040, 0.062, hull)  # Heckaufbau
    if kind == "steamer":
        b(-0.05 * L, 0.050, 0.34 * L, 0.040, 0.075, "white")
        b(0.18 * L, 0.040, 0.14 * L, 0.040, 0.066, "white")
        b(0.05 * L, 0.040, 0.10 * L, 0.075, 0.095, "white")  # Brücke
        for dz in (-0.12 * L, -0.02 * L):
            b(dz, 0.022, 0.03, 0.075, 0.120, "black")  # Schornsteine
            b(dz, 0.024, 0.032, 0.108, 0.114, "red")
        b(0.30 * L, 0.006, 0.006, 0.040, 0.100, "black")
        return

    def mast(dz, h):
        b(dz, 0.007, 0.007, 0.040, h, "wood" if kind != "sloop" else "white")

    def square_sails(dz, h, mat):
        low_top = 0.062 + 0.55 * (h - 0.062)
        b(dz + 0.010, 0.074, 0.022, 0.062, low_top, mat)
        b(dz + 0.008, 0.052, 0.018, low_top + 0.008, h - 0.004, mat)
        b(dz + 0.004, 0.082, 0.006, low_top - 0.002, low_top + 0.002, "wood")  # Rah

    if kind == "tall":
        for dz, h in ((-0.26 * L, 0.17), (0.0, 0.21), (0.26 * L, 0.16)):
            mast(dz, h)
            square_sails(dz, h, "sail")
        b(0.5 * L + 0.045, 0.006, 0.07, 0.036, 0.046, "wood")  # Klüverbaum
    elif kind == "schooner":
        for dz, h in ((-0.12 * L, 0.20), (0.22 * L, 0.18)):
            mast(dz, h)
            for i in range(7):  # Gaffelsegel hinter dem Mast, nach oben schmaler
                y0 = 0.05 + i * (h - 0.06) / 7
                f = 1 - i / 8.0
                b(dz - 0.005 - 0.075 * f, 0.004, 0.15 * f, y0, y0 + (h - 0.06) / 7, "red")
        b(0.5 * L + 0.045, 0.006, 0.07, 0.036, 0.046, "wood")
    else:  # sloop: ein Mast, dreieckiges Groß- und Vorsegel aus gestapelten Streifen
        mast(0.0, 0.24)
        for i in range(8):
            y0 = 0.05 + i * 0.022
            f = 1 - i / 8.0
            b(-0.02 - 0.09 * f, 0.004, 0.18 * f, y0, y0 + 0.022, "sail")  # Großsegel hinter dem Mast
            b(0.02 + 0.07 * (1 - i / 9.0), 0.004, 0.14 * (1 - i / 9.0), y0, y0 + 0.022, "sail")  # Fock


for y, kind, length in ((1.10, "steamer", 0.50), (1.38, "sloop", 0.40), (1.66, "tall", 0.52), (1.94, "schooner", 0.46)):
    box(WX + 0.02, WX + 0.16, 1.16, 1.86, y - 0.01, y + 0.01, "wood")
    ship(1.51, length, kind, y + 0.01)

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
