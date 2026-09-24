#!/usr/bin/env python3
"""Holt die amtlichen Klima-Normalwerte einer DWD-Station: 1991-2020 und 1961-1990.

Quelle: Deutscher Wetterdienst, Climate Data Center, frei zugaengliche Dateien
unter opendata.dwd.de (Monatsmittel der Lufttemperatur und Monatssummen des
Niederschlags). Gespeichert werden zwei Bezugszeitraeume: 1991-2020 als aktuelles
Klimamittel und 1961-1990 als aeltere Normalperiode zum Vergleich.

Diese Werte aendern sich erst mit der naechsten Normalperiode (2021-2050).
Das Skript laeuft deshalb NICHT im Workflow, sondern nur von Hand:

    python3 skripte/klima_normalwerte.py            # Station 3366 (Muehldorf)
    python3 skripte/klima_normalwerte.py --station 4261 --name Rosenheim

Ergebnis: daten/klima/normalwerte.json. Von dort nimmt bauen_station.py die
Werte in die Stationsseite auf (Jahresansicht: Vergleichskurve und -linien).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemeinsam import atomar_schreiben_json, hole  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
ZIEL = WURZEL / "daten" / "klima" / "normalwerte.json"
BASIS = ("https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
         "climate/multi_annual/")
# Reihenfolge: zuerst das aktuelle Klimamittel, danach die Vergleichsperiode.
PERIODEN = [("1991-2020", "mean_91-20"), ("1961-1990", "mean_61-90")]
DATEIEN = {"temperatur_c": "Temperatur_{zeitraum}.txt",
           "niederschlag_mm": "Niederschlag_{zeitraum}.txt"}
STATIONSLISTE = "Temperatur_{zeitraum}_Stationsliste.txt"


def zeile_der_station(text, station):
    """Die Zeile einer Station aus einer DWD-Normalwertdatei als Liste von Feldern."""
    for zeile in text.splitlines()[1:]:
        felder = [f.strip() for f in zeile.split(";")]
        if felder and felder[0] == str(station):
            return felder
    raise SystemExit(f"Station {station} kommt in der Datei nicht vor.")


def werte_der_station(text, station):
    """Zwoelf Monatswerte und der Jahreswert (Spalten 4 bis 16)."""
    felder = zeile_der_station(text, station)[3:16]
    if len(felder) != 13:
        raise SystemExit(f"Unerwarteter Dateiaufbau fuer Station {station}.")
    zahlen = [float(f.replace(",", ".")) for f in felder]
    return zahlen[:12], zahlen[12]


def stationsangaben(text, station):
    felder = zeile_der_station(text, station)
    return {"id": str(station), "name": felder[1],
            "hoehe_m": float(felder[4].replace(",", ".")) if len(felder) > 4 else None}


def datei_stationsliste(laden, periode):
    zeitraum, ordner = periode
    return laden(f"{ordner}/" + STATIONSLISTE.format(zeitraum=zeitraum))


def main(argv=None, laden=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--station", default="3366", help="DWD-Stationskennung (Vorgabe: 3366, Mühldorf)")
    p.add_argument("--ziel", default=str(ZIEL))
    a = p.parse_args(argv)
    laden = laden or (lambda datei: hole(BASIS + datei, roh=True).decode("latin-1"))

    def periode(zeitraum, ordner):
        """Monatswerte und Jahreswerte eines Bezugszeitraums."""
        datei = lambda name: laden(f"{ordner}/" + name.format(zeitraum=zeitraum))
        teil = {"zeitraum": zeitraum, "jahr": {}}
        for feld, name in DATEIEN.items():
            monate, jahr = werte_der_station(datei(name), a.station)
            teil[feld] = monate
            teil["jahr"][feld] = jahr
        return teil

    aktuell, alt = PERIODEN[0], PERIODEN[1]
    # Die Felder des aktuellen Klimamittels stehen weiterhin oben (die Seite liest sie dort);
    # die aeltere Periode kommt als "vergleich" dazu.
    ergebnis = {"quelle": "Deutscher Wetterdienst (DWD), Climate Data Center, opendata.dwd.de",
                "station": stationsangaben(datei_stationsliste(laden, aktuell), a.station),
                **periode(*aktuell),
                "vergleich": periode(*alt)}
    atomar_schreiben_json(Path(a.ziel), ergebnis)
    s = ergebnis["station"]
    print(f"Normalwerte fuer {s['name']} ({s['id']}, {s['hoehe_m']} m) gespeichert: {a.ziel}")
    for teil in (ergebnis, ergebnis["vergleich"]):
        print(f"  {teil['zeitraum']}: {teil['jahr']['temperatur_c']} °C und "
              f"{teil['jahr']['niederschlag_mm']} mm im Jahr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
