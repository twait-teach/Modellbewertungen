#!/usr/bin/env python3
"""Baut die Wetterstationsseite aus daten/station/.

Erzeugt (alles unter docs/, damit GitHub Pages es ausliefert):

  docs/station.html            Oberflaeche (vorerst versteckte Testseite, nicht verlinkt)
  docs/station/heute.js        Rohwerte der letzten 48 Stunden + Stand + Monatsliste
  docs/station/verlauf_JJJJ-MM.js Stundenwerte eines Kalendermonats (Ortszeit Europe/Berlin)

Monatsdateien statt Jahresdateien: Bei jedem Lauf aendert sich nur die kleine
Datei des laufenden Monats; das haelt Seitenaufrufe und Git-Historie klein.

Die Dateien enthalten nur Zeit, Aussentemperatur, Aussenluftfeuchte und
Niederschlag. Unveraenderte Daten ergeben bytegleiche Dateien und damit keinen
Git-Commit. Getrennt von bauen.py: Ein Fehler hier beruehrt die Seiten
"Vorhersage" und "Analyse" nicht.
"""

import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemeinsam import atomar_schreiben  # noqa: E402
from station_netatmo import laden, stand_laden  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
DATEN = WURZEL / "daten" / "station"
VORLAGE = WURZEL / "skripte" / "station_vorlage.html"
DOCS = WURZEL / "docs"
ZONE = ZoneInfo("Europe/Berlin")
HEUTE_STUNDEN = 48


def _js(name, schluessel, objekt):
    inhalt = json.dumps(objekt, ensure_ascii=False, separators=(",", ":"))
    if schluessel is None:
        return f"window.{name}={inhalt};\n"
    return f"window.{name}=window.{name}||{{}};window.{name}[{json.dumps(schluessel)}]={inhalt};\n"


def _r(x, stellen=1):
    return None if x is None else round(x, stellen)


def stundenwerte(reihen):
    """Stundenaggregate je Ortsmonat: [beginn_unix, t_mittel, t_min, t_max, feuchte_mittel, regen_summe, n_aussen].

    Stundenbeginn in UTC ist wegen ganzzahliger Zonenversaetze zugleich ein
    Ortsstundenbeginn. Fehlende Messungen bleiben fehlend (nie 0 oder geschaetzt);
    die Anzahl der Aussenwerte je Stunde (n_aussen) zeigt die Vollstaendigkeit."""
    stunden = {}
    for ts, (t, h) in reihen["aussen"].items():
        s = stunden.setdefault(ts - ts % 3600, {"t": [], "h": [], "r": []})
        if t is not None:
            s["t"].append(t)
        if h is not None:
            s["h"].append(h)
    for ts, (mm,) in reihen["regen"].items():
        if mm is not None:
            stunden.setdefault(ts - ts % 3600, {"t": [], "h": [], "r": []})["r"].append(mm)
    monate = {}
    for beginn in sorted(stunden):
        s = stunden[beginn]
        t, h, r = s["t"], s["h"], s["r"]
        zeile = [beginn,
                 _r(sum(t) / len(t)) if t else None, _r(min(t)) if t else None, _r(max(t)) if t else None,
                 _r(sum(h) / len(h), 0) if h else None,
                 _r(sum(r), 2) if r else None,
                 len(t)]
        monat = dt.datetime.fromtimestamp(beginn, ZONE).strftime("%Y-%m")
        monate.setdefault(monat, []).append(zeile)
    return monate


def main():
    reihen = laden(DATEN)
    stand = stand_laden(DATEN / "stand.json")
    DOCS.mkdir(parents=True, exist_ok=True)
    atomar_schreiben(DOCS / "station.html", VORLAGE.read_text(encoding="utf-8"))

    alle = [ts for w in reihen.values() for ts in w]
    if not alle:
        heute = {"ort": "Stephanskirchen", "letzte_aktualisierung": stand.get("letzte_aktualisierung"),
                 "letzte_messung": None, "aussen": [], "regen": [], "monate": []}
        atomar_schreiben(DOCS / "station" / "heute.js", _js("STATION_HEUTE", None, heute))
        print("Wetterstation: noch keine Messwerte vorhanden.")
        return
    grenze = max(alle) - HEUTE_STUNDEN * 3600
    monate = stundenwerte(reihen)
    heute = {
        "ort": "Stephanskirchen",
        "letzte_aktualisierung": stand.get("letzte_aktualisierung"),
        "letzte_messung": max(reihen["aussen"]) if reihen["aussen"] else None,
        "aussen": [[ts, *reihen["aussen"][ts]] for ts in sorted(reihen["aussen"]) if ts >= grenze],
        "regen": [[ts, *reihen["regen"][ts]] for ts in sorted(reihen["regen"]) if ts >= grenze],
        "regen_vorhanden": bool(reihen["regen"]),
        "monate": sorted(monate),
        "erste_messung": min(alle),
        "rueckfuellung_fertig": all(stand.get("rueckfuellung_fertig", {}).values()),
    }
    atomar_schreiben(DOCS / "station" / "heute.js", _js("STATION_HEUTE", None, heute))
    for monat, zeilen in monate.items():
        atomar_schreiben(DOCS / "station" / f"verlauf_{monat}.js",
                         _js("STATION_VERLAUF", monat, {"monat": monat, "stunden": zeilen}))
    print(f"Wetterstation: {len(reihen['aussen'])} Aussenwerte, {len(reihen['regen'])} Regenwerte, "
          f"{len(monate)} Monate ({min(monate)} bis {max(monate)})")


if __name__ == "__main__":
    main()
