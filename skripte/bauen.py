#!/usr/bin/env python3
"""
Baut aus dem Datenbestand in daten/ die fertige Webseite docs/index.html.

Die Daten werden in die Seite eingebettet, nicht nachgeladen -- so ist die Seite
eine einzige Datei, funktioniert ohne Server und auch lokal im Browser.
"""

import datetime as dt
import glob
import json
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
DATEN = WURZEL / "daten"
VORLAGE = WURZEL / "skripte" / "vorlage.html"
ZIEL = WURZEL / "docs" / "index.html"

# Wie weit die Messreihe in die Seite soll. Aelteres bleibt im Repo erhalten,
# wird aber nicht eingebettet -- die Auswertung reicht ohnehin nur so weit
# zurueck, wie es Vorhersagen gibt (rund 90 Tage).
MONATE_RUECKWAERTS = 8


def monatsschluessel(versatz):
    heute = dt.date.today().replace(day=1)
    for _ in range(versatz):
        heute = (heute - dt.timedelta(days=1)).replace(day=1)
    return heute.strftime("%Y-%m")


def main():
    grenze = monatsschluessel(MONATE_RUECKWAERTS)

    messungen = {}
    for pfad in sorted(DATEN.glob("messungen_*.json")):
        d = json.loads(pfad.read_text(encoding="utf-8"))
        if d["monat"] >= grenze:
            messungen.update(d["tage"])

    history = {}
    for modell in ("gfs", "ecmwf"):
        pfad = DATEN / f"history_{modell}.json"
        if pfad.exists():
            history[modell] = json.loads(pfad.read_text(encoding="utf-8"))

    forecasts = {}
    for pfad in sorted(DATEN.glob("forecasts_*.json")):
        d = json.loads(pfad.read_text(encoding="utf-8"))
        forecasts[d["lauf"]] = d

    if not forecasts:
        raise SystemExit("Keine Vorhersagedaten in daten/ gefunden — erst skripte/sammeln.py laufen lassen.")

    paket = {
        "messungen": dict(sorted(messungen.items())),
        "history": history,
        "forecasts": forecasts,
        "gebaut": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }

    vorlage = VORLAGE.read_text(encoding="utf-8")
    if "/*__DATEN__*/{}" not in vorlage:
        raise SystemExit("Platzhalter /*__DATEN__*/{} fehlt in skripte/vorlage.html")

    seite = vorlage.replace("/*__DATEN__*/{}", json.dumps(paket, ensure_ascii=False, separators=(",", ":")))
    # Eine Seite fuers offene Netz braucht Kopf und Rahmen selbst.
    seite = ('<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
             '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
             '<meta name="description" content="Täglicher Vergleich der Niederschlagsvorhersagen von '
             'ECMWF und GFS gegen die Messwerte der DWD-Station Mühldorf am Inn.">\n'
             '<meta name="robots" content="index,follow">\n'
             '<style>html{color-scheme:light dark}body{margin:0}img{max-width:100%}'
             '[hidden]{display:none!important}</style>\n'
             + seite.split("<style>", 1)[0].replace("<title>", "<title>", 1)
             + "<style>" + seite.split("<style>", 1)[1].split("</style>", 1)[0] + "</style>\n</head>\n<body>\n"
             + seite.split("</style>", 1)[1] + "\n</body>\n</html>\n")

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    ZIEL.write_text(seite, encoding="utf-8")

    tage = sorted(messungen)
    print(f"docs/index.html gebaut — {len(seite)} Bytes")
    print(f"  Messreihe:  {len(tage)} Tage ({tage[0] if tage else '–'} bis {tage[-1] if tage else '–'})")
    print(f"  Läufe:      {len(forecasts)} ({min(forecasts)} bis {max(forecasts)})")
    print(f"  Historie:   " + ", ".join(f"{m} {len(history[m]['tage'])} Tage" for m in history))


if __name__ == "__main__":
    main()
