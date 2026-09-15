#!/usr/bin/env python3
"""
Einmaliger Import historischer Vorhersagen ueber die Previous-Runs-API von open-meteo.

Liefert fuer die letzten ~90 Tage, was GFS bzw. ECMWF mit 1 bis 7 Tagen Vorlauf
fuer jeden Tag vorhergesagt hatten. Damit ist die Guete der HAUPTLAEUFE sofort
auswertbar, statt erst ueber Monate zu wachsen.

Wichtige Grenze: Die Previous-Runs-API kennt keine Ensembles. Die Ensemble-Mittel
haben diese Historie also NICHT -- ihre Statistik beginnt mit dem ersten taeglichen
Lauf. Ein Vergleich Hauptlauf gegen Ensemble ueber unterschiedlich lange Zeitraeume
waere irrefuehrend; das Dashboard muss die Fallzahlen getrennt ausweisen.

Ausgabe: out/history_<modell>.json
"""

import datetime as dt
import json
import time
import zoneinfo
from pathlib import Path

import requests

LAT, LON = 48.2456, 12.5228
TZ_NAME = "Europe/Berlin"
TZ = zoneinfo.ZoneInfo(TZ_NAME)
MODELLE = {"gfs": "gfs_seamless", "ecmwf": "ecmwf_ifs025"}
LEADS = range(1, 8)
PAST_DAYS = 92
OUT = Path(__file__).resolve().parent.parent / "daten"


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
    # nur vollstaendige Tage; angebrochene Tage am Rand wuerden zu niedrig ausfallen
    return {t: round(s, 1) for t, s in summe.items() if zaehler[t] >= 24}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    heute = dt.date.today()
    for kurz, modell_id in MODELLE.items():
        spalten = [f"precipitation_previous_day{i}" for i in LEADS]
        d = hole({"latitude": LAT, "longitude": LON, "timezone": TZ_NAME, "models": modell_id,
                  "past_days": PAST_DAYS, "forecast_days": 1, "hourly": ",".join(spalten)})
        h = d["hourly"]
        je_lead = {lead: tagessummen(h["time"], h[f"precipitation_previous_day{lead}"]) for lead in LEADS}

        tage = {}
        for lead, werte in je_lead.items():
            for tag, v in werte.items():
                # nur abgeschlossene Tage: heute laeuft noch
                if dt.date.fromisoformat(tag) >= heute:
                    continue
                tage.setdefault(tag, {})[str(lead)] = v

        pfad = OUT / f"history_{kurz}.json"
        pfad.write_text(json.dumps({
            "modell": kurz,
            "quelle": "open-meteo Previous-Runs-API, Hauptlauf, stündliche Werte zu Tagessummen 00–24 Uhr Ortszeit",
            "leads": list(LEADS),
            "stand": heute.isoformat(),
            "tage": dict(sorted(tage.items())),
        }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{kurz}: {len(tage)} Tage ({min(tage)} bis {max(tage)}), {pfad.stat().st_size} Bytes")


if __name__ == "__main__":
    main()
