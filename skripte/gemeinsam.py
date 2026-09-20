#!/usr/bin/env python3
"""
Gemeinsame Hilfsfunktionen fuer sammeln.py, sammeln_vorhersage.py und historie.py.

Buendelt drei Dinge, die an mehreren Stellen gebraucht werden:
  - robuster HTTP-Abruf mit Wiederholung und Backoff (Fehler werden gesammelt,
    nicht geworfen -- ein einzelner ausgefallener Abruf darf den Rest des Laufs
    nicht abbrechen),
  - atomares Schreiben (erst temporaere Datei, dann Umbenennen -- ein Absturz
    mitten im Schreiben darf keine vorhandene, gueltige Datei beschaedigen),
  - lineare Perzentil-Interpolation, wie in der Meteorologie ueblich.
"""

import datetime as dt
import json
import os
import statistics
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


def hole(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
    """GET mit exponentiellem Backoff. Gibt None zurueck (statt zu werfen), wenn
    alle Versuche fehlschlagen, und traegt den Grund in fehlerliste ein, falls
    eine Liste uebergeben wurde. So kann der Aufrufer entscheiden, ob ein
    fehlender Wert den restlichen Lauf abbricht oder nur als Luecke stehen bleibt.
    """
    letzter = None
    for i in range(versuche):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            if roh:
                return r.content
            d = r.json()
            if isinstance(d, dict) and d.get("error"):
                raise RuntimeError(d.get("reason", "API-Fehler"))
            return d
        except Exception as e:  # noqa: BLE001
            letzter = e
            if i < versuche - 1:
                time.sleep(2 ** i)
    if fehlerliste is not None:
        try:
            host = url.split("/")[2]
        except IndexError:
            host = url
        fehlerliste.append(f"{host}: {letzter}")
    return None


def atomar_schreiben(pfad: Path, inhalt: str, encoding="utf-8"):
    """Erst in eine temporaere Datei im selben Verzeichnis schreiben, dann
    per os.replace umbenennen. os.replace ist auf POSIX-Systemen atomar --
    ein Prozess, der die Zieldatei gerade liest, sieht entweder die alte
    oder die neue Version, nie eine halb geschriebene."""
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + f".tmp{os.getpid()}")
    tmp.write_text(inhalt, encoding=encoding)
    os.replace(tmp, pfad)


def atomar_schreiben_json(pfad: Path, objekt, **json_kwargs):
    kwargs = {"ensure_ascii": False, "indent": 1}
    kwargs.update(json_kwargs)
    atomar_schreiben(pfad, json.dumps(objekt, **kwargs))


def perzentil(sortiert, q):
    """Lineare Interpolation zwischen den Rangwerten (numpy-Methode 'linear'),
    wie sie in Ensemble-Meteogrammen ueblich ist."""
    if not sortiert:
        return None
    if len(sortiert) == 1:
        return sortiert[0]
    pos = q * (len(sortiert) - 1)
    unten = int(pos)
    rest = pos - unten
    if unten + 1 >= len(sortiert):
        return sortiert[-1]
    return sortiert[unten] + rest * (sortiert[unten + 1] - sortiert[unten])


def mittel(werte):
    werte = [w for w in werte if w is not None]
    return round(statistics.fmean(werte), 3) if werte else None


# ---------------------------------------------------------------- Format der Laufdateien
FORMAT_MODELLNAH = "modellnativ-v1"
LAUF_FELDER = ("temperatur_2m", "temperatur_850hpa", "niederschlag")


def ist_aktuelles_format(lauf):
    """Einzige Formatpruefung fuer Ensemble-Laufdateien (Sammler UND Builder).

    Ein Lauf gilt nur dann als aktuell und darstellbar, wenn er den Marker
    ``zeitauflosung == "modellnativ-v1"`` traegt und in allen drei Bereichen
    Zeitstempel, Unixzeiten gleicher Laenge und Ensemblemitglieder besitzt.
    Beim GFS ist zusaetzlich der Kontrolllauf Pflicht; ECMWF hat keinen.
    Die Frontend-Funktion ``formatAktuell`` in skripte/vorlage.html folgt exakt
    denselben Regeln (durch einen Browsertest abgesichert).
    """
    if not isinstance(lauf, dict) or lauf.get("zeitauflosung") != FORMAT_MODELLNAH:
        return False
    for feld in LAUF_FELDER:
        reihe = lauf.get(feld)
        if not isinstance(reihe, dict):
            return False
        zeiten = reihe.get("zeiten")
        unix = reihe.get("zeitpunkte_unix")
        if (not isinstance(zeiten, list) or not zeiten
                or not isinstance(unix, list) or len(unix) != len(zeiten)):
            return False
        mitglieder = reihe.get("mitglieder")
        if not isinstance(mitglieder, list) or not mitglieder:
            return False
        if lauf.get("modell") == "gfs" and (
                not isinstance(reihe.get("kontrolllauf"), list) or not reihe["kontrolllauf"]):
            return False
    return True


def ohne_feld(objekt: dict, feld: str) -> dict:
    """Flache Kopie ohne ein einzelnes Feld -- fuer fachliche Vergleiche, die
    einen reinen Zeitstempel ignorieren sollen."""
    return {k: v for k, v in objekt.items() if k != feld}


def stunden_im_ortstag(datum, zone="Europe/Berlin"):
    """Anzahl der Stunden des Ortstages ``JJJJ-MM-TT`` (23, 24 oder 25).

    Ein Ortstag hat wegen der Zeitumstellung nicht immer 24 Stunden. Als
    Vollstaendigkeitsgrenze fuer Tagessummen taugt daher nur diese Zahl, nicht
    pauschal 24: sonst faellt der 23-Stunden-Tag im Maerz aus der Auswertung,
    und am 25-Stunden-Tag im Oktober bliebe eine fehlende Stunde unbemerkt.
    """
    tag = dt.date.fromisoformat(str(datum)[:10])
    z = ZoneInfo(zone)
    anfang = dt.datetime.combine(tag, dt.time(0), tzinfo=z)
    folgetag = dt.datetime.combine(tag + dt.timedelta(days=1), dt.time(0), tzinfo=z)
    return round((folgetag.astimezone(dt.timezone.utc) - anfang.astimezone(dt.timezone.utc)).total_seconds() / 3600)
