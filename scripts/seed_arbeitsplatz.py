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
box(-1.40, -1.16, NZ, 0.95, TOP0, TOP1)
# Verlängerung zur Tür hin (gehört zum Schreibtisch): beige gesprenkelte Platte auf Alubeinen,
# endet kurz vor dem Türrahmen (Tür t8 beginnt bei x -0.83)
box(-1.16, -0.90, NZ, 0.95, TOP0, TOP1 + 0.002, "chip")
for lx, lz in [(-1.14, 0.92), (-0.93, 0.92), (-0.93, 0.28)]:
    box(lx - 0.018, lx + 0.018, lz - 0.018, lz + 0.018, 0, TOP0, "chrome")
# Beine (dünne weiße Rohre) an den freien Ecken
for lx, lz in [(-1.43, 1.67), (-1.43, 0.92)]:
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

# Regal mit Schiffsmodellen an der Westwand (nach Foto): Rückwand aus weiß lasierten Latten, drei Bretter,
# darauf Flugzeugträger (oben), Kreuzer (Mitte), Zerstörer und U-Boot (unten). Maßstab aus dem Foto
# geschätzt: 1 Pixel = 0,614 mm, linke Kante an der Schranktür (z 1,88), Bug zeigt zum Schrank (+z).
SX = WX + 0.07  # Mitte der Bretter (Tiefe 0,14 m)
LIFT = 0.26  # Regal höher gehängt: das unterste Brett hängt über den Monitoren (Oberkante Monitor 1,27 m)


def zpx(px):  # Bildpixel (waagerecht) -> z in Metern
    return 1.88 - (px - 325) * 0.000614


def ypx(py):  # Bildpixel (senkrecht) -> Höhe über dem Boden in Metern
    return 1.10 + LIFT + (1330 - py) * 0.000614


# Rückwand und Latten
box(WX, WX + 0.012, 1.03, 1.87, 1.19 + LIFT, 1.81 + LIFT, "wood")
box(WX, WX + 0.012, 1.15, 1.80, 1.09 + LIFT, 1.20 + LIFT, "wood")
for py0, py1, p0, p1 in ((235, 290, 495, 1525), (620, 680, 495, 1515), (690, 745, 495, 1520), (750, 810, 495, 1515)):
    box(WX + 0.012, WX + 0.022, zpx(p1), zpx(p0), ypx(py1), ypx(py0), "wood")
SHELVES = ((1.594 + LIFT, 305, 1445), (1.272 + LIFT, 345, 1500), (1.109 + LIFT, 350, 1495))  # Oberkante, linke/rechte Kante (px)
for top, p0, p1 in SHELVES:
    box(WX + 0.012, WX + 0.14, zpx(p1), min(zpx(p0), 1.87), top - 0.016, top, "wood")

CUR = {"y": 0.0}


def bx(zc, w, l, y0, y1, mat, dx=0.0):
    box(SX + dx - w / 2, SX + dx + w / 2, zc - l / 2, zc + l / 2, CUR["y"] + y0, CUR["y"] + y1, mat)


def hull(zb, zs, y0, y1, beam, mat, n=12, bow_start=0.6, bow_tip=0.08):
    """Rumpfschicht mit spitzem Bug und leicht schmalerem Heck, aus n Quadern entlang z."""
    length = zb - zs
    for i in range(n):
        t = (i + 0.5) / n
        if t < 0.12:
            f = 0.7 + 0.3 * t / 0.12
        elif t < bow_start:
            f = 1.0
        else:
            f = 1 - (1 - bow_tip) * ((t - bow_start) / (1 - bow_start)) ** 1.3
        z0, z1 = zs + length * i / n, zs + length * (i + 1) / n
        box(SX - beam * f / 2, SX + beam * f / 2, z0, z1, CUR["y"] + y0, CUR["y"] + y1, mat)


def carrier(top):
    CUR["y"] = top
    bx(1.50, 0.05, 0.20, 0.0, 0.04, "gray")  # Ständer
    zb, zs = 1.855, 1.14
    hull(zb - 0.03, zs + 0.02, 0.040, 0.061, 0.050, "rust")
    hull(zb, zs, 0.061, 0.086, 0.070, "gray")
    hull(zb - 0.02, zs, 0.086, 0.092, 0.090, "ship", bow_start=0.8, bow_tip=0.3)  # Flugdeck
    bx(1.54, 0.030, 0.15, 0.092, 0.115, "gray", 0.026)  # Insel
    bx(1.52, 0.020, 0.035, 0.115, 0.135, "gray", 0.026)  # Schornstein
    bx(1.62, 0.008, 0.012, 0.092, 0.180, "gray", 0.026)  # Mast
    bx(1.62, 0.022, 0.006, 0.150, 0.158, "gray", 0.026)


