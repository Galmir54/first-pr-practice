"""Küche (Raum x -0,40..1,60, z -4,90..-1,30) als Props nach den Fotos.

Zwei Zeilen, die sich gegenüberstehen (alle Maße geschätzt aus Fotos und den Klötzen im STL):
  Westwand (x -0,40, Fronten zeigen nach +x), von der Tür (Süden) nach Norden:
     Waschmaschine, Spülmaschine, Spüle (schwarz) unter dem Oberschrank, Mikrowelle/Toaster,
     Kaffeemaschine, Vorratsschrank; über der Waschmaschine die Gastherme.
  Ostwand (x 1,60, Fronten zeigen nach -x), von der Tür nach Norden:
     Hochschrank mit Backofen, Schubladen mit Induktionskochfeld, Dunstabzug, Oberschränke,
     Trockner am Fenster-Ende.
  Am Fenster (Nordwand): Mülleimer (der Heizkörper steht in scripts/seed_heizkoerper.py).
Waschmaschine, Trockner und Spülmaschine sind eigene Props mit Shelly-Steckdose (device_id 2/3/4):
läuft das Gerät, leuchtet die Anzeige, dreht sich die Trommel und liegt ein Lichtschein davor.

Aufruf: py -I scripts/seed_kueche.py http://host:8000   (ersetzt nur die eigenen Props)
"""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
ON_WATTS = 8  # Steckdose zieht im Stand ~0 W


class Builder:
    def __init__(self):
        self.parts = []

    def box(self, x0, x1, z0, z1, y0, y1, mat="white", **kw):
        x0, x1 = sorted((x0, x1))
        z0, z1 = sorted((z0, z1))
        part = dict(x0=round(x0, 3), x1=round(x1, 3), z0=round(z0, 3), z1=round(z1, 3),
                    y0=round(y0, 3), y1=round(y1, 3), mat=mat)
        part.update(kw)
        self.parts.append(part)

    def cyl(self, axis, a0, a1, c1, c2, r, mat, **kw):
        """Zylinder: Achse `axis` von a0 bis a1, Mittelpunkt (c1, c2) in den beiden anderen Richtungen
        (x-Achse: y=c1, z=c2; y-Achse: x=c1, z=c2; z-Achse: x=c1, y=c2)."""
        a0, a1 = sorted((a0, a1))
        if axis == "x":
            self.box(a0, a1, c2 - r, c2 + r, c1 - r, c1 + r, mat, shape="cyl", axis="x", **kw)
        elif axis == "y":
            self.box(c1 - r, c1 + r, c2 - r, c2 + r, a0, a1, mat, shape="cyl", axis="y", **kw)
        else:
            self.box(c1 - r, c1 + r, a0, a1, c2 - r, c2 + r, mat, shape="cyl", axis="z", **kw)


def handle_w(b, zc, y, length=0.24, fx=0.22):
    """Griffstange an einer Front der Westzeile (zeigt nach +x)."""
    b.box(fx, fx + 0.025, zc - length / 2, zc + length / 2, y, y + 0.014, "chrome")


def handle_e(b, zc, y, length=0.24, fx=1.0):
    """Griffstange an einer Front der Ostzeile (zeigt nach -x)."""
    b.box(fx - 0.025, fx, zc - length / 2, zc + length / 2, y, y + 0.014, "chrome")


# ------------------------------------------------------------------------------------------------
# Westzeile (ohne Waschmaschine/Spülmaschine, die sind eigene Props)
# ------------------------------------------------------------------------------------------------
W = Builder()
Z_S, Z_N = -1.50, -4.30  # Südende (an der Tür) und Nordende der Westzeile
W.box(-0.40, 0.12, Z_S, Z_N, 0, 0.10, "black")  # Sockel
W.box(-0.40, 0.20, -2.70, Z_N, 0.10, 0.86, "white")  # Korpus Spüle + Mikrowellenschrank
W.box(-0.40, 0.28, Z_S, Z_N, 0.86, 0.90, "oak")  # Arbeitsplatte
W.box(-0.40, -0.385, Z_S, Z_N, 0.90, 1.45, "oaklight")  # Rückwand aus Holzdekor
for za, zb in ((-2.70, -3.15), (-3.15, -3.60), (-3.60, -3.95), (-3.95, -4.30)):
    W.box(0.20, 0.22, za - 0.003, zb + 0.003, 0.11, 0.855, "white")
    handle_w(W, (za + zb) / 2, 0.78)
