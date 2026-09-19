#!/usr/bin/env python3
"""
Sammelt vollstaendige Ensemble-Mitgliederdaten fuer die drei Diagrammbereiche
der Seite "Vorhersage": 2-m-Temperatur, aufsummierter Niederschlag und
850-hPa-Temperatur. Anders als sammeln.py (das pro Kalendertag ein Dokument
mit nur Hauptlauf + Ensemble-Kennzahlen fuehrt) speichert dieses Skript pro
tatsaechlich erkanntem MODELLLAUF ein eigenes Dokument mit allen Einzel-
mitgliedern -- das ist Voraussetzung fuer den geforderten Laufvergleich
("aktuell / vorheriger Lauf / davorliegender Lauf") und fuer die pro Mitglied
akkumulierte Niederschlagsdarstellung.

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

Niederschlag wird weiterhin ZUERST JE MITGLIED AKKUMULIERT und erst danach
werden Mittel/Perzentile aus den akkumulierten Kurven gebildet (kumulieren()).
Temperatur (2 m und 850 hPa) wird NICHT akkumuliert und NICHT auf einen Wert
pro Tag verdichtet: gespeichert wird die vollstaendige stuendliche Reihe, wie
open-meteo sie liefert (in der Langfrist je nach Modell auch groeber --
es wird genommen, was da ist). Mittel und Perzentile werden je Zeitschritt
direkt aus den zu diesem Zeitpunkt vorhandenen Mitgliedswerten gebildet;
fehlt ein Mitgliedswert zu einem Zeitpunkt, wird NUR dieser Zeitpunkt fuer
dieses Mitglied ausgeschlossen (anders als beim Niederschlag bricht das nicht
die Kette fuer die folgenden Zeitpunkte, da Temperatur nicht kumuliert wird).
So entsteht ein echtes Ensemble-Meteogramm mit Tagesgang bei 2 m und zeitlich
hoch aufgeloesten Luftmassenwechseln bei 850 hPa.

Pro erkanntem Lauf wird eine Datei daten/vorhersage/<modell>_<initISO>.json
angelegt -- aber ERST, wenn Laufweite und Mitgliederzahl vollstaendig
vorliegen (siehe VOLLSTAENDIGKEITSPRUEFUNG in verarbeite_modell()); ein noch
unvollstaendiger Lauf wird nicht gespeichert, sondern beim naechsten stuend-
lichen Durchlauf erneut versucht. Aeltere Laeufe werden nach dem Schreiben
ueber AUFBEWAHREN hinaus geloescht (vollstaendige Mitgliederdaten muessen laut
Aufgabenstellung nicht unbegrenzt archiviert werden).
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


def tageswerte_je_serie(d, praefix):
    """{spaltenname: {datum: wert}} aus dem 'daily'-Block einer Antwort."""
    daily = d.get("daily") or {}
    zeiten = daily.get("time", [])
    out = {}
    for spalte, werte in daily.items():
        if spalte == "time" or not spalte.startswith(praefix):
            continue
        out[spalte] = dict(zip(zeiten, werte))
    return out


def stundenwerte_je_serie(d, praefix):
    """{spaltenname: {'JJJJ-MM-TTTHH:MM': wert}} aus dem 'hourly'-Block."""
    hourly = d.get("hourly") or {}
    zeiten = hourly.get("time", [])
    out = {}
    for spalte, werte in hourly.items():
        if spalte == "time" or not spalte.startswith(praefix):
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


def stundenreihe(stundenserie, zeiten):
    """Fuer Temperatur: die vollstaendige stuendliche Reihe in der Reihenfolge
    der uebergebenen Zeitstempel -- KEINE Akkumulation und KEINE Verdichtung
    auf einen Tageswert. Fehlt ein Zeitschritt, ist NUR dieser None."""
    return [stundenserie.get(t) for t in zeiten]


def aggregiere_lead(mitglieder_werte, lead_index, runden=2):
    """Mittel/Perzentile/Spannweite fuer EINEN Lead-Index aus den Werten aller
    Mitglieder an dieser Stelle -- fehlende Werte (None) werden ausgeschlossen,
    nicht als 0 gewertet. Gemeinsam fuer akkumulierte (Niederschlag) und nicht
    akkumulierte (Temperatur) Reihen nutzbar, da die Rundenlogik nur auf den
    bereits fertigen Werten an diesem Lead arbeitet."""
    w = sorted(s[lead_index] for s in mitglieder_werte if s[lead_index] is not None)
    if not w:
        return {"mittel": None, "p10": None, "p50": None, "p90": None, "min": None, "max": None, "n": 0}
    return {
        "mittel": round(sum(w) / len(w), runden),
        "p10": round(perzentil(w, 0.10), runden),
        "p50": round(perzentil(w, 0.50), runden),
        "p90": round(perzentil(w, 0.90), runden),
        "min": round(w[0], runden),
        "max": round(w[-1], runden),
        "n": len(w),
    }


def aggregiere_alle_leads(mitglieder_werte, horizont, runden=2):
    kennzahlen = [aggregiere_lead(mitglieder_werte, i, runden) for i in range(horizont)]
    zusammen = {"mittel": [], "p10": [], "p50": [], "p90": [], "min": [], "max": [], "n": []}
    for k in kennzahlen:
        for feld in zusammen:
            zusammen[feld].append(k[feld])
    return zusammen


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

    # EIN Abruf liefert Niederschlag (daily) UND beide Temperaturreihen
    # (hourly) zusammen -- getestet, dass open-meteo daily+hourly im selben
    # Aufruf kombiniert; das haelt die Zahl der API-Aufrufe gleich niedrig
    # wie vor der Temperatur-Erweiterung.
    ens = hole("https://ensemble-api.open-meteo.com/v1/ensemble",
               {"latitude": LAT, "longitude": LON,
                "daily": "precipitation_sum",
                "hourly": "temperature_2m,temperature_850hPa",
                "forecast_days": horizont + 1, "timezone": TZ_NAME, "models": cfg["ensemble_datensatz"]},
               fehlerliste=fehler)
    if not ens:
        return None, [f"{kurz}: Ensemble-Daten nicht abrufbar"]

    # --- Niederschlag: wie bisher, akkumuliert ---
    serien_regen = tageswerte_je_serie(ens, "precipitation_sum")
    if "precipitation_sum" not in serien_regen:
        return None, [f"{kurz}: Kontrolllauf-Spalte (Niederschlag) fehlt in der Antwort"]
    kontrolle_regen = kumulieren(serien_regen["precipitation_sum"], ziele)
    mitglieder_keys = sorted(k for k in serien_regen if k != "precipitation_sum")
    mitglieder_regen = [kumulieren(serien_regen[k], ziele) for k in mitglieder_keys]

    # --- Temperatur: 2 m und 850 hPa, NICHT akkumuliert, VOLLE stuendliche Reihe ---
    temperaturen = {}
    zieltage = set(ziele)
    for feld, praefix in (("temperatur_2m", "temperature_2m"), ("temperatur_850hpa", "temperature_850hPa")):
        serien_temp = stundenwerte_je_serie(ens, praefix)
        if praefix not in serien_temp:
            temperaturen[feld] = None
            hinweise.append(f"{feld}: Spalte fehlt in der Antwort -- fuer diesen Lauf nicht gespeichert")
            continue
        # Alle Zeitschritte innerhalb des Vorhersagefensters, chronologisch.
        # Die Zeitstempel sind bereits Ortszeit Europe/Berlin, weil die API mit
        # timezone=Europe/Berlin abgefragt wird (TZ_NAME) -- open-meteo liefert
        # die hourly-"time"-Werte dann als lokale Zeit ohne Zonensuffix.
        # Die API liefert je nach Modell/Reichweite stuendlich oder (in der
        # Langfrist) groeber -- es wird genommen, was da ist, ohne zu verdichten.
        zeiten = [t for t in sorted(serien_temp[praefix]) if t[:10] in zieltage]
        temp_keys = sorted(k for k in serien_temp if k != praefix)
        kontrolle_t = stundenreihe(serien_temp[praefix], zeiten)
        mitglieder_t = [stundenreihe(serien_temp[k], zeiten) for k in temp_keys]
        kennzahlen_t = aggregiere_alle_leads(mitglieder_t, len(zeiten))
        temperaturen[feld] = {
            "zeiten": zeiten,
            "zeitzone": TZ_NAME,
            "kontrolllauf": kontrolle_t,
            "mitglieder": mitglieder_t,
            "hauptlauf": None,  # wird unten befuellt, falls Hauptlauf passt
            **kennzahlen_t,
        }

    # --- Pruefungen vor dem Speichern (gilt fuer den GESAMTEN Lauf: erst
    # speichern, wenn Laufweite UND Mitgliederzahl vollstaendig vorliegen) ---
    erwartete_mitglieder = {"gfs": 30, "ecmwf": 50}[kurz]
    if len(mitglieder_keys) < erwartete_mitglieder - 2:  # etwas Toleranz, Modelle aendern Mitgliederzahl gelegentlich
        hinweise.append(f"nur {len(mitglieder_keys)} statt erwarteter {erwartete_mitglieder} Mitglieder")
    letzter_lead_leer = sum(1 for s in mitglieder_regen if s[-1] is None)
    if letzter_lead_leer > len(mitglieder_regen) * 0.5:
        hinweise.append(f"Horizont unvollstaendig: bei {letzter_lead_leer}/{len(mitglieder_regen)} "
                         f"Mitgliedern bricht die Niederschlagsreihe vor Tag {horizont} ab")
    vollstaendig = letzter_lead_leer == 0 and len(mitglieder_keys) >= erwartete_mitglieder - 2

    # Auch die stuendlichen Temperaturreihen muessen den vorgesehenen Horizont
    # abdecken, sonst gilt der Lauf als noch nicht vollstaendig (und wird von
    # main() noch nicht gespeichert, sondern beim naechsten Durchlauf erneut
    # versucht). Geprueft wird: die Reihe existiert, sie reicht bis zum letzten
    # Vorhersagetag, und zum letzten Zeitpunkt liegen ueberhaupt Mitgliedswerte vor.
    letzter_tag = ziele[-1]
    for feld in ("temperatur_2m", "temperatur_850hpa"):
        t = temperaturen.get(feld)
        if not t:
            vollstaendig = False
            continue
        if not t["zeiten"] or t["zeiten"][-1][:10] != letzter_tag:
            hinweise.append(f"{feld}: stuendliche Reihe reicht nicht bis {letzter_tag}")
            vollstaendig = False
        elif not t["n"] or t["n"][-1] == 0:
            hinweise.append(f"{feld}: zum letzten Zeitpunkt liegen keine Mitgliedswerte vor")
            vollstaendig = False

    # --- Kennzahlen Niederschlag aus den AKKUMULIERTEN Mitgliederkurven ---
    kennzahlen_regen = aggregiere_alle_leads(mitglieder_regen, horizont)

    # --- Deterministischer Hauptlauf, nur wenn seine Initialisierung nachweislich passt ---
    hl_info = laufinfo(cfg["meta_hauptlauf"], fehler)
    hauptlauf_regen = None
    if hl_info and hl_info["lauf"] == init:
        # Die normale /v1/forecast-Schnittstelle (anders als die Ensemble-API)
        # erlaubt hoechstens forecast_days=16 (heute + 15 Tage). Reicht der
        # Ensemble-Horizont weiter (GFS: 16 Tage), bleiben die letzten Leads
        # beim Hauptlauf schlicht leer.
        hl = hole("https://api.open-meteo.com/v1/forecast",
                  {"latitude": LAT, "longitude": LON,
                   "daily": "precipitation_sum",
                   "hourly": "temperature_2m,temperature_850hPa",
                   "forecast_days": min(horizont + 1, 16), "timezone": TZ_NAME,
                   "models": cfg["hauptlauf_datensatz"]},
                  fehlerliste=fehler)
        if hl:
            if hl.get("daily"):
                hauptlauf_regen = kumulieren(dict(zip(hl["daily"]["time"], hl["daily"]["precipitation_sum"])), ziele)
            hl_hourly = stundenwerte_je_serie(hl, "temperature_2m") | stundenwerte_je_serie(hl, "temperature_850hPa")
            for feld, praefix in (("temperatur_2m", "temperature_2m"), ("temperatur_850hpa", "temperature_850hPa")):
                if temperaturen.get(feld) and praefix in hl_hourly:
                    # exakt dieselben Zeitstempel wie die Ensemblereihe, damit
                    # Hauptlauf und Ensemble Punkt fuer Punkt vergleichbar sind
                    temperaturen[feld]["hauptlauf"] = stundenreihe(hl_hourly[praefix], temperaturen[feld]["zeiten"])
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
        "kontrolllauf_kumulativ": kontrolle_regen,
        "mitglieder_kumulativ": mitglieder_regen,
        "hauptlauf_kumulativ": hauptlauf_regen,
        "mittel_kumulativ": kennzahlen_regen["mittel"],
        "p10_kumulativ": kennzahlen_regen["p10"],
        "p50_kumulativ": kennzahlen_regen["p50"],
        "p90_kumulativ": kennzahlen_regen["p90"],
        "min_kumulativ": kennzahlen_regen["min"],
        "max_kumulativ": kennzahlen_regen["max"],
        "n_kumulativ": kennzahlen_regen["n"],
        "temperatur_2m": temperaturen.get("temperatur_2m"),
        "temperatur_850hpa": temperaturen.get("temperatur_850hpa"),
        "vollstaendig": vollstaendig,
        "hinweise": hinweise,
    }
    return lauf, hinweise


def dateiname(kurz, init: dt.datetime) -> str:
    return f"{kurz}_{init.strftime('%Y-%m-%dT%H')}.json"


def aufraeumen(kurz):
    """Nur die AUFBEWAHREN juengsten Laeufe je Modell behalten. Sortiert wird
    nicht nach Dateiname/Stunde, sondern nach der tatsaechlichen, im
    Dateinamen enthaltenen vollen Initialisierung (JJJJ-MM-TTThh) -- der
    Dateiname ist so gebaut, dass ein einfacher Textvergleich schon korrekt
    chronologisch sortiert (siehe dateiname())."""
    dateien = sorted(OUT.glob(f"{kurz}_*.json"), key=lambda p: p.name, reverse=True)
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

        # Ein Lauf wird ERST gespeichert, wenn er vollstaendig ist (erwartete
        # Laufweite UND Mitgliederzahl). Ein noch unvollstaendiger Lauf wird
        # NICHT geschrieben -- weder neu noch ueberschreibend -- sondern beim
        # naechsten stuendlichen Durchlauf erneut versucht (siehe Vorab-Pruefung
        # oben, die dann wieder "unvollstaendig" vorfindet und es erneut versucht).
        if not lauf["vollstaendig"]:
            print(f"{kurz}: Lauf {lauf['init']} noch nicht vollstaendig -- wird noch NICHT gespeichert. "
                  + ("Hinweise: " + "; ".join(hinweise) if hinweise else ""))
            continue

        init = dt.datetime.strptime(lauf["init"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
        ziel = OUT / dateiname(kurz, init)
        neu = not ziel.exists()
        atomar_schreiben_json(ziel, lauf, separators=(",", ":"))
        entfernt = aufraeumen(kurz)
        status = "neu gespeichert" if neu else "aktualisiert (nochmal abgerufen)"
        print(f"{kurz}: Lauf {lauf['init']} {status} -- {lauf['mitglieder_n']} Mitglieder, "
              f"Horizont {lauf['horizont_tage']} Tage, hauptlauf={'ja' if lauf['hauptlauf_kumulativ'] else 'nein'}, "
              f"temp2m={'ja' if lauf['temperatur_2m'] else 'nein'}, temp850={'ja' if lauf['temperatur_850hpa'] else 'nein'}")
        if hinweise:
            print("  Hinweise:", *hinweise, sep="\n    ")
        if entfernt:
            print(f"  aufgeraeumt: {len(entfernt)} aeltere Laufdatei(en) entfernt")
    if fehler:
        print("FEHLER:", *fehler, sep="\n  ")


if __name__ == "__main__":
    main()
