#!/usr/bin/env python3
"""Stundenwerte der naechsten 48 Stunden ("48h Wetter") und Tageswettercodes ("Vorhersage").

Je Modell (GFS und ECMWF-IFS) ein Abruf der Open-Meteo-Vorhersage-Schnittstelle
mit dem jeweiligen Hauptlauf in Stundenaufloesung:

    Temperatur (2 m) · Niederschlag je Stunde · WMO-Wettercode · Tag/Nacht

Derselbe Abruf liefert zusaetzlich den WMO-Wettercode je KALENDERTAG fuer 16 Tage
(Ortszeit). Er traegt die Tagessymbole im Reiter "Vorhersage" -- ohne zusaetzlichen
Abruf. Achtung: Dieser Code stammt aus dem Hauptlauf, waehrend Kurve und
Niederschlagswahrscheinlichkeit dort aus dem Ensemble kommen; in der zweiten Woche
koennen beide auseinanderlaufen.

Der Wettercode ist die Quelle fuer die Wettersymbole; er kommt direkt vom
gewaehlten Modell, es braucht also keine zweite Wetterquelle. Ensemble-Mittel
und das 10.-/90.-Perzentil stammen NICHT von hier, sondern aus den ohnehin
gespeicherten Ensemble-Laeufen (daten/vorhersage/*.json) -- so entsteht kein
zusaetzlicher Abruf und beide Ansichten zeigen denselben Lauf.

Geschrieben wird nur bei fachlicher Aenderung: Der reine Abrufzeitpunkt zaehlt
nicht als Aenderung und erzeugt damit keinen Commit.
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemeinsam import atomar_schreiben_json, hole, ohne_feld  # noqa: E402
from sammeln_vorhersage import LAT, LON, MODELLE  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "daten" / "48h"
STUNDEN = 48
TAGE = 16                      # Tageswettercodes fuer den Reiter "Vorhersage"
FELDER = ("temperature_2m", "precipitation", "weather_code", "is_day")
NAMEN = {"temperature_2m": "temperatur_2m", "precipitation": "niederschlag",
         "weather_code": "wettercode", "is_day": "tag"}


def abrufen(modell, fehler, hole_=hole):
    """Ein Abruf je Modell. Gibt None zurueck, wenn die Antwort unbrauchbar ist."""
    cfg = MODELLE[modell]
    d = hole_("https://api.open-meteo.com/v1/forecast", params={
        "latitude": LAT, "longitude": LON, "hourly": ",".join(FELDER),
        "models": cfg["hauptlauf_datensatz"], "forecast_hours": STUNDEN + 1,
        # Die Tageswerte laufen in Ortszeit (ein Wettercode je Kalendertag),
        # die Stundenwerte weiterhin in UTC-Unixzeit.
        "daily": "weather_code", "forecast_days": TAGE,
        "timezone": "UTC", "timeformat": "unixtime"}, fehlerliste=fehler)
    stunden = (d or {}).get("hourly") or {}
    zeiten = stunden.get("time") or []
    if not zeiten or any(f not in stunden for f in FELDER):
        return None
    reihen = {NAMEN[f]: list(stunden[f]) for f in FELDER}
    if any(len(r) != len(zeiten) for r in reihen.values()):
        return None
    # Tageswettercodes sind ein Zusatz: Fehlen sie, bleibt der 48-Stunden-Teil trotzdem gueltig.
    tage = (d or {}).get("daily") or {}
    tageszeiten, tagescodes = tage.get("time") or [], tage.get("weather_code") or []
    tagesteil = {}
    if tageszeiten and len(tagescodes) == len(tageszeiten):
        tagesteil = {"tage_unix": [int(t) for t in tageszeiten], "tageswettercode": list(tagescodes)}
    return {"modell": modell, "modellname": cfg["name"], "datensatz": cfg["hauptlauf_datensatz"],
            "zeitpunkte_unix": [int(t) for t in zeiten], **reihen, **tagesteil}


def speichern(datensatz, pfad):
    """Schreibt nur bei fachlicher Aenderung (Abrufzeitpunkt zaehlt nicht)."""
    if pfad.exists():
        import json
        alt = json.loads(pfad.read_text(encoding="utf-8"))
        if ohne_feld(alt, "abgerufen") == ohne_feld(datensatz, "abgerufen"):
            return False
    atomar_schreiben_json(pfad, datensatz)
    return True


def main(argv=None, hole_=hole):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--modell", default="beide", choices=[*MODELLE, "beide"])
    a = p.parse_args(argv)
    modelle = list(MODELLE) if a.modell == "beide" else [a.modell]
    jetzt = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    fehler, geschrieben = [], 0
    for modell in modelle:
        datensatz = abrufen(modell, fehler, hole_=hole_)
        if not datensatz:
            print(f"{modell}: keine brauchbare 48-Stunden-Antwort — bisheriger Stand bleibt.")
            continue
        datensatz["abgerufen"] = jetzt
        neu = speichern(datensatz, OUT / f"{modell}.json")
        geschrieben += 1 if neu else 0
        print(f"{modell}: {len(datensatz['zeitpunkte_unix'])} Stunden "
              + ("gespeichert" if neu else "unveraendert"))
    if fehler:
        print("Hinweise: " + "; ".join(fehler))
    return 0


if __name__ == "__main__":
    sys.exit(main())