# Spüle: Abtropffläche (Süden) und Becken (Norden), schwarz, mit Rillen und Ablaufstopfen
W.box(-0.12, 0.22, -2.72, -3.10, 0.90, 0.906, "black")
for zr in (-2.78, -2.84, -2.90, -2.96, -3.02):
    W.box(-0.10, 0.20, zr - 0.004, zr + 0.004, 0.906, 0.909, "ship")
W.box(-0.12, 0.22, -3.12, -3.58, 0.90, 0.906, "black")
W.cyl("y", 0.906, 0.912, 0.05, -3.35, 0.022, "chrome")
# Wandarmatur mit langem Schwenkauslauf
W.box(-0.40, -0.36, -3.34, -3.26, 1.04, 1.12, "chrome")
W.box(-0.36, 0.05, -3.31, -3.29, 1.10, 1.12, "chrome")
W.box(0.04, 0.06, -3.31, -3.29, 0.98, 1.12, "chrome")
# Oberschrank mit zwei Türen über Spüle/Spülmaschine, Holzseitenteil am Nordende
W.box(-0.40, -0.05, -2.30, -3.60, 1.45, 2.30, "white")
for za, zb in ((-2.30, -2.95), (-2.95, -3.60)):
    W.box(-0.05, -0.035, za - 0.003, zb + 0.003, 1.455, 2.295, "white")
    handle_w(W, (za + zb) / 2, 1.50, 0.34, fx=-0.035)
W.box(-0.40, -0.03, -3.60, -3.62, 1.43, 2.32, "oaklight")
# Gastherme (weißes Gehäuse) mit Abgasrohr zur Decke, links vom Oberschrank
W.box(-0.40, -0.05, -1.90, -2.28, 1.20, 1.95, "white")
W.box(-0.06, -0.045, -1.98, -2.20, 1.62, 1.80, "gray")
W.cyl("y", 1.95, 2.50, -0.30, -2.08, 0.045, "gray")
# Mikrowelle (weiß, schwarze Front) mit Toaster darauf, daneben die Kaffeemaschine
W.box(-0.25, 0.10, -3.62, -4.04, 0.90, 1.19, "white")
W.box(0.10, 0.104, -3.64, -3.92, 0.93, 1.16, "black")
W.box(0.10, 0.104, -3.94, -4.02, 0.93, 1.16, "gray")
W.box(-0.20, 0.00, -3.68, -3.96, 1.19, 1.37, "gray")
W.box(-0.30, 0.15, -4.05, -4.29, 0.90, 1.30, "black")
W.box(-0.10, 0.15, -4.05, -4.29, 0.90, 1.00, "gray")
# Vorratsschrank (alter Einbauschrank) in der Nordwestecke, zwei Türen mit Knauf
W.box(-0.40, 0.20, -4.90, -4.30, 0, 2.50, "white")
W.box(0.20, 0.22, -4.893, -4.307, 0.01, 1.19, "white")
W.box(0.20, 0.22, -4.893, -4.307, 1.22, 2.48, "white")
W.cyl("x", 0.22, 0.24, 1.15, -4.36, 0.015, "chrome")
W.cyl("x", 0.22, 0.24, 1.28, -4.36, 0.015, "chrome")

