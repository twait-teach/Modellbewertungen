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
from gemeinsam import atomar_schreiben, ist_aktuelles_format

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
<title>Vorhersage und Analyse Mühldorf</title></head><body>
<p>Aktuelle Seite wird geladen …</p>
<script>location.replace('app.html?v=' + Date.now() + location.hash);</script>
<noscript><p><a href="app.html">Zur Wetterseite</a></p></noscript>
</body></html>
"""

# Wie weit die Messreihe in die Seite soll. Aelteres bleibt im Repo erhalten,
# wird aber nicht eingebettet -- die Auswertung reicht ohnehin nur so weit
# zurueck, wie es Vorhersagen gibt (rund 90 Tage).
MONATE_RUECKWAERTS = 8


def meteogrammlauf_anzeigbar(lauf):
    """Nur Laeufe im aktuellen Meteogrammformat werden eingebettet.

    Die Regeln (Marker ``modellnativ-v1``, Zeitstempel, Unixzeit, Mitglieder,
    beim GFS der Kontrolllauf) liegen in ``gemeinsam.ist_aktuelles_format`` und
    sind damit dieselben wie im Sammler. Ein Ensemble-Slot ohne Hauptlauf ist
    ausdruecklich anzeigbar; der Hauptlauf wird spaeter in denselben Slot
    nachgetragen.
    """
    return ist_aktuelles_format(lauf)


def _utc_aus_iso(text):
    """ISO-Zeitstempel (mit Offset oder 'Z') als UTC-Zeitpunkt; None bei Fehler."""
    try:
        t = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)


def datenstand(forecasts, vorhersage, history):
    """Neuester Abrufzeitpunkt (UTC, Minutengenauigkeit) aller Quelldaten.

    Wird ausschliesslich aus den Quelldaten abgeleitet -- nie aus der Uhr. Damit
    erzeugen unveraenderte Wetterdaten bytegleich dieselbe ``daten.js`` und
    keinen Git-Commit, auch bei einem manuell angestossenen Neubau.
    """
    zeiten = [_utc_aus_iso(d.get("abgerufen")) for d in forecasts.values()]
    for laeufe in vorhersage.values():
        for lauf in laeufe:
            zeiten += [_utc_aus_iso(lauf.get("abgerufen")), _utc_aus_iso(lauf.get("hauptlauf_abgerufen"))]
    for h in history.values():
        zeiten.append(_utc_aus_iso(h.get("stand")))
    zeiten = [z for z in zeiten if z]
    return max(zeiten).strftime("%Y-%m-%dT%H:%MZ") if zeiten else None


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
    nicht_eingebettet = []
    for pfad in sorted((DATEN / "vorhersage").glob("*.json")) if (DATEN / "vorhersage").exists() else []:
        d = json.loads(pfad.read_text(encoding="utf-8"))
        modell = d.get("modell")
        if modell not in vorhersage:
            continue
        if meteogrammlauf_anzeigbar(d):
            vorhersage[modell].append(d)
        else:
            nicht_eingebettet.append(pfad.name)
    for modell in vorhersage:
        vorhersage[modell].sort(key=lambda d: d["init"], reverse=True)

    # Stundenwerte der naechsten 48 Stunden (Reiter "48h Wetter"). Fehlt die Datei,
    # bleibt der Reiter leer und meldet das; Vorhersage und Analyse sind unberuehrt.
    wetter48 = {}
    for pfad in sorted((DATEN / "48h").glob("*.json")) if (DATEN / "48h").exists() else []:
        d = json.loads(pfad.read_text(encoding="utf-8"))
        if d.get("modell") and d.get("zeitpunkte_unix"):
            wetter48[d["modell"]] = d

    paket = {
        "messungen": dict(sorted(messungen.items())),
        "history": history,
        "forecasts": forecasts,
        "vorhersage": vorhersage,
        "wetter48": wetter48,
        "datenstand": datenstand(forecasts, vorhersage, history),
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
             '<meta name="description" content="Ensemble-Vorhersage und Niederschlagsanalyse für Mühldorf am Inn '
             '(ECMWF und GFS gegen die DWD-Station) sowie Messwerte der Wetterstation Stefanskirchen.">\n'
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
    print(f"  48h-Wetter:  " + (", ".join(f"{m} {len(d['zeitpunkte_unix'])} Stunden" for m, d in wetter48.items()) or "keine Daten"))
    print(f"  Datenstand:  {paket['datenstand']}")
    if nicht_eingebettet:
        print(f"  Nicht eingebettet (kein aktuelles Format): {', '.join(nicht_eingebettet)}")


if __name__ == "__main__":
    main()
