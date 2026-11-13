# Energie-Dashboard

Ein leichtgewichtiges Dashboard für Raspberry Pi (Raspberry Pi OS), das den Stromverbrauch
über lokal im Heimnetz erreichbare **Shelly-Geräte** (Gen2/Gen3 RPC-API) trackt und per
Tablet-Browser bedienbar ist. Aktuell unterstützt:

- **Shelly Pro 3EM** als 3-phasiger Hauptzähler (Gesamtverbrauch des Hauses)
- **Shelly Plug S (Gen3)** für einzelne Verbraucher (z.B. Waschmaschine, Kühlschrank)

Die Datenmodelle sind bewusst generisch gehalten (`utility_type`-Feld), damit später
**Wasser- und Gaszähler** ergänzt werden können, ohne die Datenbank migrieren zu müssen.

## Funktionen

- **Live-Tab**: Phasen-Karten (L1/L2/L3) mit Leistung, Spannung, Strom, Leistungsfaktor
  und Frequenz je Phase, kombinierter Chart (L1/L2/L3 + Summe), Kennzahlen-Leiste
  (Gesamt/Peak/Gesamt-kWh/Arbeitskosten/Gesamtkosten), einstellbares Aktualisierungs-
  intervall, Pause-Funktion, CSV-Export der Rohmesswerte, Peak-Reset
- Tages-/Monatsverbrauch (kWh) pro Gerät, berechnet aus den Energiezählerständen der Shellys
- Kostenberechnung auf Basis von Grundpreis (€/Monat) + Arbeitspreis (ct/kWh), inkl. Tarifhistorie
  und optionalem Tarifnamen
- "Sonstige Verbraucher" = Hauptzähler minus Summe der erfassten Einzelgeräte
- Kalender-Tab mit Tages-kWh-Übersicht für den laufenden Monat
- Müllabfuhr-Erinnerung (Landkreis Mainz-Bingen): Popup am Vortag ab 16 Uhr und am Abfuhrtag bis 8 Uhr, bis es quittiert wird
- Grundriss-Tab: 3D-Modell der Wohnung (STL, Maßstab 1:100) als "Puppenhaus" mit Schatten und Kantenlinien, Umschalten zwischen 3D und Draufsicht, einstellbarer Wandschnitt; die Datei liegt unter `static/models/wohnung.stl` und muss einmalig manuell auf den Pi kopiert werden (nicht im Repo)
- Geräte- und Tarifverwaltung direkt im Web-UI (kein Konfigfile nötig)

## Installation

Die vollständige Schritt-für-Schritt-Anleitung (Voraussetzungen, Einrichtung als
Dienst, automatische Updates, Fehlerbehebung) steht in **[INSTALL.md](INSTALL.md)**.

Kurzfassung für den schnellen Testlauf:

```bash
git clone https://github.com/Galmir54/first-pr-practice.git energie-dashboard
cd energie-dashboard
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Danach im Tablet-Browser `http://<pi-ip>:8000` öffnen und über das ⚙-Menü die
Shelly-Geräte sowie den Stromtarif eintragen.

## Konfiguration (Umgebungsvariablen, optional)

| Variable               | Standard          | Bedeutung                          |
|-------------------------|-------------------|-------------------------------------|
| `ENERGY_DATA_DIR`        | `./data`          | Ablageort der SQLite-Datenbank      |
| `ENERGY_POLL_INTERVAL`   | `2` (Sekunden)    | Abfrageintervall der Shelly-Geräte (bestimmt auch, wie oft der Live-Phasen-Chart neue Werte bekommt) |
| `ENERGY_HTTP_TIMEOUT`    | `5` (Sekunden)    | Timeout je Shelly-Anfrage           |
| `ENERGY_STORE_INTERVAL`  | `30` (Sekunden)   | Wie oft ein Messwert in die Datenbank geschrieben wird (die Live-Ansicht nutzt trotzdem jeden Poll-Wert) |
| `ENERGY_THIN_AFTER_DAYS` | `2` (Tage)        | Ab diesem Alter werden Rohmesswerte ausgedünnt |
| `ENERGY_THIN_BUCKET_SECONDS` | `300` (Sekunden) | Ausgedünnte Messwerte: ein Wert je Zeitfenster dieser Länge |

Bei vielen Geräten oder wenn der Pi entlasten werden soll, kann `ENERGY_POLL_INTERVAL`
erhöht werden (z.B. `10`) – der Live-Phasen-Chart aktualisiert sich dann entsprechend
seltener.

