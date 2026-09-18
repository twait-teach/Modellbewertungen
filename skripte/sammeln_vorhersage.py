#!/usr/bin/env python3
"""
Sammelt vollstaendige Ensemble-Mitgliederdaten fuer das Meteogramm der Seite
"Vorhersage". Anders als sammeln.py (das pro Kalendertag ein Dokument mit nur
Hauptlauf + Ensemble-Kennzahlen fuehrt) speichert dieses Skript pro tatsaechlich
erkanntem MODELLLAUF ein eigenes Dokument mit allen Einzelmitgliedern -- das
ist Voraussetzung fuer den in der Aufgabenstellung geforderten Laufvergleich
("aktuell / vorheriger Lauf / davorliegender Lauf") und fuer die pro Mitglied
akkumulierte Darstellung.

Modelle:
  GFS       -- Datensatz gfs_seamless (Ensemble- UND Hauptlauf-Endpunkt).
               gfs025 allein liefert Mitgliederdaten nur bis Tag 10; erst
               gfs_seamless verlaengert das GEFS-Ensemble bis Tag 16 (siehe
               offizielle Doku: "GEFS needs gfs_seamless; gfs025 is None past
               10 days"). Es handelt sich dabei um denselben GEFS-Lauf, nur ab
               Tag 10 in der groeberen 0.5-Grad/6-stuendigen Original-
               Aufloesung des Modells -- keine Vermischung unterschiedlicher
               Initialisierungen, sondern ein Aufloesungs-Wechsel innerhalb
               desselben Laufs.
               Erlaubte Laufstunden: 00, 06, 12, 18 UTC. Horizont: 16 Tage.
  ECMWF-IFS -- Datensatz ecmwf_ifs025 (klassisches physikalisches IFS, NICHT
               die KI-Variante AIFS). Erlaubte Laufstunden: nur 00 und 12 UTC
               -- die eigenstaendigen 06- und 18-UTC-Ensembleläufe von ECMWF
               reichen offiziell nur rund sechs Tage weit und werden hier
               bewusst nicht als 15-Tage-Lauf erfasst. Horizont: 15 Tage.

Pro erkanntem Lauf wird eine Datei daten/vorhersage/<modell>_<initISO>.json
angelegt. Aeltere Laeufe werden nach dem Schreiben ueber AUFBEWAHREN hinaus
geloescht (vollstaendige Mitgliederdaten muessen laut Aufgabenstellung nicht
unbegrenzt archiviert werden).
"""

import argparse
import datetime as dt
import json
from pathlib import Path

from gemeinsam import atomar_schreiben_json, hole, mittel, perzentil

LAT, LON = 48.2456, 12.5228
TZ_NAME = "Europe/Berlin"
OUT = Path(__file__).resolve().parent.parent / "daten" / "vorhersage"
AUFBEWAHREN = 12  # so viele Laeufe je Modell werden mit vollen Mitgliederdaten behalten

MODELLE = {
    "gfs": {
        "name": "GFS",
        "ensemble_datensatz": "gfs_seamless",
        "hauptlauf_datensatz": "gfs_seamless",
        "meta_ensemble": "ncep_gefs025",
        "meta_hauptlauf": "ncep_gfs025",
        "erlaubte_stunden": {0, 6, 12, 18},
        "horizont": 16,
    },
    "ecmwf": {
        "name": "ECMWF-IFS",
        "ensemble_datensatz": "ecmwf_ifs025",
        "hauptlauf_datensatz": "ecmwf_ifs025",
        "meta_ensemble": "ecmwf_ifs025_ensemble",
        "meta_hauptlauf": "ecmwf_ifs025",
        "erlaubte_stunden": {0, 12},
        "horizont": 15,
    },
}


def laufinfo(datensatz, fehler):
    d = hole(f"https://api.open-meteo.com/data/{datensatz}/static/meta.json", fehlerliste=fehler)
    if not d or "last_run_initialisation_time" not in d:
        return None
    return {
        "lauf": dt.datetime.fromtimestamp(d["last_run_initialisation_time"], dt.timezone.utc),
        "verfuegbar": dt.datetime.fromtimestamp(d["last_run_availability_time"], dt.timezone.utc),
    }


def tageswerte_je_serie(d):
    """{spaltenname: {datum: wert}} aus einer /daily-Antwort."""
    daily = d["daily"]
    zeiten = daily["time"]
    out = {}
    for spalte, werte in daily.items():
        if spalte == "time" or not spalte.startswith("precipitation_sum"):
            continue
        out[spalte] = dict(zip(zeiten, werte))
    return out


def kumulieren(tagesreihe, ziele):
    """Tageswerte in Zieldatum-Reihenfolge aufsummieren. Fehlt irgendwo ein
    Tageswert, ist ab dort und fuer den Rest der Reihe nichts Verlaessliches
    mehr aufsummierbar -- die Kumulation bricht an dieser Stelle sauber ab
    (None fuer alle folgenden Leads), statt eine Luecke stillschweigend als
    0 mm zu behandeln."""
    out = []
    summe = 0.0
    abgebrochen = False
    for tag in ziele:
        v = tagesreihe.get(tag)
        if v is None or abgebrochen:
            abgebrochen = True
            out.append(None)
            continue
        summe += v
        out.append(round(summe, 2))
    return out


