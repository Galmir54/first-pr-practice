# Energie-Dashboard

Ein leichtgewichtiges Dashboard für Raspberry Pi (Raspberry Pi OS), das den Stromverbrauch
über lokal im Heimnetz erreichbare **Shelly-Geräte** (Gen2/Gen3 RPC-API) trackt und per
Tablet-Browser bedienbar ist. Aktuell unterstützt:

- **Shelly Pro 3EM** als 3-phasiger Hauptzähler (Gesamtverbrauch des Hauses)
- **Shelly Plug S (Gen3)** für einzelne Verbraucher (z.B. Waschmaschine, Kühlschrank)

Die Datenmodelle sind bewusst generisch gehalten (`utility_type`-Feld), damit später
**Wasser- und Gaszähler** ergänzt werden können, ohne die Datenbank migrieren zu müssen.

## Funktionen

- Live-Leistung (W) pro Gerät, automatische Aktualisierung alle paar Sekunden
- Tages-/Monatsverbrauch (kWh) pro Gerät, berechnet aus den Energiezählerständen der Shellys
- Kostenberechnung auf Basis von Grundpreis (€/Monat) + Arbeitspreis (ct/kWh), inkl. Tarifhistorie
- "Sonstige Verbraucher" = Hauptzähler minus Summe der erfassten Einzelgeräte
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

Bei vielen Geräten oder wenn der Pi entlasten werden soll, kann `ENERGY_POLL_INTERVAL`
erhöht werden (z.B. `10`) – der Live-Phasen-Chart aktualisiert sich dann entsprechend
seltener, da er direkt auf den gespeicherten Messwerten aufbaut.

## Geplante Erweiterung: Wasser & Gas

Shellys messen Wasser/Gas nicht direkt, aber über einen Impulszähler-Eingang
(z.B. Shelly Plus Add-On / Shelly UNI an einem Impulsausgang des Zählers) lässt sich
das später nachrüsten. Die Tabellen `devices` und `tariffs` haben dafür bereits ein
`utility_type`-Feld – die eigentliche Poll-Logik und UI-Erweiterung folgt, sobald die
passende Hardware feststeht.