## Müllabfuhr-Erinnerung

Die Abfuhrtermine holt sich der Server selbst von der öffentlichen Schnittstelle der
KAW (Kommunale Abfallwirtschaft Mainz und Mainz-Bingen AöR), speichert sie lokal
(funktioniert danach auch ohne Internet) und aktualisiert sie alle 12 Stunden. Den Ort
wählst du einmalig unter ⚙ Einstellungen → „Müllabfuhr" (Abfuhrbezirk + Ort); er wird
nur in der lokalen Datenbank gespeichert, nicht im Repo.

Ein Popup erscheint am Vortag ab `ENERGY_WASTE_REMIND_FROM_HOUR` (16 Uhr) und am
Abfuhrtag bis `ENERGY_WASTE_REMIND_UNTIL_HOUR` (8 Uhr). Es bleibt, bis du
„Tonnen stehen draußen" tippst (gilt dann für alle Geräte); „In 30 Min. erinnern"
blendet es nur kurz aus. Rest-/Biomüll, Gelbe Tonne und Papiertonne lösen Erinnerungen
aus (`ENERGY_WASTE_TYPE_IDS`, KAW-IDs: 1 Rest, 2 Bio, 3 Gelb, 4 Papier, 5 Sperrmüll,
6 Problemmüllbus). Der nächste Termin steht außerdem als Chip in der Kopfzeile.

## Heizung absenken, wenn niemand zu Hause ist (Danfoss Ally)

Der Server prüft alle 30 Sekunden, ob die eingetragenen Handys im WLAN sind (Ping und
ARP-Abfrage, funktioniert auch, wenn das Handy im Standby nicht auf Ping antwortet).
Ist **kein** Handy mehr seit der eingestellten Wartezeit (Standard 15 Min.) erreichbar,
schaltet er alle Ally-Thermostate über die Danfoss-Cloud auf „Abwesend“ mit der
Absenktemperatur (Standard 17 °C). Vorher merkt er sich je Thermostat den bisherigen
Modus. Sobald ein Handy wieder im WLAN ist, stellt er genau diesen Modus wieder her,
z. B. den Wochenplan oder manuell 23 °C. Klappt ein Befehl nicht (z. B. kein
Internet), versucht er es alle 30 Sekunden erneut. Nach einem Neustart des Pi wartet
er erst die volle Wartezeit ab, bevor er absenkt.

Einrichtung unter ⚙ Einstellungen → „Heizung (Danfoss Ally)“, Schritt für Schritt in
[INSTALL.md](INSTALL.md#optional--heizung-mit-danfoss-ally-absenken). Mit
„Jetzt absenken (Test)“ / „Jetzt zurücksetzen“ lässt sich das sofort ausprobieren;
die Automatik pausiert danach 10 Minuten, damit sie den Test nicht gleich rückgängig
macht. API-Secret und Handy-IPs liegen nur in der lokalen Datenbank, das Secret wird
nie an den Browser zurückgegeben.

## Datenbank-Wartung

Der letzte Poll-Wert jedes Geräts liegt im Speicher (Live-Ansicht), in die SQLite-Datei
wird nur alle `ENERGY_STORE_INTERVAL` Sekunden geschrieben. Ein Hintergrund-Job (stündlich)
dünnt außerdem ältere Rohmesswerte aus, ohne die Zählerstände (und damit Verbrauch und
Kosten) zu verändern; die höchste je gemessene Leistung („Peak") wird dabei in eine eigene
Tabelle übernommen. Die Datei selbst schrumpft dadurch nicht, sie wächst aber nicht mehr –
zum Verkleinern einmalig bei gestopptem Dienst:

```bash
sudo systemctl stop energy-dashboard
sqlite3 ~/energie-dashboard/data/energy.db "VACUUM;"
sudo systemctl start energy-dashboard
```

## Geplante Erweiterung: Wasser & Gas

Shellys messen Wasser/Gas nicht direkt, aber über einen Impulszähler-Eingang
(z.B. Shelly Plus Add-On / Shelly UNI an einem Impulsausgang des Zählers) lässt sich
das später nachrüsten. Die Tabellen `devices` und `tariffs` haben dafür bereits ein
`utility_type`-Feld – die eigentliche Poll-Logik und UI-Erweiterung folgt, sobald die
passende Hardware feststeht.