def verarbeite_modell(kurz, cfg, fehler, heute):
    ens_info = laufinfo(cfg["meta_ensemble"], fehler)
    if not ens_info:
        return None, [f"{kurz}: Ensemble-Laufzeit nicht abrufbar"]

    init = ens_info["lauf"]
    hinweise = []
    if init.hour not in cfg["erlaubte_stunden"]:
        return None, [f"{kurz}: Lauf {init:%d.%m. %HZ} nicht in erlaubten Stunden "
                       f"{sorted(cfg['erlaubte_stunden'])} -- wird uebersprungen"]

    horizont = cfg["horizont"]
    ziele = [(init.date() + dt.timedelta(days=lead)).isoformat() for lead in range(1, horizont + 1)]

    ens = hole("https://ensemble-api.open-meteo.com/v1/ensemble",
               {"latitude": LAT, "longitude": LON, "daily": "precipitation_sum",
                "forecast_days": horizont + 1, "timezone": TZ_NAME, "models": cfg["ensemble_datensatz"]},
               fehlerliste=fehler)
    if not ens:
        return None, [f"{kurz}: Ensemble-Daten nicht abrufbar"]

    serien = tageswerte_je_serie(ens)
    if "precipitation_sum" not in serien:
        return None, [f"{kurz}: Kontrolllauf-Spalte fehlt in der Antwort"]

    kontrolle_kum = kumulieren(serien["precipitation_sum"], ziele)
    mitglieder_keys = sorted(k for k in serien if k != "precipitation_sum")
    mitglieder_kum = [kumulieren(serien[k], ziele) for k in mitglieder_keys]

    # --- Pruefungen vor dem Speichern ---
    erwartete_mitglieder = {"gfs": 30, "ecmwf": 50}[kurz]
    if len(mitglieder_keys) < erwartete_mitglieder - 2:  # etwas Toleranz, Modelle aendern Mitgliederzahl gelegentlich
        hinweise.append(f"nur {len(mitglieder_keys)} statt erwarteter {erwartete_mitglieder} Mitglieder")
    letzter_lead_leer = sum(1 for s in mitglieder_kum if s[-1] is None)
    if letzter_lead_leer > len(mitglieder_kum) * 0.5:
        hinweise.append(f"Horizont unvollstaendig: bei {letzter_lead_leer}/{len(mitglieder_kum)} "
                         f"Mitgliedern bricht die Reihe vor Tag {horizont} ab")

    # --- Kennzahlen je Lead aus den AKKUMULIERTEN Mitgliederkurven ---
    mittel_kum, p10_kum, p50_kum, p90_kum, min_kum, max_kum, n_kum = [], [], [], [], [], [], []
    for i in range(horizont):
        w = sorted(s[i] for s in mitglieder_kum if s[i] is not None)
        if not w:
            mittel_kum.append(None); p10_kum.append(None); p50_kum.append(None)
            p90_kum.append(None); min_kum.append(None); max_kum.append(None); n_kum.append(0)
            continue
        mittel_kum.append(round(sum(w) / len(w), 2))
        p10_kum.append(round(perzentil(w, 0.10), 2))
        p50_kum.append(round(perzentil(w, 0.50), 2))
        p90_kum.append(round(perzentil(w, 0.90), 2))
        min_kum.append(round(w[0], 2))
        max_kum.append(round(w[-1], 2))
        n_kum.append(len(w))

    # --- Deterministischer Hauptlauf, nur wenn seine Initialisierung nachweislich passt ---
    hl_info = laufinfo(cfg["meta_hauptlauf"], fehler)
    hauptlauf_kum = None
    if hl_info and hl_info["lauf"] == init:
        # Die normale /v1/forecast-Schnittstelle (anders als die Ensemble-API)
        # erlaubt hoechstens forecast_days=16 (heute + 15 Tage). Reicht der
        # Ensemble-Horizont weiter (GFS: 16 Tage), bleiben die letzten Leads
        # beim Hauptlauf schlicht leer -- kumulieren() haengt dort ab, sobald
        # ein Tageswert fehlt.
        hl = hole("https://api.open-meteo.com/v1/forecast",
                  {"latitude": LAT, "longitude": LON, "daily": "precipitation_sum",
                   "forecast_days": min(horizont + 1, 16), "timezone": TZ_NAME,
                   "models": cfg["hauptlauf_datensatz"]},
                  fehlerliste=fehler)
        if hl:
            hauptlauf_kum = kumulieren(dict(zip(hl["daily"]["time"], hl["daily"]["precipitation_sum"])), ziele)
    elif hl_info:
        hinweise.append(f"deterministischer Lauf ist {hl_info['lauf']:%d.%m. %HZ}, "
                         f"passt nicht zum Ensemble-Lauf {init:%d.%m. %HZ} -- nicht eingebettet")

    lauf = {
        "modell": kurz,
        "modellname": cfg["name"],
        "ensemble_datensatz": cfg["ensemble_datensatz"],
        "init": init.strftime("%Y-%m-%dT%H:%MZ"),
        "verfuegbar_seit": ens_info["verfuegbar"].strftime("%Y-%m-%dT%H:%MZ"),
        "abgerufen": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "horizont_tage": horizont,
        "mitglieder_n": len(mitglieder_keys),
        "leads": list(range(1, horizont + 1)),
        "ziele": ziele,
        "kontrolllauf_kumulativ": kontrolle_kum,
        "mitglieder_kumulativ": mitglieder_kum,
        "hauptlauf_kumulativ": hauptlauf_kum,
        "mittel_kumulativ": mittel_kum,
        "p10_kumulativ": p10_kum,
        "p50_kumulativ": p50_kum,
        "p90_kumulativ": p90_kum,
        "min_kumulativ": min_kum,
        "max_kumulativ": max_kum,
        "n_kumulativ": n_kum,
        "vollstaendig": letzter_lead_leer == 0 and len(mitglieder_keys) >= erwartete_mitglieder - 2,
        "hinweise": hinweise,
    }
    return lauf, hinweise


