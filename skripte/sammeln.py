#!/usr/bin/env python3
"""
Datensammler fuer den Niederschlags-Modellvergleich Muehldorf.

Erzeugt JSON-Dokumente fuer die Artifact-Datenbank:
  out/forecasts_<Laufdatum>.json   14 Leads x (Hauptlauf, Ensemble-Mittel, P10, P90, Min, Max)
  out/messungen_<Monat>.json       Tagessummen der DWD-Station 03366, Ortszeit 00-24 Uhr

Referenz ist die Station Muehldorf (03366), nicht ERA5: aus den STUENDLICHEN
DWD-Werten (UTC) werden Kalendertagssummen in Ortszeit gebildet, damit sie zum
Tagesraster der Vorhersagen passen. Der DWD-Klimatagswert (RSK) taugt dafuer
nicht -- der laeuft von 06 UTC bis 06 UTC und ist um Stunden versetzt.
"""

import csv
import datetime as dt
import glob
import io
import json
import statistics
import sys
import time
import zipfile
import zoneinfo
from pathlib import Path

import requests

import argparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemeinsam import atomar_schreiben_json

LAT, LON = 48.2456, 12.5228
TZ_NAME = "Europe/Berlin"
TZ = zoneinfo.ZoneInfo(TZ_NAME)
STATION = "03366"          # DWD-Klimastation Muehldorf, 48.2790 N / 12.5024 E, 406 m
HAUPT = {"gfs": "gfs_seamless", "ecmwf": "ecmwf_ifs025"}
ENSEMBLE = {"gfs": "gfs_seamless", "ecmwf": "ecmwf_ifs025"}  # gfs025 allein liefert Mitglieder nur bis Tag 10
OUT = Path(__file__).resolve().parent.parent / "daten"

fehler = []


def hole(url, params=None, roh=False, versuche=4):
    letzter = None
    for i in range(versuche):
        try:
            r = requests.get(url, params=params, timeout=90)
            r.raise_for_status()
            if roh:
                return r.content
            d = r.json()
            if d.get("error"):
                raise RuntimeError(d.get("reason", "API-Fehler"))
            return d
        except Exception as e:  # noqa: BLE001
            letzter = e
            if i < versuche - 1:
                time.sleep(2 ** i)
    fehler.append(f"{url.split('/')[2]}: {letzter}")
    return None


# ---------------------------------------------------------------- Vorhersagen
# Welcher open-meteo-Datensatz hinter welcher Modell-Kennung steckt (fuer die Laufpruefung)
META = {("gfs", "hl"): "ncep_gfs025", ("gfs", "ens"): "ncep_gefs025",
        ("ecmwf", "hl"): "ecmwf_ifs025", ("ecmwf", "ens"): "ecmwf_ifs025_ensemble"}
ERWARTETE_LAUFSTUNDE = 0      # nur der 00-UTC-Lauf soll erfasst werden


def laufinfo(datensatz):
    """Initialisierungszeit des zuletzt veroeffentlichten Laufs.

    Wichtig: open-meteo liefert bei einem noch nicht fertigen Lauf klaglos den
    vorherigen. Ohne diese Pruefung landen also stillschweigend aeltere Daten
    im Bestand, ohne dass irgendetwas fehlschlaegt.
    """
    d = hole(f"https://api.open-meteo.com/data/{datensatz}/static/meta.json")
    if not d or "last_run_initialisation_time" not in d:
        return None
    return {
        "lauf": dt.datetime.fromtimestamp(d["last_run_initialisation_time"], dt.timezone.utc),
        "verfuegbar": dt.datetime.fromtimestamp(d["last_run_availability_time"], dt.timezone.utc),
    }


MAX_LEAD = 14  # bis Tag 14, fuer das Auswertungsfenster Tag 8-14 auf der Analyse-Seite


def hauptlauf(modell_id):
    """Gibt (Werte, erfolgreich) zurueck. erfolgreich=False bedeutet: der Abruf
    ist nach allen Wiederholungen endgueltig gescheitert -- der Aufrufer darf
    dann bestehende Werte NICHT durch das leere Ergebnis ueberschreiben."""
    d = hole("https://api.open-meteo.com/v1/forecast",
             {"latitude": LAT, "longitude": LON, "daily": "precipitation_sum",
              "forecast_days": MAX_LEAD + 1, "timezone": TZ_NAME, "models": modell_id})
    if not d:
        return {}, False
    return {t: v for t, v in zip(d["daily"]["time"], d["daily"]["precipitation_sum"])}, True


