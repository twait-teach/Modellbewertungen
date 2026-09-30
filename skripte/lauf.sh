#!/bin/sh
# Ein vollstaendiger Datenlauf auf dem Webspace.
#
# Ersatz fuer den GitHub-Workflow "Daten holen und Seite bauen": dieselben
# Schritte in derselben Reihenfolge, nur eben auf dem eigenen Server.
# Gestartet wird das Skript entweder vom Cronjob (ueber docs/cron.php, weil
# All-Inkl Cronjobs nur ueber eine URL ausfuehren kann) oder von Hand:
#
#     cd /www/htdocs/w022232d/wetter/programm && sh skripte/lauf.sh
#
# Bewusst KEIN "set -e": Ein einzelner Sammler, der an einer ueberlasteten
# Schnittstelle scheitert, darf den Rest des Laufs nicht verhindern. Die
# Sammler melden solche Faelle selbst und lassen den bisherigen Stand stehen.

WURZEL=$(cd "$(dirname "$0")/.." && pwd)
cd "$WURZEL" || exit 1

# --- Sperre: es laeuft immer nur ein Durchgang ------------------------------
# mkdir ist atomar, anders als "Datei existiert?" plus "Datei anlegen".
# Entspricht der concurrency-Gruppe "daten" der bisherigen Workflows.
SPERRE="$WURZEL/../lauf.sperre"
if ! mkdir "$SPERRE" 2>/dev/null; then
  # Eine Sperre, die aelter als eine Stunde ist, stammt von einem abgestuerzten
  # Lauf und wird uebergangen -- sonst stuende die Automatik fuer immer still.
  if [ -n "$(find "$SPERRE" -maxdepth 0 -mmin +60 2>/dev/null)" ]; then
    echo "$(date -u '+%Y-%m-%d %H:%MZ') alte Sperre entfernt"
    rmdir "$SPERRE" 2>/dev/null
    mkdir "$SPERRE" 2>/dev/null || exit 0
  else
    echo "$(date -u '+%Y-%m-%d %H:%MZ') laeuft bereits -- uebersprungen"
    exit 0
  fi
fi
trap 'rmdir "$SPERRE" 2>/dev/null' EXIT INT TERM

echo "=== $(date -u '+%Y-%m-%d %H:%MZ') Lauf beginnt ==="

# --- Programmstand auffrischen ---------------------------------------------
# Holt Aenderungen, die von aussen ins Archiv geschoben wurden (Patches).
# --ff-only: Gibt es hier eigene, noch nicht geschobene Commits, bricht der
# Abgleich lieber ab, als eine Zusammenfuehrung zu erfinden.
git pull --ff-only --quiet || echo "Hinweis: git pull uebersprungen"

# --- Daten holen ------------------------------------------------------------
python3 skripte/sammeln_vorhersage.py --modell beide
python3 skripte/sammeln_48h.py --modell beide
python3 skripte/sammeln.py --alles
python3 skripte/historie.py

# --- Nur bei fachlicher Aenderung bauen und sichern -------------------------
if [ -z "$(git status --porcelain -- daten)" ]; then
  echo "Keine neuen Daten -- nichts zu bauen."
  echo "=== $(date -u '+%Y-%m-%d %H:%MZ') Lauf beendet ==="
  exit 0
fi

python3 skripte/bauen.py || { echo "FEHLER beim Bauen -- nichts gesichert."; exit 1; }

# -A statt nur einzelner Pfade: sammeln_vorhersage.py raeumt alte Laufdateien
# auch mal ab; ohne -A wuerden Loeschungen nicht erfasst.
git add -A daten docs
if git diff --staged --quiet; then
  echo "Nichts veraendert."
else
  git commit -q -m "Daten automatisch $(date -u '+%Y-%m-%d %H:%MZ')"
  git push --quiet || echo "FEHLER: Push ins Archiv abgelehnt -- naechster Lauf beginnt auf dem neuen Stand."
fi

echo "=== $(date -u '+%Y-%m-%d %H:%MZ') Lauf beendet ==="
