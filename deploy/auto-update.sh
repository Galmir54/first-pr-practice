#!/bin/bash
# Prüft, ob es auf dem gerade ausgecheckten Branch neue Commits gibt, zieht sie
# und startet den Dienst neu. Wird von energy-dashboard-update.timer alle paar
# Minuten aufgerufen.
#
# Wichtig: verfolgt bewusst den Branch, der auf dem Pi gerade ausgecheckt ist
# (z.B. "main" oder ein Feature-Branch vor dem Merge) statt fest "main"
# anzunehmen — sonst würde bei noch nicht gemergten Branches versehentlich auf
# einen älteren Stand von "main" zurückgesetzt.
#
# Achtung: führt bei neuen Commits "git reset --hard" aus. Auf dem Pi selbst
# also keine manuellen Änderungen im Repo vornehmen, die würden überschrieben.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git fetch origin "$BRANCH" --quiet

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

echo "$(date -Iseconds) Neue Version auf $BRANCH gefunden ($LOCAL -> $REMOTE), aktualisiere..."
git reset --hard "origin/$BRANCH"

source venv/bin/activate
pip install --quiet -r requirements.txt

sudo /usr/bin/systemctl restart energy-dashboard

echo "$(date -Iseconds) Update abgeschlossen (Commit $REMOTE)"