def ensemble(modell_id):
    """Alle Member abrufen und daraus Mittel, Perzentile und Spannweite bilden.
    Gibt (Werte, Mitgliederzahl, erfolgreich) zurueck -- siehe hauptlauf()."""
    d = hole("https://ensemble-api.open-meteo.com/v1/ensemble",
             {"latitude": LAT, "longitude": LON, "daily": "precipitation_sum",
              "forecast_days": MAX_LEAD + 1, "timezone": TZ_NAME, "models": modell_id})
    if not d:
        return {}, 0, False
    daily = d["daily"]
    spalten = [k for k in daily if k.startswith("precipitation_sum")]
    ergebnis = {}
    for i, t in enumerate(daily["time"]):
        w = sorted(daily[s][i] for s in spalten if daily[s][i] is not None)
        if not w:
            continue
        ergebnis[t] = {
            "mittel": round(statistics.fmean(w), 2),
            "p10": round(perzentil(w, 0.10), 2),
            "p50": round(perzentil(w, 0.50), 2),
            "p90": round(perzentil(w, 0.90), 2),
            "min": round(w[0], 2),
            "max": round(w[-1], 2),
            "n": len(w),
            # Anteil der Member ueber 5 mm = Wahrscheinlichkeit fuer nennenswerten Regen
            "p_ueber5": round(sum(1 for x in w if x >= 5.0) / len(w), 3),
        }
    return ergebnis, len(spalten), True


def perzentil(sortiert, q):
    """Lineare Interpolation, wie in der Meteorologie ueblich."""
    if len(sortiert) == 1:
        return sortiert[0]
    pos = q * (len(sortiert) - 1)
    unten = int(pos)
    rest = pos - unten
    if unten + 1 >= len(sortiert):
        return sortiert[-1]
    return sortiert[unten] + rest * (sortiert[unten + 1] - sortiert[unten])