# ------------------------------------------------------------------------------------------------
# Ostzeile (ohne Trockner)
# ------------------------------------------------------------------------------------------------
E = Builder()
E.box(1.08, 1.60, -2.10, -4.30, 0, 0.10, "black")  # Sockel
# Hochschrank: Schubladen unten, Backofen in der Mitte, Tür oben, Holzseitenteil zum Nordende
E.box(1.00, 1.60, -2.10, -2.70, 0.10, 2.25, "white")
for y0, y1 in ((0.10, 0.47), (0.47, 0.855)):
    E.box(0.98, 1.00, -2.103, -2.697, y0 + 0.003, y1 - 0.003, "white")
    handle_e(E, -2.40, y1 - 0.08, 0.30)
E.box(0.975, 1.00, -2.12, -2.68, 0.88, 1.42, "black")  # Backofenfront
E.box(0.968, 0.975, -2.17, -2.63, 0.93, 1.29, "glass")
E.box(0.94, 0.97, -2.15, -2.65, 1.31, 1.33, "chrome")  # Griffstange mit Geschirrtuch
E.box(0.968, 0.975, -2.45, -2.35, 1.35, 1.38, "led")  # Anzeige
E.box(0.98, 1.00, -2.103, -2.697, 1.44, 2.245, "white")  # Tür oben
handle_e(E, -2.40, 1.50, 0.30)
E.box(1.00, 1.60, -2.70, -2.72, 0, 2.30, "oaklight")
# Unterschränke mit Kochfeld: zwei Spalten à drei Schubladen
E.box(1.00, 1.60, -2.72, -3.70, 0.10, 0.86, "white")
for za, zb in ((-2.72, -3.21), (-3.21, -3.70)):
    for y0, y1 in ((0.10, 0.34), (0.34, 0.58), (0.58, 0.855)):
        E.box(0.98, 1.00, za - 0.003, zb + 0.003, y0 + 0.003, y1 - 0.003, "white")
        handle_e(E, (za + zb) / 2, y1 - 0.07, 0.30)
E.box(0.98, 1.60, -2.72, -4.30, 0.86, 0.90, "oak")  # Arbeitsplatte (läuft über den Trockner)
E.box(1.595, 1.60, -2.72, -4.30, 0.90, 1.46, "tile")  # Fliesenspiegel
# Induktionskochfeld (AEG, schwarzes Glas, vier Zonen)
E.box(1.04, 1.56, -2.91, -3.49, 0.90, 0.906, "black")
for xc, zc in ((1.17, -3.05), (1.17, -3.35), (1.43, -3.05), (1.43, -3.35)):
    E.cyl("y", 0.906, 0.909, xc, zc, 0.075, "gray")
# Dunstabzug (schwarz mit Chromkante) und vier Oberschränke
E.box(1.12, 1.60, -2.75, -3.65, 1.38, 1.46, "black")
E.box(1.11, 1.12, -2.75, -3.65, 1.38, 1.46, "chrome")
E.box(1.25, 1.60, -2.72, -4.30, 1.46, 2.30, "white")
for k in range(4):
    za, zb = -2.72 - k * 0.395, -2.72 - (k + 1) * 0.395
    E.box(1.24, 1.25, za - 0.003, zb + 0.003, 1.465, 2.295, "white")
    handle_e(E, (za + zb) / 2, 1.52, 0.26, fx=1.24)
# Mülleimer am Fenster (Fotos 3 und 4). Der Heizkörper unter dem Fenster (mit Farbwechsel nach dem
# Thermostat) kommt aus scripts/seed_heizkoerper.py.
E.cyl("y", 0.0, 0.42, 0.50, -4.62, 0.17, "gray")
E.cyl("y", 0.42, 0.46, 0.50, -4.62, 0.18, "ship")