def cruiser(top):
    CUR["y"] = top
    bx(1.505, 0.040, 0.19, 0.0, 0.04, "hull")  # Holzständer
    zb, zs = 1.818, 1.136
    hull(zb - 0.03, zs + 0.02, 0.040, 0.063, 0.040, "rust")
    hull(zb, zs, 0.063, 0.089, 0.056, "gray")
    bx(1.60, 0.030, 0.40, 0.089, 0.093, "hull")  # Deck-Holzbelag
    bx(1.631, 0.030, 0.045, 0.089, 0.108, "ship")  # Turm A
    bx(1.552, 0.034, 0.050, 0.089, 0.157, "ship")  # Brückenturm
    bx(1.500, 0.024, 0.040, 0.089, 0.147, "gray")  # Schornstein
    bx(1.420, 0.034, 0.090, 0.089, 0.110, "ship")  # Achteraufbau
    bx(1.435, 0.008, 0.010, 0.110, 0.224, "ship")  # Großmast
    bx(1.435, 0.024, 0.005, 0.190, 0.196, "ship")
    bx(1.330, 0.030, 0.045, 0.089, 0.105, "ship")  # Turm C
    bx(1.265, 0.030, 0.045, 0.089, 0.105, "ship")  # Turm D


def destroyer(top):
    CUR["y"] = top
    bx(1.37, 0.030, 0.10, 0.0, 0.03, "gray")
    zb, zs = 1.57, 1.158
    hull(zb - 0.02, zs + 0.02, 0.030, 0.045, 0.030, "rust")
    hull(zb, zs, 0.045, 0.070, 0.040, "gray")
    bx(1.53, 0.020, 0.030, 0.070, 0.082, "ship")  # Bugkanone
    bx(1.465, 0.026, 0.070, 0.070, 0.095, "ship")  # Brücke
    bx(1.45, 0.006, 0.008, 0.095, 0.115, "ship")  # Mast
    for zc in (1.370, 1.335):
        bx(zc, 0.014, 0.020, 0.070, 0.100, "gray")  # Schornsteine
    bx(1.290, 0.020, 0.030, 0.070, 0.082, "ship")
    bx(1.250, 0.020, 0.030, 0.070, 0.082, "ship")


def uboat(top):
    CUR["y"] = top
    hull(1.806, 1.594, 0.004, 0.026, 0.026, "ship", n=10, bow_start=0.7, bow_tip=0.2)
    bx(1.70, 0.014, 0.026, 0.026, 0.044, "ship")  # Turm
    bx(1.70, 0.012, 0.070, 0.0, 0.003, "brass", 0.03)  # Messingschild davor


carrier(SHELVES[0][0])
cruiser(SHELVES[1][0])
destroyer(SHELVES[2][0])
uboat(SHELVES[2][0])

prop = dict(id="arbeitsplatz", name="Arbeitsplatz Schlafzimmer", parts=parts,
            cutout=dict(x0=-2.12, x1=-1.12, z0=0.20, z1=1.76))

def req(method, url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())

# nur das eigene Prop ersetzen, andere (z.B. die Küche) bleiben erhalten
existing = req("GET", base + "/api/floorplan/props")["props"]
keep = [{k: v for k, v in p.items() if k not in ("on", "power_w")} for p in existing if p["id"] != prop["id"]]
req("PUT", base + "/api/floorplan/props", {"props": keep + [prop]})

tvs = [t for t in req("GET", base + "/api/floorplan/tvs")["tvs"] if t["id"] != "tv2"]
tvs = [{k: v for k, v in t.items() if k not in ("on", "power_w", "source")} for t in tvs]
tvs.append(dict(id="tv2", name="Fernseher Schlafzimmer (LG)", x_front=-1.925, x_back=-0.975, z_min=0.29, z_max=0.34,
                tv_z=0.0, tv_width=0.95, tv_height=0.56, soundbar=False, mount="wall", facing="+z", yaw=45, arm=0.75,
                wall_x=round(WX + D[0] * 0.75, 3), wall_z=round(NZ + D[1] * 0.75, 3), y_bottom=1.32,
                device_id=5, on_watts=150, ip=None))  # Steckdose "Computer und Fernseher": ab 150 W gilt er als an
out = req("PUT", base + "/api/floorplan/tvs", {"tvs": tvs})
print("parts", len(parts), "tvs", [t["id"] for t in out["tvs"]])