# ---------------------------------------------------------------- Messwerte
def stationswerte():
    """Stuendliche DWD-Werte (UTC) zu Tagessummen in Ortszeit verdichten."""
    basis = ("https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
             "climate/hourly/precipitation/recent/")
    roh = hole(f"{basis}stundenwerte_RR_{STATION}_akt.zip", roh=True)
    if not roh:
        return {}, None
    tage, stunden = {}, {}
    with zipfile.ZipFile(io.BytesIO(roh)) as z:
        name = next(n for n in z.namelist() if n.startswith("produkt_rr_stunde"))
        text = z.read(name).decode("latin-1")
    for zeile in csv.reader(io.StringIO(text), delimiter=";"):
        if not zeile or zeile[0].strip() == "STATIONS_ID":
            continue
        ts = dt.datetime.strptime(zeile[1].strip(), "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
        wert = float(zeile[3])
        if wert < -900:          # -999 = Fehlwert
            continue
        tag = ts.astimezone(TZ).date().isoformat()
        tage[tag] = round(tage.get(tag, 0.0) + wert, 1)
        stunden[tag] = stunden.get(tag, 0) + 1
    # Nur vollstaendige Tage (24 Stundenwerte) gelten als belastbar
    vollstaendig = {t: v for t, v in tage.items() if stunden[t] >= 24}
    return vollstaendig, max(vollstaendig) if vollstaendig else None


# ---------------------------------------------------------------- Ausgabe
def main():
    ap = argparse.ArgumentParser(description="Datensammler Niederschlags-Modellvergleich Muehldorf")
    ap.add_argument("--modell", choices=["gfs", "ecmwf", "beide"], default="beide",
                    help="nur dieses Modell abrufen (getrennte Laeufe je Zeitfenster)")
    ap.add_argument("--messwerte", action="store_true", help="auch die Stationswerte holen")
    ap.add_argument("--alles", action="store_true", help="beide Modelle und Messwerte")
    args = ap.parse_args()
    modelle = ("gfs", "ecmwf") if args.modell == "beide" or args.alles else (args.modell,)
    messwerte_holen = args.messwerte or args.alles or args.modell == "beide"

    heute = dt.date.today()
    OUT.mkdir(parents=True, exist_ok=True)
    zieldatei = OUT / f"forecasts_{heute.isoformat()}.json"

    # Bereits vorhandenen Tageseintrag weiterfuehren, statt ihn zu ueberschreiben.
    # So ergaenzt der spaetere ECMWF-Lauf den frueheren GFS-Lauf desselben Tages.
    vorhanden = {}
    if zieldatei.exists():
        try:
            vorhanden = json.loads(zieldatei.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            fehler.append(f"vorhandene Datei {zieldatei.name} nicht lesbar: {e}")

    # --- Bereits erledigt? Bevor irgendetwas abgerufen wird: Modelle, fuer die
    # der heutige 00Z-Lauf (Hauptlauf UND Ensemble) schon eingetragen ist,
    # muessen bei einem stuendlichen Aufruf nicht elf weitere Male am Tag neu
    # abgerufen werden. --messwerte/--alles holt die Stationswerte trotzdem
    # weiter (guenstig, und DWD aktualisiert im Laufe des Tages).
    bereits_00z = dict(vorhanden.get("modelllaeufe", {}))
    def modell_bereits_fertig(m):
        for teil in ("hl", "ens"):
            info = bereits_00z.get(f"{m}/{teil}")
            if not info or not info["lauf"].startswith(f"{heute.isoformat()}T00:00"):
                return False
        return True
    modelle = tuple(m for m in modelle if not modell_bereits_fertig(m))
    if not modelle and not messwerte_holen:
        print(f"Lauf {heute}: alle angefragten Modelle bereits mit dem 00Z-Lauf erfasst — nichts zu tun.")
        return

    # --- Welcher Lauf steckt drin? Vor dem Abruf pruefen. ---
    laeufe_meta = dict(vorhanden.get("modelllaeufe", {}))
    laufwarnung = [w for w in vorhanden.get("laufhinweise", [])
                   if not any(w.startswith(m) for m in modelle)]
    for schluessel, datensatz in META.items():
        if schluessel[0] not in modelle:
            continue
        info = laufinfo(datensatz)
        if not info:
            laufwarnung.append(f"{schluessel[0]}/{schluessel[1]}: Laufzeit nicht abrufbar")
            continue
        laeufe_meta["/".join(schluessel)] = {
            "lauf": info["lauf"].strftime("%Y-%m-%dT%H:%MZ"),
            "verfuegbar_seit": info["verfuegbar"].strftime("%Y-%m-%dT%H:%MZ"),
        }
        passt = info["lauf"].hour == ERWARTETE_LAUFSTUNDE and info["lauf"].date() == heute
        if not passt:
            laufwarnung.append(
                f"{schluessel[0]} {schluessel[1]}: {info['lauf'].strftime('%d.%m. %HZ')} "
                f"statt {heute.strftime('%d.%m.')} {ERWARTETE_LAUFSTUNDE:02d}Z")

    werte, ens_n = {}, dict(vorhanden.get("ensemble_n", {}))
    erfolg = {}  # (modell, "hl"|"ens") -> bool; False = endgueltig fehlgeschlagen, NICHT ueberschreiben
    for modell in modelle:
        werte[(modell, "hl")], erfolg[(modell, "hl")] = hauptlauf(HAUPT[modell])
        ens_werte, n, ok = ensemble(ENSEMBLE[modell])
        werte[(modell, "ens")] = ens_werte
        erfolg[(modell, "ens")] = ok
        if ok:
            ens_n[modell] = n
        # bei ok=False bleibt ens_n[modell] auf dem alten Wert aus 'vorhanden' stehen

    LEER_MODELL = {"hl": None, "ens": None, "p10": None, "p90": None, "min": None, "max": None, "p_ueber5": None}
    alte_leads = {e["lead"]: e for e in vorhanden.get("leads", [])}
    leads = []
    for lead in range(1, MAX_LEAD + 1):
        ziel = (heute + dt.timedelta(days=lead)).isoformat()
        eintrag = dict(alte_leads.get(lead, {}))
        eintrag.update({"lead": lead, "ziel": ziel})
        for modell in modelle:
            # Ausgangspunkt: was vorher schon fuer dieses Modell an diesem Lead
            # stand (aus alte_leads). Nur bei erfolgreichem Abruf werden die
            # betroffenen Felder ueberschrieben -- ein endgueltig gescheiterter
            # Abruf (erfolg=False) laesst bestehende gueltige Werte unangetastet,
            # statt sie durch None zu ersetzen.
            neu = {**LEER_MODELL, **eintrag.get(modell, {})}
            if erfolg.get((modell, "hl")):
                neu["hl"] = werte[(modell, "hl")].get(ziel)
            if erfolg.get((modell, "ens")):
                ens = werte[(modell, "ens")].get(ziel)
                neu["ens"] = ens["mittel"] if ens else None
                neu["p10"] = ens["p10"] if ens else None
                neu["p90"] = ens["p90"] if ens else None
                neu["min"] = ens["min"] if ens else None
                neu["max"] = ens["max"] if ens else None
                neu["p_ueber5"] = ens["p_ueber5"] if ens else None
            eintrag[modell] = neu
        leads.append(eintrag)

    # Ein Modell gilt fuer diesen Lauf nur dann als "erfasst", wenn tatsaechlich
    # mindestens ein Abruf (Hauptlauf ODER Ensemble) erfolgreich war -- nicht
    # schon deshalb, weil es unter --modell/--alles angefragt wurde. Bereits
    # frueher am selben Tag erfolgreich erfasste Modelle bleiben ueber die
    # Vereinigung mit 'vorhanden' erhalten.
    neu_erfasst = {m for m in modelle if erfolg.get((m, "hl")) or erfolg.get((m, "ens"))}

    lauf = {
        "lauf": heute.isoformat(),
        "abgerufen": dt.datetime.now(TZ).isoformat(timespec="minutes"),
        "erfasste_modelle": sorted(set(vorhanden.get("erfasste_modelle", [])) | neu_erfasst),
        "ensemble_n": ens_n,
        "modelllaeufe": laeufe_meta,
        "lauf_wie_erwartet": not laufwarnung,
        "laufhinweise": laufwarnung,
        "leads": leads,
    }
    atomar_schreiben_json(zieldatei, lauf)

    # --- Messwerte, nach Monat gebuendelt ---
    # Wichtig: DWD liefert im "akt"-Archiv nur ein rollierendes Zeitfenster von
    # rund 500 Tagen. Aeltere Monatsdateien liegen daher oft schon AUSSERHALB
    # dieses Fensters -- ein Ueberschreiben nur mit dem, was der aktuelle Abruf
    # zurueckgibt, wuerde diese aelteren Tage stillschweigend loeschen. Deshalb
    # wird hier mit der vorhandenen Datei zusammengefuehrt: neue oder korrigierte
    # Tage (aus dem aktuellen Abruf) ueberschreiben die alten Werte fuer densel-
    # ben Tag, alle anderen vorhandenen Tage bleiben unangetastet erhalten.
    messungen, letzter = stationswerte() if messwerte_holen else ({}, None)
    monate = {}
    for tag, v in messungen.items():
        monate.setdefault(tag[:7], {})[tag] = v
    aktualisierte_monate = 0
    for monat, neue_tage in monate.items():
        pfad = OUT / f"messungen_{monat}.json"
        vorhandene_tage = {}
        if pfad.exists():
            try:
                vorhandene_tage = json.loads(pfad.read_text(encoding="utf-8")).get("tage", {})
            except Exception as e:  # noqa: BLE001
                fehler.append(f"vorhandene Messdatei {pfad.name} nicht lesbar, wird NICHT ueberschrieben: {e}")
                continue
        zusammengefuehrt = dict(vorhandene_tage)
        zusammengefuehrt.update(neue_tage)  # neuere/korrigierte Werte gewinnen, nichts geht verloren
        if zusammengefuehrt != vorhandene_tage:
            atomar_schreiben_json(pfad, {
                "monat": monat, "station": STATION,
                "quelle": "DWD CDC, Stundenwerte RR, Tagessumme 00-24 Uhr Ortszeit",
                "tage": dict(sorted(zusammengefuehrt.items())),
            })
            aktualisierte_monate += 1

    print(f"Lauf {heute}: {len(leads)} Leads · erfasst: {', '.join(lauf['erfasste_modelle'])}"
          f" · Ensemble-Läufe " + " ".join(f"{m.upper()}={ens_n.get(m, '–')}" for m in ("gfs", "ecmwf")))
    for name, info in laeufe_meta.items():
        print(f"  Modelllauf {name:12s} {info['lauf']}  (verfügbar seit {info['verfuegbar_seit']})")
    if laufwarnung:
        print("  ACHTUNG – nicht der erwartete 00Z-Lauf:", *laufwarnung, sep="\n    ")
    if messwerte_holen:
        print(f"Messwerte: {len(messungen)} vollständige Tage, letzter {letzter}, {len(monate)} Monatsdateien")
    else:
        print("Messwerte: übersprungen (--messwerte nicht gesetzt)")
    leer = {"hl": None, "ens": None, "p10": None, "p90": None}
    for e in leads:
        g, c = e.get("gfs", leer), e.get("ecmwf", leer)
        print(f"  L{e['lead']:2d} {e['ziel']}  GFS {fmt(g['hl'])}/{fmt(g['ens'])} [{fmt(g['p10'])}–{fmt(g['p90'])}]"
              f"   ECMWF {fmt(c['hl'])}/{fmt(c['ens'])} [{fmt(c['p10'])}–{fmt(c['p90'])}]")
    if fehler:
        print("FEHLER:", *fehler, sep="\n  ")
        # Mindestens ein notwendiger Abruf ist nach allen Wiederholungen
        # endgueltig gescheitert. Bereits geschriebene Dateien enthalten dank
        # der Merge-Logik oben weiterhin nur gueltige Werte -- aber der Lauf
        # selbst war nicht vollstaendig erfolgreich, und das muss sich im
        # Exit-Code zeigen. Sonst haelt z.B. GitHub Actions einen Totalausfall
        # faelschlich fuer einen erfolgreichen Durchlauf.
        sys.exit(1)


def fmt(v):
    return "  –" if v is None else f"{v:4.1f}"


if __name__ == "__main__":
    main()