def dateiname(kurz, init: dt.datetime) -> str:
    return f"{kurz}_{init.strftime('%Y-%m-%dT%H')}.json"


def aufraeumen(kurz):
    """Nur die AUFBEWAHREN juengsten Laeufe je Modell behalten."""
    dateien = sorted(OUT.glob(f"{kurz}_*.json"), reverse=True)
    entfernt = []
    for pfad in dateien[AUFBEWAHREN:]:
        pfad.unlink()
        entfernt.append(pfad.name)
    return entfernt


def main():
    ap = argparse.ArgumentParser(description="Ensemble-Meteogrammdaten fuer die Vorhersage-Seite sammeln")
    ap.add_argument("--modell", choices=["gfs", "ecmwf", "beide"], default="beide")
    args = ap.parse_args()
    modelle = ("gfs", "ecmwf") if args.modell == "beide" else (args.modell,)

    OUT.mkdir(parents=True, exist_ok=True)
    heute = dt.datetime.now(dt.timezone.utc).date()
    fehler = []
    for kurz in modelle:
        cfg = MODELLE[kurz]

        # --- Erst nur die Metadaten pruefen (billig): ist ueberhaupt ein neuer
        # Lauf da, den wir noch nicht gespeichert haben? Nur dann folgt der
        # teure Abruf aller Ensemblemitglieder. So kann dieses Skript stuend-
        # lich laufen, ohne bei jedem Durchlauf alles neu herunterzuladen.
        vorab_info = laufinfo(cfg["meta_ensemble"], [])
        if vorab_info and vorab_info["lauf"].hour in cfg["erlaubte_stunden"]:
            erwarteter_pfad = OUT / dateiname(kurz, vorab_info["lauf"])
            if erwarteter_pfad.exists():
                try:
                    bereits = json.loads(erwarteter_pfad.read_text(encoding="utf-8"))
                except Exception:
                    bereits = {}
                if bereits.get("vollstaendig"):
                    print(f"{kurz}: Lauf {vorab_info['lauf']:%Y-%m-%dT%H:%MZ} bereits vollstaendig gespeichert -- nichts zu tun")
                    continue
                print(f"{kurz}: Lauf {vorab_info['lauf']:%Y-%m-%dT%H:%MZ} war beim letzten Mal noch unvollstaendig -- erneuter Versuch")

        lauf, hinweise = verarbeite_modell(kurz, cfg, fehler, heute)
        if not lauf:
            print(f"{kurz}: kein neuer Lauf gespeichert. " + "; ".join(hinweise))
            continue
        init = dt.datetime.strptime(lauf["init"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
        ziel = OUT / dateiname(kurz, init)
        neu = not ziel.exists()
        atomar_schreiben_json(ziel, lauf, separators=(",", ":"))
        entfernt = aufraeumen(kurz)
        status = "neu gespeichert" if neu else "aktualisiert (nochmal abgerufen)"
        print(f"{kurz}: Lauf {lauf['init']} {status} -- {lauf['mitglieder_n']} Mitglieder, "
              f"Horizont {lauf['horizont_tage']} Tage, hauptlauf={'ja' if lauf['hauptlauf_kumulativ'] else 'nein'}, "
              f"vollstaendig={lauf['vollstaendig']}")
        if hinweise:
            print("  Hinweise:", *hinweise, sep="\n    ")
        if entfernt:
            print(f"  aufgeraeumt: {len(entfernt)} aeltere Laufdatei(en) entfernt")
    if fehler:
        print("FEHLER:", *fehler, sep="\n  ")


if __name__ == "__main__":
    main()