# ------------------------------------------------------------------------------------------------
# Geräte mit Shelly-Steckdose: Waschmaschine (2), Trockner (3), Spülmaschine (4)
# ------------------------------------------------------------------------------------------------
def machine(dev_id, z0, z1, front_x, direction, glow_mat, name, pid, body_x0, body_x1):
    """Frontlader mit Trommel. direction +1: Front zeigt nach +x (Westzeile), -1: nach -x (Ostzeile).
    front_x = Ebene der Front. Von der Wand nach außen: Ring (Chrom), schwarze Scheibe, Wäsche, Glas."""
    b = Builder()
    zc = (z0 + z1) / 2
    yc = 0.46
    b.box(body_x0, body_x1, z0, z1, 0.10, 0.86, "white")
    b.box(body_x0, body_x1, z0, z1, 0.0, 0.10, "black")

    def out(a, c):  # Abstand a..c von der Front nach außen -> x-Bereich
        return (front_x + direction * a, front_x + direction * c)

    b.cyl("x", *out(0, 0.012), yc, zc, 0.17, "chrome")
    b.cyl("x", *out(0.012, 0.016), yc, zc, 0.135, "black")
    for dy, dz, sy, sz, mat in ((0.03, 0.04, 0.09, 0.09, "blue"), (-0.05, -0.03, 0.08, 0.10, "red"),
                                (0.0, -0.07, 0.06, 0.07, "sail")):
        x0, x1 = out(0.016, 0.030)
        b.box(x0, x1, zc + dz - sz / 2, zc + dz + sz / 2, yc + dy - sy / 2, yc + dy + sy / 2, mat,
              anim="spin", axis="x", py=yc, pz=zc)
    b.cyl("x", *out(0.030, 0.036), yc, zc, 0.135, "glass")
    x0, x1 = out(0, 0.004)
    b.box(x0, x1, zc - 0.20, zc - 0.05, 0.78, 0.83, "black", anim="glow")  # Anzeige
    gx0, gx1 = front_x + direction * 0.012, front_x + direction * 0.55
    b.box(gx0, gx1, z0 + 0.02, z1 - 0.02, 0.012, 0.016, glow_mat, anim="show")  # Lichtschein am Boden
    return dict(id=pid, name=name, parts=b.parts, device_id=dev_id, on_watts=ON_WATTS)


def dishwasher(dev_id, z0, z1, front_x, name, pid):
    b = Builder()
    b.box(-0.40, front_x, z0, z1, 0.0, 0.10, "black")
    b.box(-0.40, 0.20, z0, z1, 0.10, 0.86, "white")
    b.box(0.20, front_x, z0 + 0.003, z1 - 0.003, 0.11, 0.855, "white")  # Front
    handle_w(b, (z0 + z1) / 2, 0.76, 0.40, fx=front_x)
    b.box(front_x, front_x + 0.004, z0 + 0.12, z1 - 0.12, 0.825, 0.845, "black", anim="glow")  # Anzeige
    b.box(front_x + 0.012, front_x + 0.55, z0 + 0.02, z1 - 0.02, 0.012, 0.016, "glowcyan", anim="show")
    return dict(id=pid, name=name, parts=b.parts, device_id=dev_id, on_watts=ON_WATTS)


props = [
    dict(id="kueche_west", name="Küche Westzeile", parts=W.parts,
         cutout=dict(x0=-0.38, x1=0.45, z0=-4.95, z1=-1.45)),
    dict(id="kueche_ost", name="Küche Ostzeile", parts=E.parts,
         cutout=dict(x0=1.25, x1=1.62, z0=-2.75, z1=-2.05)),
    machine(2, -1.50, -2.10, 0.22, +1, "glowblue", "Waschmaschine", "waschmaschine", -0.40, 0.22),
    dishwasher(4, -2.10, -2.70, 0.22, "Spülmaschine", "spuelmaschine"),
    machine(3, -3.70, -4.30, 1.00, -1, "glowamber", "Trockner", "trockner", 1.00, 1.60),
]


def req(method, url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())


mine = {p["id"] for p in props}
existing = req("GET", base + "/api/floorplan/props")["props"]
keep = [{k: v for k, v in p.items() if k not in ("on", "power_w", "run")} for p in existing if p["id"] not in mine]
out = req("PUT", base + "/api/floorplan/props", {"props": keep + props})
print({p["id"]: len(p["parts"]) for p in out["props"]})
