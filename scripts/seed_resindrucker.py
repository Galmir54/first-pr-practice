"""Resin-Drucker (Anycubic Photon Mono M7 Pro) im Arbeitszimmer, neben dem FDM-Drucker.

Er steht auf demselben Schreibtisch an der Ostwand (Oberkante 0,84 m, x 4,05..4,58, z -2,85..-1,50), auf der
Nordseite des FDM-Druckers (der steht bei z -2,15..-1,75). Maße ungefähr nach Datenblatt (ca. 23 x 22 x 38 cm),
Front zum Raum = -x: dunkler Sockel mit Anzeige, weißer Z-Turm hinten, orange durchscheinende UV-Haube, darunter
Wanne und Bauplatte. Reines Standbild ohne Gerätezustand (keine Steckdose bekannt).

Aufruf: py -I scripts/seed_resindrucker.py http://host:8000   (ersetzt nur das eigene Prop)
"""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")

DESK = 0.84
X0, X1 = 4.205, 4.435  # Front bei X0 (zum Raum)
Z0, Z1 = -2.50, -2.27
XC, ZC = (X0 + X1) / 2, (Z0 + Z1) / 2
XT = 4.375  # Vorderkante des Turms; davor die Haube

parts = []


def box(x0, x1, z0, z1, y0, y1, mat="black"):
    parts.append(dict(x0=round(x0, 3), x1=round(x1, 3), z0=round(z0, 3), z1=round(z1, 3),
                      y0=round(DESK + y0, 3), y1=round(DESK + y1, 3), mat=mat))


# Sockel mit Anzeige vorn und Drehknopf-ähnlichem Taster
box(X0, X1, Z0, Z1, 0.0, 0.12, "black")
box(X0 - 0.006, X0, ZC - 0.07, ZC + 0.07, 0.03, 0.09, "gray")  # Anzeigefeld
box(X0 - 0.01, X0, ZC - 0.05, ZC + 0.05, 0.04, 0.08, "glass")  # Bildschirm
# Wanne (Resin) im Sockel, vorn in der Haube
box(X0 + 0.015, XT - 0.015, Z0 + 0.02, Z1 - 0.02, 0.12, 0.15, "gray")
# Z-Turm hinten, volle Höhe
box(XT, X1, Z0, Z1, 0.12, 0.38, "white")
# Arm vom Turm zur Bauplatte, Bauplatte (Alu) über der Wanne
box(X0 + 0.03, XT, ZC - 0.05, ZC + 0.05, 0.215, 0.235, "chrome")
box(X0 + 0.03, XT - 0.03, ZC - 0.075, ZC + 0.075, 0.195, 0.215, "chrome")
# UV-Haube (orange, durchscheinend) und Deckplatte
box(X0, XT, Z0, Z1, 0.12, 0.35, "glowamber")
box(X0, XT, Z0, Z1, 0.35, 0.37, "white")

prop = dict(id="resindrucker", name="Resin-Drucker (Photon Mono M7 Pro)", parts=parts)


def req(method, url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())


existing = req("GET", base + "/api/floorplan/props")["props"]
keep = [{k: v for k, v in p.items() if k not in ("on", "power_w", "run")} for p in existing if p["id"] != prop["id"]]
out = req("PUT", base + "/api/floorplan/props", {"props": keep + [prop]})
print({p["id"]: len(p["parts"]) for p in out["props"]})
