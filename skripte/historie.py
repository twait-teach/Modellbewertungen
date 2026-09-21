#!/usr/bin/env python3
"""
Einmaliger Import historischer Vorhersagen ueber die Previous-Runs-API von open-meteo.

Liefert fuer die letzten ~90 Tage, was GFS bzw. ECMWF mit 1 bis 7 Tagen Vorlauf
fuer jeden Tag vorhergesagt hatten. Damit ist die Guete der HAUPTLAEUFE sofort
auswertbar, statt erst ueber Monate zu wachsen.

Dauerhafte Zeitreihe: Jeder Abruf wird mit dem bisherigen Bestand ZUSAMMENGEFUEHRT,
nicht ueberschrieben. Tage, die aus dem 92-Tage-Fenster der API herausfallen, bleiben
dadurch erhalten; nur Tage, die der aktuelle Abruf liefert, werden (identisch)
erneuert. Eine optionale Datei history_<modell>_nachtrag.json wird ebenfalls
uebernommen (einmaliger Nachtrag frueher verlorener Tage).

Wichtige Grenze: Die Previous-Runs-API kennt keine Ensembles. Die Ensemble-Mittel
haben diese Historie also NICHT -- ihre Statistik beginnt mit dem ersten taeglichen
Lauf. Ein Vergleich Hauptlauf gegen Ensemble ueber unterschiedlich lange Zeitraeume
waere irrefuehrend; das Dashboard muss die Fallzahlen getrennt ausweisen.

Ausgabe: daten/history_<modell>.json

Idempotenz: Das Skript wird bei jedem halbstuendlichen Workflowdurchlauf (und bei
manuellem Start) aufgerufen, ruft die Previous-Runs-API aber nur ab, wenn es noetig
ist:
  * vor 12:00 UTC gibt es keine automatische Aktualisierung,
  * ab 12:00 UTC wird nur aktualisiert, wenn das Feld ``stand`` der jeweiligen
    Datei aelter als der heutige UTC-Tag ist (oder die Datei fehlt/unlesbar ist),
  * nur die veralteten Modelle werden neu abgerufen.
``--erzwingen`` hebt beides bewusst auf (Handbetrieb, z.B. nach einem Ausfall).
"""

import argparse
import datetime as dt
import json
import sys
import time
import zoneinfo
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemeinsam import atomar_schreiben, stunden_im_ortstag  # noqa: E402

LAT, LON = 48.2456, 12.5228
TZ_NAME = "Europe/Berlin"
TZ = zoneinfo.ZoneInfo(TZ_NAME)
MODELLE = {"gfs": "gfs_seamless", "ecmwf": "ecmwf_ifs025"}
LEADS = range(1, 8)
PAST_DAYS = 92
OUT = Path(__file__).resolve().parent.parent / "daten"
AB_STUNDE_UTC = 12   # fruehestens ab dieser UTC-Stunde wird automatisch aktualisiert


def hole(params, versuche=5):
    letzter = None
    for i in range(versuche):
        try:
            r = requests.get("https://previous-runs-api.open-meteo.com/v1/forecast",
                             params=params, timeout=120)
            r.raise_for_status()
            d = r.json()
            if d.get("error"):
                raise RuntimeError(d.get("reason", "API-Fehler"))
            return d
        except Exception as e:  # noqa: BLE001
            letzter = e
            if i < versuche - 1:
                time.sleep(2 ** i)
    raise RuntimeError(f"Abruf endgültig fehlgeschlagen: {letzter}")


def tagessummen(zeiten, werte):
    """Stuendliche Werte (Ortszeit) zu Kalendertagssummen verdichten."""
    summe, zaehler = {}, {}
    for t, v in zip(zeiten, werte):
        if v is None:
            continue
        tag = t[:10]
        summe[tag] = summe.get(tag, 0.0) + v
        zaehler[tag] = zaehler.get(tag, 0) + 1
    # nur vollstaendige Tage; angebrochene Tage am Rand wuerden zu niedrig ausfallen.
    # Vollstaendig heisst: alle Stunden des Ortstages (23, 24 oder 25 -- Zeitumstellung).
    return {t: round(s, 1) for t, s in summe.items() if zaehler[t] >= stunden_im_ortstag(t)}


