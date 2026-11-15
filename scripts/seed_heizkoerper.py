"""Heizkörper (Kinderzimmer, Küche, Arbeitszimmer, Bad, Schlafzimmer, Wohnzimmer) als Props mit Farbwechsel nach dem Raum-Thermostat.

Doppelplatten-Heizkörper mit Konvektorgitter oben, Sicken in der Front und Thermostatkopf rechts. Die Platten haben
die Animation "heat": rötlich, wenn der Thermostat des Raums (Prop.heat_room) gerade heizt (Ally work_state Heat),
sonst bläulich. Maße geschätzt (Küche nach den Fotos aus seed_kueche.py, Kinderzimmer nach dem Fenster).

  Kinderzimmer: unter Fenster "f1" (x -3,86, z -5,15, Brüstung 0,94 m, Wand 10 cm), Innenseite der Wand bei z -5,10.
  Küche:        unter Fenster "f2" (x 0,87, z -4,97, Brüstung 0,95 m), Innenseite der Wand bei z -4,92; ersetzt den
                früheren weißen Quader im Prop "kueche_ost" (wird beim Einspielen entfernt).

Aufruf: py -I scripts/seed_heizkoerper.py http://host:8000   (ersetzt nur die eigenen Props)
"""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")


def radiator(pid, name, heat_room, xc, half, z_wall, y0, y1, dirz=1, head=1):
    """Heizkörper mit Rückseite an der Wand (z_wall = Innenseite der Wand). dirz +1: Wand im Norden, Front zeigt nach +z;
    dirz -1: Wand im Süden, Front zeigt nach -z. head +1/-1: Thermostatkopf an der rechten (+x) / linken (-x) Seite."""
    parts = []
    x0, x1 = xc - half, xc + half
    top = y1 - 0.015  # darüber das Konvektorgitter

    def zz(offset):  # Abstand von der Wand -> z
        return z_wall + dirz * offset

    def box(a0, a1, d0, d1, c0, c1, mat="white", **kw):
        """x von a0..a1, Abstand von der Wand d0..d1, Höhe c0..c1."""
        za, zb = sorted((zz(d0), zz(d1)))
        parts.append(dict(x0=round(a0, 3), x1=round(a1, 3), z0=round(za, 3), z1=round(zb, 3),
                          y0=round(c0, 3), y1=round(c1, 3), mat=mat, **kw))

    # zwei Platten hintereinander, dazwischen ein dunkler Spalt
    box(x0, x1, 0.012, 0.040, y0, top, "gray", anim="heat")
    box(x0 + 0.01, x1 - 0.01, 0.040, 0.048, y0 + 0.02, top - 0.02, "black")
    box(x0, x1, 0.048, 0.076, y0, top, "gray", anim="heat")
    # Konvektorgitter oben, Seitenblenden
    box(x0 + 0.005, x1 - 0.005, 0.012, 0.078, top, y1, "black")
    for sx in (x0 - 0.008, x1):
        box(sx, sx + 0.008, 0.012, 0.078, y0 + 0.005, y1 - 0.005, "white")
    # senkrechte Sicken in der Frontplatte
    n = 6
    for k in range(1, n):
        x = x0 + (x1 - x0) * k / n
        box(x - 0.003, x + 0.003, 0.076, 0.079, y0 + 0.03, top - 0.03, "black")
    # Thermostatkopf (Ally) mit Ventil darunter, an der Seite `head`
    mid = y0 + (top - y0) * 0.55
    hx0, hx1 = (x1, x1 + 0.085) if head > 0 else (x0 - 0.085, x0)
    vx0, vx1 = (x1, x1 + 0.02) if head > 0 else (x0 - 0.02, x0)
    za, zb = sorted((zz(0.02), zz(0.07)))
    parts.append(dict(x0=round(hx0, 3), x1=round(hx1, 3), z0=round(za, 3), z1=round(zb, 3),
                      y0=round(mid - 0.025, 3), y1=round(mid + 0.025, 3), mat="white", shape="cyl", axis="x"))
    box(vx0, vx1, 0.035, 0.055, y0 + 0.05, mid - 0.025, "chrome")
    return dict(id=pid, name=name, parts=parts, heat_room=heat_room)


props = [
    radiator("kinderzimmer_heizkoerper", "Heizkörper Kinderzimmer", "Kinderzimmer", -3.86, 0.45, -5.10, 0.14, 0.66),
    radiator("kueche_heizkoerper", "Heizkörper Küche", "Küche", 0.85, 0.45, -4.92, 0.28, 0.86),
    # Arbeitszimmer: an der Nordwand links neben der Tür nach draußen "t3" (Tür x 2,95..3,68; Wand-Innenseite z -3,84,
    # Westwand-Innenseite x 2,10): 60 cm breit, ca. 10 cm Abstand zur Tür. Breite/Höhe geschätzt.
    radiator("arbeitszimmer_heizkoerper", "Heizkörper Arbeitszimmer", "Arbeitszimmer", 2.55, 0.30, -3.84, 0.14, 0.74),
    # Bad: an der Südwand östlich (links, wenn man zur Tür schaut) der Tür zum Flur "t4" (Tür x -2,07..-1,48; Wand-Innenseite
    # z -2,15; Ostwand-Innenseite x -0,545): 60 cm breit, Thermostatkopf zur Tür hin (ca. 6 cm bis zur Türkante).
    radiator("bad_heizkoerper", "Heizkörper Bad", "Bad", -1.03, 0.30, -2.15, 0.14, 0.74, dirz=-1, head=-1),
    # Schlafzimmer und Wohnzimmer: je unter dem Fenster an der Südwand (Wand-Innenseite z 5,095; Fenster f5 x -0,12 /
    # f6 x 3,02, Brüstung 1,05 / 1,01 m, Breite 1,77 / 1,83 m): 1,20 m breit, Front zeigt nach -z. Maße geschätzt.
    radiator("schlafzimmer_heizkoerper", "Heizkörper Schlafzimmer", "Schlafzimmer", -0.12, 0.60, 5.095, 0.14, 0.74, dirz=-1),
    radiator("wohnzimmer_heizkoerper", "Heizkörper Wohnzimmer", "Wohnzimmer", 3.02, 0.60, 5.095, 0.14, 0.74, dirz=-1),
]
OWN = {p["id"] for p in props}


def legacy(part):
    """Der frühere weiße Quader samt schwarzer Abdeckung in der Küche (Prop kueche_ost)."""
    return (abs(part["x0"] - 0.40) < 0.011 and abs(part["x1"] - 1.30) < 0.011
            and abs(part["z0"] + 4.90) < 0.011 and abs(part["z1"] + 4.80) < 0.011 and part["mat"] in ("white", "black"))


def req(method, url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())


existing = req("GET", base + "/api/floorplan/props")["props"]
keep = []
for p in existing:
    if p["id"] in OWN:
        continue
    p = {k: v for k, v in p.items() if k not in ("on", "power_w", "run")}
    if p["id"] == "kueche_ost":
        p["parts"] = [s for s in p["parts"] if not legacy(s)]
    keep.append(p)
out = req("PUT", base + "/api/floorplan/props", {"props": keep + props})
print({p["id"]: len(p["parts"]) for p in out["props"]})
