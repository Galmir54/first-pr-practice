#!/bin/bash
# Prüft, ob es auf origin/main neue Commits gibt, zieht sie und startet den
# Dienst neu. Wird von energy-dashboard-update.timer alle paar Minuten aufgerufen.
#
# Achtung: führt bei neuen Commits "git reset --hard" aus. Auf dem Pi selbst
# also keine manuellen Änderungen im Repo vornehmen, die würden überschrieben.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

git fetch origin main --quiet

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

echo "$(date -Iseconds) Neue Version gefunden ($LOCAL -> $REMOTE), aktualisiere..."
git reset --hard origin/main

source venv/bin/activate
pip install --quiet -r requirements.txt

sudo /usr/bin/systemctl restart energy-dashboard

echo "$(date -Iseconds) Update abgeschlossen (Commit $REMOTE)"
