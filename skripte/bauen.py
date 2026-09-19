#!/usr/bin/env python3
"""Baut Startdatei, Anwendung und die getrennte Datei docs/daten.js.

``index.html`` ist ein dauerhaft stabiler Loader. Er oeffnet ``app.html`` mit
einer frischen Versionskennung; aktualisierte Wetterdaten landen ausschliesslich
in ``daten.js``. Das vermeidet sowohl Browsercache-Probleme als auch Konflikte
zwischen dem halbstuendlichen Workflow und Entwicklungsarbeit.
"""

import datetime as dt
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemeinsam import atomar_schreiben

WURZEL = Path(__file__).resolve().parent.parent
DATEN = WURZEL / "daten"
VORLAGE = WURZEL / "skripte" / "vorlage.html"
START_ZIEL = WURZEL / "docs" / "index.html"
ZIEL = WURZEL / "docs" / "app.html"
DATEN_ZIEL = WURZEL / "docs" / "daten.js"

STARTSEITE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="index,follow">
<title>Regenprognose Mühldorf</title></head><body>
<p>Aktuelle Seite wird geladen …</p>
<script>location.replace('app.html?v=' + Date.now());</script>
<noscript><p><a href="app.html">Zur Wetterseite</a></p></noscript>
</body></html>
"""

# Wie weit die Messreihe in die Seite soll. Aelteres bleibt im Repo erhalten,
# wird aber nicht eingebettet -- die Auswertung reicht ohnehin nur so weit
# zurueck, wie es Vorhersagen gibt (rund 90 Tage).
MONATE_RUECKWAERTS = 8


def meteogrammlauf_anzeigbar(lauf):
    """Jeden vollstaendigen Ensemble-Slot sofort in die Seite einbetten.

    Der Hauptlauf darf noch fehlen und wird spaeter in denselben Slot
    nachgetragen. Unbrauchbare Altformate bleiben draussen, sobald wenigstens
    ein Slot im modellnahen Raster vorhanden ist.
    """
    for feld in ("temperatur_2m", "temperatur_850hpa", "niederschlag"):
        reihe = lauf.get(feld)
        if (not isinstance(reihe, dict) or not reihe.get("zeiten")
                or not reihe.get("zeitpunkte_unix") or not reihe.get("mitglieder")):
            return False
        if lauf.get("modell") == "gfs" and not reihe.get("kontrolllauf"):
            return False
    return True


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

    # Ensemble-Meteogrammlaeufe fuer die Vorhersage-Seite: je Modell STRIKT
    # absteigend nach der VOLLSTAENDIGEN Initialisierungszeit sortiert (nicht
    # nach Uhrzeit allein und nicht nach Dateireihenfolge) -- "init" ist ein
    # ISO-Zeitstempel JJJJ-MM-TTThh:mmZ, dessen Textsortierung deshalb exakt
    # der chronologischen Reihenfolge entspricht, auch ueber Tages-, Monats-
    # und Jahresgrenzen hinweg. Historische Luecken (Laeufe, die vor Einfuehrung
    # des Sammlers nie gespeichert wurden) bleiben einfach Luecken; es wird
    # nichts erfunden oder aufgefuellt.
    vorhersage = {"gfs": [], "ecmwf": []}
    vorhersage_altbestand = {"gfs": [], "ecmwf": []}
    for pfad in sorted((DATEN / "vorhersage").glob("*.json")) if (DATEN / "vorhersage").exists() else []:
        d = json.loads(pfad.read_text(encoding="utf-8"))
        modell = d.get("modell")
        if modell in vorhersage:
            vorhersage_altbestand[modell].append(d)
            if meteogrammlauf_anzeigbar(d):
                vorhersage[modell].append(d)
    for modell in vorhersage:
        # Kein leerer Bildschirm waehrend der Umstellung: Solange noch gar
        # kein Paket nach der strengeren Regel vorliegt, bleibt der bisherige
        # Bestand sichtbar. Sobald der erste korrekte Lauf gespeichert wurde,
        # werden die alten Teilpakete nicht mehr eingebettet.
        if not vorhersage[modell]:
            vorhersage[modell] = vorhersage_altbestand[modell]
        vorhersage[modell].sort(key=lambda d: d["init"], reverse=True)

    paket = {
        "messungen": dict(sorted(messungen.items())),
        "history": history,
        "forecasts": forecasts,
        "vorhersage": vorhersage,
        "gebaut": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }

    vorlage = VORLAGE.read_text(encoding="utf-8")
    if "/*__DATEN__*/{}" not in vorlage:
        raise SystemExit("Platzhalter /*__DATEN__*/{} fehlt in skripte/vorlage.html")

    # Die Vorlage enthaelt nur einen leeren Rueckfall fuer Tests/Fehlerfaelle.
    # Reale Daten werden als eigene Datei geschrieben und beim Seitenaufruf
    # mit einem Cache-Buster geladen.
    seite = vorlage
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
    atomar_schreiben(START_ZIEL, STARTSEITE)
    atomar_schreiben(ZIEL, seite)
    daten_js = "window.DATEN=" + json.dumps(
        paket, ensure_ascii=False, separators=(",", ":")) + ";\n"
    atomar_schreiben(DATEN_ZIEL, daten_js)

    tage = sorted(messungen)
    print(f"docs/index.html gebaut — {len(STARTSEITE)} Bytes (cachefester Loader)")
    print(f"docs/app.html gebaut — {len(seite)} Bytes (statischer Seitencode)")
    print(f"docs/daten.js gebaut — {len(daten_js)} Bytes (aktuelle Wetterdaten)")
    print(f"  Messreihe:   {len(tage)} Tage ({tage[0] if tage else '–'} bis {tage[-1] if tage else '–'})")
    print(f"  Läufe:       {len(forecasts)} ({min(forecasts)} bis {max(forecasts)})")
    print(f"  Historie:    " + ", ".join(f"{m} {len(history[m]['tage'])} Tage" for m in history))
    print(f"  Meteogramm:  " + ", ".join(f"{m} {len(vorhersage[m])} Lauf/Läufe" for m in vorhersage))


if __name__ == "__main__":
    main()
