"""FDM-Drucker im Arbeitszimmer als Prop (Shelly-Steckdose "FDM Drucker", device_id 6).

Er steht auf dem vorhandenen Schreibtisch an der Ostwand (gegenüber der Tür), ungefähr in der Mitte.
Der Schreibtisch selbst ist schon im STL-Modell (Oberkante 0,84 m, x 4,05..4,58, z -2,85..-1,50) und
wird nicht ersetzt, das Arbeitszimmer bleibt sonst wie es ist.

Das Druckermodell ist unbekannt, deshalb eine allgemeine Bauform (Bettschieber im Stil Prusa/Ender, ca.
40 x 40 x 45 cm, Front zum Raum = -x): schwarzer Rahmen, Druckbett fährt nach vorn/hinten, der Druckkopf
fährt am Querträger hin und her, oben dreht sich eine rote Filamentspule. Läuft der Drucker (Steckdose
zieht ab ON_WATTS), bewegen sich Kopf, Bett und Spule, Anzeige und Kammerlicht leuchten.

Aufruf: py -I scripts/seed_drucker.py http://host:8000   (ersetzt nur das eigene Prop)
"""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
ON_WATTS = 20  # im Stand zieht die Steckdose ~0 W, ein Druck (Heizbett/Düse) deutlich mehr

DESK = 0.84  # Oberkante des Schreibtischs über dem Boden
LIFT = 0.012  # Der Drucker steht auf kleinen Füßen: darunter leuchtet die Statusfläche
TOP = DESK + LIFT  # Unterkante des Druckers
X0, X1 = 4.12, 4.52  # Tiefe (Front bei X0, zum Raum)
Z0, Z1 = -2.15, -1.75
XC, ZC = (X0 + X1) / 2, (Z0 + Z1) / 2

parts = []


def box(x0, x1, z0, z1, y0, y1, mat="black", **kw):
    parts.append(dict(x0=round(x0, 3), x1=round(x1, 3), z0=round(z0, 3), z1=round(z1, 3),
                      y0=round(TOP + y0, 3), y1=round(TOP + y1, 3), mat=mat, **kw))


# Statusleuchte unter dem Drucker (indirektes Licht): rot, solange er druckt, grün, wenn er fertig ist.
# Etwas größer als der Sockel, auf der Schreibtischplatte; dazu vier Füße unter dem Sockel.
parts.append(dict(x0=round(X0 - 0.045, 3), x1=round(X1 + 0.045, 3), z0=round(Z0 - 0.045, 3), z1=round(Z1 + 0.045, 3),
                  y0=DESK, y1=round(DESK + 0.004, 3), mat="led", anim="status"))
for fx in (X0 + 0.02, X1 - 0.05):
    for fz in (Z0 + 0.02, Z1 - 0.05):
        parts.append(dict(x0=round(fx, 3), x1=round(fx + 0.03, 3), z0=round(fz, 3), z1=round(fz + 0.03, 3),
                          y0=DESK, y1=round(TOP, 3), mat="black"))
# Sockel (Elektronik) und Rahmen
box(X0, X1, Z0, Z1, 0.0, 0.06)
box(X0 + 0.02, X1 - 0.02, Z0 + 0.02, Z1 - 0.02, 0.06, 0.075, "gray")
# zwei Säulen hinten, Querholm oben
box(4.40, 4.50, Z0, Z0 + 0.06, 0.075, 0.46)
box(4.40, 4.50, Z1 - 0.06, Z1, 0.075, 0.46)
box(4.40, 4.50, Z0, Z1, 0.40, 0.46)
# Querträger der X-Achse (Chromstange) mit Hub-Schlitten
box(4.34, 4.40, Z0 + 0.06, Z1 - 0.06, 0.20, 0.23)
box(4.30, 4.34, Z0 + 0.06, Z1 - 0.06, 0.205, 0.225, "chrome")
# Druckbett (fährt vor und zurück, Richtung x)
box(XC - 0.15, XC + 0.15, ZC - 0.15, ZC + 0.15, 0.075, 0.095, "black", anim="slide", axis="x", amp=0.05, speed=2.2)
box(XC - 0.14, XC + 0.14, ZC - 0.14, ZC + 0.14, 0.095, 0.103, "gray", anim="slide", axis="x", amp=0.05, speed=2.2)
# Druckkopf (fährt am Querträger entlang z)
box(4.24, 4.30, ZC - 0.045, ZC + 0.045, 0.17, 0.26, "gray", anim="slide", axis="z", amp=0.09, speed=3.4)
box(4.255, 4.285, ZC - 0.012, ZC + 0.012, 0.15, 0.17, "brass", anim="slide", axis="z", amp=0.09, speed=3.4)
box(4.225, 4.24, ZC - 0.03, ZC + 0.03, 0.19, 0.23, "blue", anim="slide", axis="z", amp=0.09, speed=3.4)
# Kammerlicht unter dem Querholm
box(4.41, 4.45, Z0 + 0.07, Z1 - 0.07, 0.385, 0.40, "led", anim="show")
# Anzeige vorn am Sockel
box(X0 - 0.03, X0, ZC - 0.08, ZC + 0.02, 0.012, 0.052, "black", anim="glow")
box(X0 - 0.03, X0, ZC + 0.04, ZC + 0.07, 0.015, 0.045, "gray")  # Drehknopf
# Filamentspule auf dem Querholm (Achse z), mit Haltearm; weiße Speichen zeigen die Drehung
SX, SY = 4.46, 0.56  # Mitte der Spule: x, Höhe über dem Schreibtisch
box(SX - 0.02, SX + 0.02, ZC - 0.04, ZC + 0.04, 0.46, SY, "black")
parts.append(dict(x0=round(SX - 0.10, 3), x1=round(SX + 0.10, 3), z0=round(ZC - 0.04, 3), z1=round(ZC + 0.04, 3),
                  y0=round(TOP + SY - 0.10, 3), y1=round(TOP + SY + 0.10, 3), mat="red", shape="cyl", axis="z",
                  anim="spin", px=SX, py=round(TOP + SY, 3), pz=ZC, speed=1.1))
for dx, dy in ((0.075, 0.009), (0.009, 0.075)):  # waagerechte und senkrechte Speiche
    parts.append(dict(x0=round(SX - dx, 3), x1=round(SX + dx, 3), z0=round(ZC - 0.043, 3), z1=round(ZC + 0.043, 3),
                      y0=round(TOP + SY - dy, 3), y1=round(TOP + SY + dy, 3), mat="white",
                      anim="spin", axis="z", px=SX, py=round(TOP + SY, 3), pz=ZC, speed=1.1))

prop = dict(id="drucker", name="FDM Drucker", parts=parts, device_id=6, on_watts=ON_WATTS, estimate=False, cloud="anycubic")


def req(method, url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())


existing = req("GET", base + "/api/floorplan/props")["props"]
keep = [{k: v for k, v in p.items() if k not in ("on", "power_w", "run")} for p in existing if p["id"] != prop["id"]]
out = req("PUT", base + "/api/floorplan/props", {"props": keep + [prop]})
print({p["id"]: len(p["parts"]) for p in out["props"]})
