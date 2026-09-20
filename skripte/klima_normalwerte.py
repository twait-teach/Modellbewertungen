#!/usr/bin/env python3
"""Holt die amtlichen Klima-Normalwerte 1991-2020 einer DWD-Station.

Quelle: Deutscher Wetterdienst, Climate Data Center, frei zugaengliche Dateien
unter opendata.dwd.de (Monatsmittel der Lufttemperatur und Monatssummen des
Niederschlags, Bezugszeitraum 1991-2020).

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
         "climate/multi_annual/mean_91-20/")
DATEIEN = {"temperatur_c": "Temperatur_1991-2020.txt",
           "niederschlag_mm": "Niederschlag_1991-2020.txt"}
STATIONSLISTE = "Temperatur_1991-2020_Stationsliste.txt"


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


def main(argv=None, laden=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--station", default="3366", help="DWD-Stationskennung (Vorgabe: 3366, Mühldorf)")
    p.add_argument("--ziel", default=str(ZIEL))
    a = p.parse_args(argv)
    laden = laden or (lambda datei: hole(BASIS + datei, roh=True).decode("latin-1"))

    ergebnis = {"quelle": "Deutscher Wetterdienst (DWD), Climate Data Center, opendata.dwd.de",
                "zeitraum": "1991-2020",
                "station": stationsangaben(laden(STATIONSLISTE), a.station),
                "jahr": {}}
    for feld, datei in DATEIEN.items():
        monate, jahr = werte_der_station(laden(datei), a.station)
        ergebnis[feld] = monate
        ergebnis["jahr"][feld] = jahr
    atomar_schreiben_json(Path(a.ziel), ergebnis)
    s = ergebnis["station"]
    print(f"Normalwerte 1991-2020 fuer {s['name']} ({s['id']}, {s['hoehe_m']} m) gespeichert: {a.ziel}")
    print(f"  Temperatur:   {ergebnis['jahr']['temperatur_c']} °C im Jahr")
    print(f"  Niederschlag: {ergebnis['jahr']['niederschlag_mm']} mm im Jahr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