def stand_der_datei(kurz):
    """``stand`` (JJJJ-MM-TT) der Historiendatei oder None, wenn fehlt/unlesbar."""
    pfad = OUT / f"history_{kurz}.json"
    try:
        stand = json.loads(pfad.read_text(encoding="utf-8")).get("stand")
    except (OSError, ValueError, AttributeError):
        return None
    return stand if isinstance(stand, str) else None


def veraltete_modelle(jetzt, erzwingen=False):
    """Modelle, deren Historie jetzt aktualisiert werden soll.

    ``jetzt`` ist ein Zeitpunkt mit UTC-Zeitzone. Rueckgabe: Liste der
    Modellkennungen in der Reihenfolge von MODELLE (leer = nichts zu tun).
    """
    if erzwingen:
        return list(MODELLE)
    if jetzt.hour < AB_STUNDE_UTC:
        return []
    heute = jetzt.date().isoformat()
    return [kurz for kurz in MODELLE if (stand_der_datei(kurz) or "") < heute]


def vorhandene_tage(kurz):
    """Bisheriger Bestand: Tage aus history_<kurz>.json und (falls vorhanden)
    history_<kurz>_nachtrag.json. Fehlende oder unlesbare Dateien zaehlen als leer."""
    tage = {}
    for name in (f"history_{kurz}_nachtrag.json", f"history_{kurz}.json"):
        try:
            d = json.loads((OUT / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        alt = d.get("tage") if isinstance(d, dict) else None
        if not isinstance(alt, dict):
            continue
        for tag, werte in alt.items():
            if isinstance(werte, dict):
                tage.setdefault(tag, {}).update(werte)
    return tage


def aktualisiere(kurz, heute):
    modell_id = MODELLE[kurz]
    spalten = [f"precipitation_previous_day{i}" for i in LEADS]
    d = hole({"latitude": LAT, "longitude": LON, "timezone": TZ_NAME, "models": modell_id,
              "past_days": PAST_DAYS, "forecast_days": 1, "hourly": ",".join(spalten)})
    h = d["hourly"]
    je_lead = {lead: tagessummen(h["time"], h[f"precipitation_previous_day{lead}"]) for lead in LEADS}

    # Mit dem Bestand zusammenfuehren: aeltere Tage bleiben, neu gelieferte ersetzen.
    tage = vorhandene_tage(kurz)
    vorher = len(tage)
    for lead, werte in je_lead.items():
        for tag, v in werte.items():
            # nur abgeschlossene Tage: heute laeuft noch
            if dt.date.fromisoformat(tag) >= heute:
                continue
            tage.setdefault(tag, {})[str(lead)] = v

    if not tage:
        print(f"{kurz}: keine Tage erhalten — Datei bleibt unverändert")
        return
    pfad = OUT / f"history_{kurz}.json"
    atomar_schreiben(pfad, json.dumps({
        "modell": kurz,
        "quelle": "open-meteo Previous-Runs-API, Hauptlauf, stündliche Werte zu Tagessummen 00–24 Uhr Ortszeit",
        "leads": list(LEADS),
        "stand": heute.isoformat(),
        "tage": dict(sorted(tage.items())),
    }, ensure_ascii=False, separators=(",", ":")))
    print(f"{kurz}: {len(tage)} Tage ({min(tage)} bis {max(tage)}), davon {len(tage) - vorher} neu, "
          f"{pfad.stat().st_size} Bytes")


def main(argv=None, jetzt=None):
    ap = argparse.ArgumentParser(description="Historie der Hauptlaeufe (Previous-Runs-API) auffrischen")
    ap.add_argument("--erzwingen", action="store_true",
                    help="Uhrzeit- und Stand-Pruefung ueberspringen und beide Historien neu laden")
    args = ap.parse_args(argv)
    jetzt = jetzt or dt.datetime.now(dt.timezone.utc)

    faellig = veraltete_modelle(jetzt, erzwingen=args.erzwingen)
    if not faellig:
        grund = (f"vor {AB_STUNDE_UTC}:00 UTC" if jetzt.hour < AB_STUNDE_UTC
                 else f"Stand bereits {jetzt.date().isoformat()}")
        print(f"Historie: nichts zu tun ({grund}).")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for kurz in faellig:
        aktualisiere(kurz, jetzt.date())


if __name__ == "__main__":
    main()
