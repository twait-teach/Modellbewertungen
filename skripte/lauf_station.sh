#!/bin/sh
# Ein Lauf der Wetterstation auf dem Webspace.
#
# Ersatz fuer den GitHub-Workflow "Wetterstation Stefanskirchen": Netatmo
# abfragen, Stationsseite bauen, sichern. Bewusst getrennt vom Wetterlauf, weil
# die Station alle paar Minuten neue Messwerte liefert, neue Modelllaeufe aber
# nur alle sechs Stunden -- der Stationslauf darf also viel haeufiger laufen.
#
# Start ueber den Cronjob (docs/cron.php?...&teil=station) oder von Hand:
#
#     cd /www/htdocs/<konto>/wetter/programm && sh skripte/lauf_station.sh
#
# Die Zugangsdaten stehen in <konto>/wetter/netatmo.json, ausserhalb von
# Repository und Webverzeichnis. station_netatmo.py erneuert bei jedem Lauf den
# Netatmo-Token und schreibt den neuen sofort dorthin zurueck.

WURZEL=$(cd "$(dirname "$0")/.." && pwd)
cd "$WURZEL" || exit 1

# Dieselbe Sperre wie der Wetterlauf: Es laeuft immer nur einer von beiden,
# sonst kaemen sich die Commits in die Quere (bei GitHub war das die
# gemeinsame concurrency-Gruppe "daten").
SPERRE="$WURZEL/../lauf.sperre"
if ! mkdir "$SPERRE" 2>/dev/null; then
  if [ -n "$(find "$SPERRE" -maxdepth 0 -mmin +60 2>/dev/null)" ]; then
    echo "$(date -u '+%Y-%m-%d %H:%MZ') alte Sperre entfernt"
    rmdir "$SPERRE" 2>/dev/null
    mkdir "$SPERRE" 2>/dev/null || exit 0
  else
    echo "$(date -u '+%Y-%m-%d %H:%MZ') Station: es laeuft bereits etwas -- uebersprungen"
    exit 0
  fi
fi
trap 'rmdir "$SPERRE" 2>/dev/null' EXIT INT TERM

echo "=== $(date -u '+%Y-%m-%d %H:%MZ') Stationslauf beginnt ==="

git pull --ff-only --quiet || echo "Hinweis: git pull uebersprungen"

# Scheitert der Zugang oder der Abruf, endet das Skript mit Fehler und hat
# nichts geschrieben -- der letzte gueltige Datenstand bleibt stehen.
if ! python3 skripte/station_netatmo.py; then
  echo "FEHLER bei Netatmo -- Datenstand unveraendert."
  echo "=== $(date -u '+%Y-%m-%d %H:%MZ') Stationslauf beendet ==="
  exit 1
fi

python3 skripte/bauen_station.py || { echo "FEHLER beim Bauen der Stationsseite."; exit 1; }

git add -A daten/station docs/station docs/station.html
if git diff --staged --quiet; then
  echo "Nichts veraendert."
else
  git commit -q -m "Station automatisch $(date -u '+%Y-%m-%d %H:%MZ')"
  git push --quiet || echo "FEHLER: Push abgelehnt -- der naechste Lauf holt die Messwerte bei Netatmo nach."
fi

echo "=== $(date -u '+%Y-%m-%d %H:%MZ') Stationslauf beendet ==="
