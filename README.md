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

## Setup auf dem Raspberry Pi

```bash
git clone <dieses-repo> energie-dashboard
cd energie-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Testlauf
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Danach im Tablet-Browser `http://<pi-ip>:8000` öffnen und über das ⚙-Menü die
Shelly-Geräte (Name, Typ, IP-Adresse) sowie den Stromtarif eintragen.

### Als Dienst einrichten (Autostart + Neustart bei Absturz)

```bash
sudo cp deploy/energy-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now energy-dashboard
```

Pfade in `deploy/energy-dashboard.service` ggf. an den tatsächlichen Nutzer/Pfad anpassen.

## Automatische Updates auf dem Pi

Damit neue Commits auf `main` (z.B. von GitHub) automatisch auf den Pi übernommen
werden, ohne dass du dich einloggen musst, prüft ein systemd-Timer alle 5 Minuten
auf Änderungen, zieht sie per `git pull` und startet den Dienst neu:

```bash
chmod +x deploy/auto-update.sh
sudo cp deploy/energy-dashboard-update.service /etc/systemd/system/
sudo cp deploy/energy-dashboard-update.timer /etc/systemd/system/
sudo cp deploy/energy-dashboard-sudoers /etc/sudoers.d/energy-dashboard-update
sudo chmod 440 /etc/sudoers.d/energy-dashboard-update
sudo systemctl daemon-reload
sudo systemctl enable --now energy-dashboard-update.timer
```

Status/Logs prüfen: `journalctl -u energy-dashboard-update -f`

**Wichtig:** Das Skript macht bei neuen Commits einen `git reset --hard origin/main`.
Also auf dem Pi selbst keine manuellen Änderungen am Repo vornehmen – die werden beim
nächsten Update überschrieben. Der Pi muss dafür nicht von außen erreichbar sein, er
fragt nur selbst aktiv bei GitHub nach.

## Ohne echte Shelly-Hardware testen

`scripts/shelly_mock_server.py` simuliert die RPC-Endpunkte eines Shelly-Geräts mit
leicht schwankenden Fake-Werten (kein zusätzliches Python-Paket nötig):

```bash
python scripts/shelly_mock_server.py --port 8001 --type plug   # simuliert Plug S
python scripts/shelly_mock_server.py --port 8002 --type 3em    # simuliert Pro 3EM
```

Im Dashboard dann ein Gerät mit IP-Adresse `localhost:8001` (bzw. `localhost:8002`) anlegen.

## Konfiguration (Umgebungsvariablen, optional)

| Variable               | Standard          | Bedeutung                          |
|-------------------------|-------------------|-------------------------------------|
| `ENERGY_DATA_DIR`        | `./data`          | Ablageort der SQLite-Datenbank      |
| `ENERGY_POLL_INTERVAL`   | `10` (Sekunden)   | Abfrageintervall der Shelly-Geräte  |
| `ENERGY_HTTP_TIMEOUT`    | `5` (Sekunden)    | Timeout je Shelly-Anfrage           |

## Geplante Erweiterung: Wasser & Gas

Shellys messen Wasser/Gas nicht direkt, aber über einen Impulszähler-Eingang
(z.B. Shelly Plus Add-On / Shelly UNI an einem Impulsausgang des Zählers) lässt sich
das später nachrüsten. Die Tabellen `devices` und `tariffs` haben dafür bereits ein
`utility_type`-Feld – die eigentliche Poll-Logik und UI-Erweiterung folgt, sobald die
passende Hardware feststeht.
