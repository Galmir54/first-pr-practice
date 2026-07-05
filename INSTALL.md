# Installationsanleitung – Energie-Dashboard auf Raspberry Pi OS

Schritt-für-Schritt-Anleitung, um das Energie-Dashboard auf einem Raspberry Pi
(Raspberry Pi OS / Raspbian) einzurichten. Dauer: ca. 15–20 Minuten.

## Voraussetzungen

- Raspberry Pi (3/4/5) mit Raspberry Pi OS, Zugriff per SSH oder Tastatur/Monitor
- Pi und Shelly-Geräte im selben Heimnetz (WLAN/LAN)
- Tablet mit Browser im selben WLAN
- Für den Auto-Update-Schritt: Zugriff auf das GitHub-Repo

## Schritt 1 – Pi vorbereiten

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip git
python3 --version   # sollte 3.10 oder neuer sein
```

## Schritt 2 – Repository holen

```bash
cd ~
git clone https://github.com/Galmir54/first-pr-practice.git energie-dashboard
cd energie-dashboard
```

> Solange der Pull Request `feature/energy-dashboard` noch nicht in `main` gemerged
> ist, den Branch direkt mitklonen:
> `git clone -b feature/energy-dashboard https://github.com/Galmir54/first-pr-practice.git energie-dashboard`

## Schritt 3 – Python-Umgebung einrichten

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Schritt 4 – Testlauf

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- IP-Adresse des Pi herausfinden: `hostname -I`
- Vom Tablet-Browser im selben WLAN öffnen: `http://<pi-ip>:8000`
- Erscheint das Dashboard, mit `Strg+C` beenden und mit Schritt 5 weitermachen.

## Schritt 5 – Geräte & Tarif einrichten

Im Dashboard über das ⚙-Symbol:

1. Shelly Pro 3EM als Hauptzähler mit seiner IP-Adresse eintragen
2. Jeden Shelly Plug S (Gen3) einzeln mit Name + IP-Adresse hinzufügen
3. Tarif prüfen/anpassen (ist mit Grundpreis 15,53 €/Monat, Arbeitspreis 16,47 ct/kWh vorbelegt)

**Empfehlung:** den Shellys im Router feste IP-Adressen zuweisen (DHCP-Reservierung),
sonst verschwindet ein Gerät aus dem Dashboard, sobald sich seine IP ändert.

## Schritt 6 – Als Dienst einrichten (Autostart, läuft dauerhaft im Hintergrund)

```bash
sudo cp deploy/energy-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now energy-dashboard
systemctl status energy-dashboard   # sollte "active (running)" zeigen
```

Falls dein Linux-Nutzername nicht `pi` ist oder das Repo an einem anderen Ort liegt,
vorher `User=` und `WorkingDirectory=`/`ExecStart=` in
`deploy/energy-dashboard.service` anpassen.

## Schritt 7 – Automatische Updates einrichten (empfohlen)

Damit neue Commits auf `main` automatisch auf den Pi übernommen werden:

```bash
chmod +x deploy/auto-update.sh
sudo cp deploy/energy-dashboard-update.service /etc/systemd/system/
sudo cp deploy/energy-dashboard-update.timer /etc/systemd/system/
sudo cp deploy/energy-dashboard-sudoers /etc/sudoers.d/energy-dashboard-update
sudo chmod 440 /etc/sudoers.d/energy-dashboard-update
sudo systemctl daemon-reload
sudo systemctl enable --now energy-dashboard-update.timer
```

Prüfen: `journalctl -u energy-dashboard-update -f` (zeigt Log-Einträge, sobald ein
Update-Durchlauf neue Commits findet).

**Wichtig:** Das Skript macht bei neuen Commits `git reset --hard origin/main`.
Auf dem Pi selbst also keine manuellen Änderungen am Repo vornehmen – die werden beim
nächsten Update überschrieben.

## Optional – Ohne echte Shelly-Hardware testen

`scripts/shelly_mock_server.py` simuliert die RPC-Endpunkte (kein zusätzliches Paket nötig):

```bash
python scripts/shelly_mock_server.py --port 8001 --type plug &
python scripts/shelly_mock_server.py --port 8002 --type 3em &
```

Dann im Dashboard ein Gerät mit IP-Adresse `localhost:8001` bzw. `localhost:8002` anlegen.

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| Dashboard vom Tablet nicht erreichbar | Prüfen, ob Tablet & Pi im selben WLAN sind; `hostname -I` auf dem Pi erneut prüfen; Firewall (`ufw status`) prüfen |
| Gerät zeigt dauerhaft "offline" | IP-Adresse prüfen; testen mit `curl http://<shelly-ip>/rpc/Shelly.GetStatus` vom Pi aus |
| Port 8000 bereits belegt | Anderen Port in `ExecStart=` von `energy-dashboard.service` wählen (z.B. `--port 8080`) |
| Dienst startet nicht nach Update | `journalctl -u energy-dashboard -n 50` für Fehlermeldungen |
| Auto-Update startet Dienst nicht neu | Sudoers-Datei korrekt kopiert? Mit `sudo visudo -c` auf Syntaxfehler prüfen |

## Deinstallation

```bash
sudo systemctl disable --now energy-dashboard energy-dashboard-update.timer
sudo rm -f /etc/systemd/system/energy-dashboard.service
sudo rm -f /etc/systemd/system/energy-dashboard-update.service
sudo rm -f /etc/systemd/system/energy-dashboard-update.timer
sudo rm -f /etc/sudoers.d/energy-dashboard-update
sudo systemctl daemon-reload
rm -rf ~/energie-dashboard
```
