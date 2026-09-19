#!/usr/bin/env python3
"""
Sammelt vollstaendige Ensemble-Mitgliederdaten fuer die drei Diagrammbereiche
der Seite "Vorhersage": 2-m-Temperatur, 850-hPa-Temperatur und
aufsummierter Niederschlag. Anders als sammeln.py (das pro Kalendertag ein Dokument
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

Open-Meteo interpoliert Ensemblewerte auf ein Stundenraster. Fuer die Anzeige
werden daraus wieder die modellnahen Stuetzstellen gewonnen: GFS dreistuendlich
bis +240 h und danach sechsstuendlich, ECMWF durchgehend dreistuendlich.
Niederschlag wird aus den stuendlichen Mengen je Modellintervall gebildet,
ZUERST JE MITGLIED AKKUMULIERT und erst danach werden Mittel/Perzentile aus
den akkumulierten Kurven gebildet. Temperatur (2 m und 850 hPa) wird NICHT
akkumuliert. Mittel und Perzentile werden je Modellstuetzstelle
direkt aus den zu diesem Zeitpunkt vorhandenen Mitgliedswerten gebildet;
fehlt ein Mitgliedswert zu einem Zeitpunkt, wird NUR dieser Zeitpunkt fuer
dieses Mitglied ausgeschlossen (anders als beim Niederschlag bricht das nicht
die Kette fuer die folgenden Zeitpunkte, da Temperatur nicht kumuliert wird).
So entsteht ein echtes Ensemble-Meteogramm mit Tagesgang bei 2 m und zeitlich
hoch aufgeloesten Luftmassenwechseln bei 850 hPa.

Pro erkanntem Lauf wird eine Datei daten/vorhersage/<modell>_<initISO>.json
als fester Slot angelegt, sobald Laufweite und Mitgliederzahl des Ensembles
vollstaendig vorliegen. Der deterministische Hauptlauf wird ueber seine exakte
Initialisierungszeit aus der Single-Runs-Schnittstelle nachgetragen, sobald er
verfuegbar ist. So wird das Ensemble ohne Wartezeit gezeigt, ohne spaeter einen
unpassenden neueren Hauptlauf einzubetten. Aeltere Laeufe werden nach dem
Schreiben ueber AUFBEWAHREN hinaus geloescht.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

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


def modell_zeitfenster(verfuegbare_zeiten, init, horizont, modell):
    """Modellnahe Zeitpunkte vom Modellstart bis zum exakten Horizont.

    Open-Meteo liefert bei ``timezone=Europe/Berlin`` lokale ISO-Zeiten ohne
    Offset. Fuer Anzeige und Tabellen bleiben diese lesbaren Werte erhalten;
    zusaetzlich speichern wir Unix-Zeitpunkte. Open-Meteo interpoliert die
    Ensemble-Ausgabe auf Stundenwerte; angezeigt werden aber nur die
    modellnahen Stuetzstellen: GFS 3-stuendlich bis einschliesslich +240 h,
    danach 6-stuendlich; ECMWF durchgehend 3-stuendlich.
    """
    zone = ZoneInfo(TZ_NAME)
    start = init.astimezone(zone)
    ende = (init + dt.timedelta(days=horizont)).astimezone(zone)
    auswahl = []
    for text in sorted(verfuegbare_zeiten):
        try:
            lokal = dt.datetime.fromisoformat(text).replace(tzinfo=zone)
        except (TypeError, ValueError):
            continue
        if start <= lokal <= ende:
            lead_stunden = round((lokal.timestamp() - init.timestamp()) / 3600)
            schritt = 6 if modell == "gfs" and lead_stunden > 240 else 3
            if lead_stunden % schritt:
                continue
            auswahl.append((text, int(lokal.timestamp())))
    return [x[0] for x in auswahl], [x[1] for x in auswahl]


def niederschlag_kumulieren(stundenserie, alle_zeiten, ausgabe_zeiten, init):
    """Stuendliche Niederschlagsmengen zu Modellintervallen zusammenfassen.

    Der Wert am Modellstart ist 0 mm. Fuer jeden folgenden modellnahen
    Zeitpunkt werden alle Stundenmengen seit der vorherigen Stuetzstelle
    addiert (GFS also 3 h, ab +240 h 6 h) und anschliessend fortlaufend
    kumuliert. Fehlt ein Stundenwert, ist die Summenkette ab dort ``None``;
    eine Datenluecke wird niemals als 0 mm interpretiert.
    """
    zone = ZoneInfo(TZ_NAME)
    start_unix = int(init.timestamp())
    ziel_unix = {
        int(dt.datetime.fromisoformat(text).replace(tzinfo=zone).timestamp()): text
        for text in ausgabe_zeiten
    }
    if not ziel_unix:
        return []
    ende_unix = max(ziel_unix)
    stunden = []
    for text in alle_zeiten:
        try:
            unix = int(dt.datetime.fromisoformat(text).replace(tzinfo=zone).timestamp())
        except (TypeError, ValueError):
            continue
        if start_unix < unix <= ende_unix:
            stunden.append((unix, text))
    stunden.sort()

    out = []
    summe = 0.0
    abgebrochen = False
    index = 0
    for unix in sorted(ziel_unix):
        if unix == start_unix:
            out.append(0.0)
            continue
        while index < len(stunden) and stunden[index][0] <= unix:
            wert = stundenserie.get(stunden[index][1])
            if wert is None:
                abgebrochen = True
            elif not abgebrochen:
                summe += wert
            index += 1
        out.append(None if abgebrochen else round(summe, 2))
    return out


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

    # EIN Abruf liefert alle drei Groessen im Stundenraster. Daraus werden
    # unten die modellnahen 3-/6-Stunden-Stuetzstellen rekonstruiert.
    ens = hole("https://ensemble-api.open-meteo.com/v1/ensemble",
               {"latitude": LAT, "longitude": LON,
                "hourly": "temperature_2m,temperature_850hPa,precipitation",
                # Ein 18Z-Lauf wird oft erst nach Mitternacht vollstaendig.
                # Ohne den Vortag fehlen dann seine ersten Modellstunden.
                "past_days": 1, "forecast_days": horizont + 1,
                "timezone": TZ_NAME, "models": cfg["ensemble_datensatz"]},
               fehlerliste=fehler)
    if not ens:
        return None, [f"{kurz}: Ensemble-Daten nicht abrufbar"]

    hourly_zeiten = (ens.get("hourly") or {}).get("time", [])
    zeiten, zeitpunkte_unix = modell_zeitfenster(hourly_zeiten, init, horizont, kurz)
    if not zeiten:
        return None, [f"{kurz}: keine modellnahen Zeitpunkte in der Antwort"]

    # --- Niederschlag: Stundenmengen erst zu 3-/6-h-Intervallen gruppieren,
    # dann je Mitglied akkumulieren, erst danach Ensemble-Kennzahlen bilden. ---
    serien_regen = stundenwerte_je_serie(ens, "precipitation")
    if "precipitation" not in serien_regen:
        return None, [f"{kurz}: Ensemble-Basisserie (Niederschlag) fehlt in der Antwort"]
    basis_regen = niederschlag_kumulieren(
        serien_regen["precipitation"], hourly_zeiten, zeiten, init)
    mitglieder_keys = sorted(k for k in serien_regen if k != "precipitation")
    mitglieder_regen = [
        niederschlag_kumulieren(serien_regen[k], hourly_zeiten, zeiten, init)
        for k in mitglieder_keys
    ]
    kennzahlen_regen = aggregiere_alle_leads(mitglieder_regen, len(zeiten))
    niederschlag = {
        "zeiten": zeiten,
        "zeitpunkte_unix": zeitpunkte_unix,
        "zeitzone": TZ_NAME,
        # GFS veroeffentlicht neben dem deterministischen Hauptlauf einen
        # eigenen Kontrolllauf. Beim ECMWF wird nur der operationelle Lauf
        # gezeigt; die unsuffigierte Ensemble-Basisserie wird dort bewusst
        # nicht als zweiter, vermeintlicher Kontrolllauf ausgegeben.
        "kontrolllauf": basis_regen if kurz == "gfs" else None,
        "mitglieder": mitglieder_regen,
        "hauptlauf": None,
        **kennzahlen_regen,
    }

    # --- Temperatur: NICHT akkumuliert, nur modellnahe Stuetzstellen ---
    temperaturen = {}
    for feld, praefix in (("temperatur_2m", "temperature_2m"), ("temperatur_850hpa", "temperature_850hPa")):
        serien_temp = stundenwerte_je_serie(ens, praefix)
        if praefix not in serien_temp:
            temperaturen[feld] = None
            hinweise.append(f"{feld}: Spalte fehlt in der Antwort -- fuer diesen Lauf nicht gespeichert")
            continue
        temp_keys = sorted(k for k in serien_temp if k != praefix)
        basis_t = stundenreihe(serien_temp[praefix], zeiten)
        mitglieder_t = [stundenreihe(serien_temp[k], zeiten) for k in temp_keys]
        kennzahlen_t = aggregiere_alle_leads(mitglieder_t, len(zeiten))
        temperaturen[feld] = {
            "zeiten": zeiten,
            "zeitpunkte_unix": zeitpunkte_unix,
            "zeitzone": TZ_NAME,
            "kontrolllauf": basis_t if kurz == "gfs" else None,
            "mitglieder": mitglieder_t,
            "hauptlauf": None,  # wird unten befuellt, falls Hauptlauf passt
            **kennzahlen_t,
        }

    # --- Pruefungen vor dem Speichern (gilt fuer den GESAMTEN Lauf: erst
    # speichern, wenn Laufweite UND Mitgliederzahl vollstaendig vorliegen) ---
    erwartete_mitglieder = {"gfs": 30, "ecmwf": 50}[kurz]
    if len(mitglieder_keys) < erwartete_mitglieder - 2:  # etwas Toleranz, Modelle aendern Mitgliederzahl gelegentlich
        hinweise.append(f"nur {len(mitglieder_keys)} statt erwarteter {erwartete_mitglieder} Mitglieder")
    letzter_lead_leer = sum(1 for s in mitglieder_regen if not s or s[-1] is None)
    if letzter_lead_leer > len(mitglieder_regen) * 0.5:
        hinweise.append(f"Horizont unvollstaendig: bei {letzter_lead_leer}/{len(mitglieder_regen)} "
                         f"Mitgliedern bricht die Niederschlagsreihe vor dem Horizont ab")
    vollstaendig = letzter_lead_leer == 0 and len(mitglieder_keys) >= erwartete_mitglieder - 2

    # Auch die Temperaturreihen muessen den vorgesehenen Horizont
    # abdecken, sonst gilt der Lauf als noch nicht vollstaendig (und wird von
    # main() noch nicht gespeichert, sondern beim naechsten Durchlauf erneut
    # versucht). Geprueft wird: die Reihe existiert, sie reicht bis zum letzten
    # Vorhersagezeitpunkt (mit hoechstens sechs Stunden Toleranz wegen der
    # groberen Originalaufloesung in der GFS-Langfrist), und am letzten
    # Zeitpunkt liegen ueberhaupt Mitgliedswerte vor.
    erwartetes_ende = int((init + dt.timedelta(days=horizont)).timestamp())
    toleranz_sekunden = 6 * 3600
    for feld in ("temperatur_2m", "temperatur_850hpa"):
        t = temperaturen.get(feld)
        if not t:
            vollstaendig = False
            continue
        if (not t["zeiten"] or not t["zeitpunkte_unix"]
                or t["zeitpunkte_unix"][-1] < erwartetes_ende - toleranz_sekunden):
            hinweise.append(f"{feld}: Temperaturreihe reicht nicht bis zum vorgesehenen Horizont")
            vollstaendig = False
        elif not t["n"] or t["n"][-1] == 0:
            hinweise.append(f"{feld}: zum letzten Zeitpunkt liegen keine Mitgliedswerte vor")
            vollstaendig = False

    lauf = {
        "modell": kurz,
        "modellname": cfg["name"],
        "ensemble_datensatz": cfg["ensemble_datensatz"],
        "init": init.strftime("%Y-%m-%dT%H:%MZ"),
        "verfuegbar_seit": ens_info["verfuegbar"].strftime("%Y-%m-%dT%H:%MZ"),
        "abgerufen": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "horizont_tage": horizont,
        "zeitauflosung": "modellnativ-v1",
        "mitglieder_n": len(mitglieder_keys),
        "leads": list(range(1, horizont + 1)),
        "ziele": ziele,
        "niederschlag": niederschlag,
        "temperatur_2m": temperaturen.get("temperatur_2m"),
        "temperatur_850hpa": temperaturen.get("temperatur_850hpa"),
        # Zwei getrennte Zustaende: Das Ensemble wird sofort als eigener Slot
        # gespeichert. Der exakt gleiche Hauptlauf wird spaeter ergaenzt.
        "ensemble_vollstaendig": vollstaendig,
        "hauptlauf_vollstaendig": False,
        "vollstaendig": False,
        "hinweise": hinweise,
    }
    return lauf, hinweise


def dateiname(kurz, init: dt.datetime) -> str:
    return f"{kurz}_{init.strftime('%Y-%m-%dT%H')}.json"


def hat_modellnative_meteogrammdaten(lauf):
    """True, wenn der Ensembleteil aller drei Diagramme darstellbar ist.

    Aeltere Dateien koennen bereits ``vollstaendig: true`` tragen und sogar
    stuendliche Temperaturen enthalten. Ohne Formatmarker koennten darin aber
    noch die kuenstlichen Interpolationszacken stecken.
    """
    if lauf.get("zeitauflosung") != "modellnativ-v1":
        return False
    for feld in ("temperatur_2m", "temperatur_850hpa", "niederschlag"):
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


def hat_hauptlaufdaten(lauf):
    """True, wenn alle drei Hauptlaufreihen bereits im Slot liegen."""
    return all(
        isinstance((lauf.get(feld) or {}).get("hauptlauf"), list)
        and any(v is not None for v in lauf[feld]["hauptlauf"])
        for feld in ("temperatur_2m", "temperatur_850hpa", "niederschlag")
    )


def normalisiere_slot(lauf):
    """Alte Laufdateien auf den zweistufigen Slotstatus heben.

    Fruehere Hinweise auf abweichende *aktuelle* Hauptlaeufe sind bei der
    gezielten Single-Run-Nachlieferung nicht mehr relevant und wuerden nur das
    Layout verschieben.
    """
    vorher = json.dumps(lauf, sort_keys=True)
    alte_hinweise = lauf.get("hinweise") or []
    hatte_falschen_hauptlauf = any(
        "passt nicht zum Ensemble-Lauf" in h or "deterministischer Lauf ist" in h
        for h in alte_hinweise
    )
    # Ein Alt-Slot mit explizitem Abweichungshinweis darf nie versehentlich
    # als vollstaendig gelten. Sein Hauptlauf wird verworfen und anschliessend
    # ueber ``run=<Slot-Initialisierung>`` korrekt neu befuellt.
    if hatte_falschen_hauptlauf:
        for feld in ("temperatur_2m", "temperatur_850hpa", "niederschlag"):
            if isinstance(lauf.get(feld), dict):
                lauf[feld]["hauptlauf"] = None
    lauf["ensemble_vollstaendig"] = hat_modellnative_meteogrammdaten(lauf)
    lauf["hauptlauf_vollstaendig"] = hat_hauptlaufdaten(lauf)
    lauf["vollstaendig"] = lauf["ensemble_vollstaendig"] and lauf["hauptlauf_vollstaendig"]
    lauf["hinweise"] = [
        h for h in alte_hinweise
        if "passt nicht zum Ensemble-Lauf" not in h and "deterministischer Lauf ist" not in h
    ]
    # ECMWF besitzt in unserer Darstellung keinen eigenen Kontrolllauf.
    if lauf.get("modell") == "ecmwf":
        for feld in ("temperatur_2m", "temperatur_850hpa", "niederschlag"):
            if isinstance(lauf.get(feld), dict):
                lauf[feld]["kontrolllauf"] = None
    return vorher != json.dumps(lauf, sort_keys=True)


def ergaenze_hauptlauf(lauf, cfg, fehler):
    """Ergaenzt EINEN bestehenden Ensemble-Slot um seinen exakten Hauptlauf.

    Eine winzige Single-Runs-Abfrage prueft zuerst die Verfuegbarkeit. Erst
    danach wird der volle Lauf geladen. ``run`` fixiert die Initialisierung;
    ein inzwischen neuerer Echtzeitlauf kann den offenen Slot nicht mehr
    verdraengen.
    """
    if hat_hauptlaufdaten(lauf):
        normalisiere_slot(lauf)
        return False, "Hauptlauf bereits vorhanden"

    init = dt.datetime.strptime(lauf["init"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
    run = init.strftime("%Y-%m-%dT%H:%M")
    basis = {
        "latitude": LAT, "longitude": LON,
        "models": cfg["hauptlauf_datensatz"], "run": run,
    }

    probe_fehler = []
    probe = hole(
        "https://single-runs-api.open-meteo.com/v1/forecast",
        {**basis, "hourly": "temperature_2m", "forecast_hours": 1, "timezone": "UTC"},
        versuche=1, timeout=30, fehlerliste=probe_fehler,
    )
    if not probe or not (probe.get("hourly") or {}).get("temperature_2m"):
        return False, f"Hauptlauf {init:%d.%m. %HZ} noch nicht in Single Runs verfuegbar"

    horizont = lauf["horizont_tage"]
    hl = hole(
        "https://single-runs-api.open-meteo.com/v1/forecast",
        {**basis,
         "hourly": "temperature_2m,temperature_850hPa,precipitation",
         # Einschliesslich Initialisierungszeit und Endpunkt bei +Horizont.
         "forecast_hours": horizont * 24 + 1, "timezone": TZ_NAME},
        fehlerliste=fehler,
    )
    if not hl:
        return False, f"Hauptlauf {init:%d.%m. %HZ} noch nicht vollstaendig abrufbar"

    hl_zeiten = (hl.get("hourly") or {}).get("time", [])
    hl_regen = stundenwerte_je_serie(hl, "precipitation")
    hl_t2 = stundenwerte_je_serie(hl, "temperature_2m")
    hl_t850 = stundenwerte_je_serie(hl, "temperature_850hPa")
    if not all(("precipitation" in hl_regen, "temperature_2m" in hl_t2, "temperature_850hPa" in hl_t850)):
        return False, f"Hauptlauf {init:%d.%m. %HZ} enthaelt noch nicht alle drei Variablen"

    regen = niederschlag_kumulieren(
        hl_regen["precipitation"], hl_zeiten, lauf["niederschlag"]["zeiten"], init)
    t2 = stundenreihe(hl_t2["temperature_2m"], lauf["temperatur_2m"]["zeiten"])
    t850 = stundenreihe(hl_t850["temperature_850hPa"], lauf["temperatur_850hpa"]["zeiten"])
    # Einzelne Langfrist-Endpunkte duerfen fehlen; eine fast leere oder am
    # Anfang fehlende Reihe gilt dagegen noch nicht als eingetroffen.
    reihen = (regen, t2, t850)
    if any(not r or r[0] is None or sum(v is not None for v in r) < len(r) * 0.9 for r in reihen):
        return False, f"Hauptlauf {init:%d.%m. %HZ} ist noch nicht ausreichend vollstaendig"

    lauf["niederschlag"]["hauptlauf"] = regen
    lauf["temperatur_2m"]["hauptlauf"] = t2
    lauf["temperatur_850hpa"]["hauptlauf"] = t850
    lauf["hauptlauf_abgerufen"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    normalisiere_slot(lauf)
    return True, f"Hauptlauf {init:%d.%m. %HZ} ergaenzt"


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
        vorab_info = laufinfo(cfg["meta_ensemble"], [])
        if not vorab_info or vorab_info["lauf"].hour not in cfg["erlaubte_stunden"]:
            print(f"{kurz}: kein erlaubter Ensemble-Lauf in den Metadaten")
        else:
            erwarteter_pfad = OUT / dateiname(kurz, vorab_info["lauf"])
            bereits = {}
            if erwarteter_pfad.exists():
                try:
                    bereits = json.loads(erwarteter_pfad.read_text(encoding="utf-8"))
                except Exception:
                    bereits = {}

            if not hat_modellnative_meteogrammdaten(bereits):
                lauf, hinweise = verarbeite_modell(kurz, cfg, fehler, heute)
                if not lauf:
                    print(f"{kurz}: Ensemble-Slot noch nicht abrufbar. " + "; ".join(hinweise))
                elif not lauf["ensemble_vollstaendig"]:
                    print(f"{kurz}: Ensemble {lauf['init']} noch nicht vollstaendig -- noch nicht gespeichert. "
                          + ("Hinweise: " + "; ".join(hinweise) if hinweise else ""))
                else:
                    atomar_schreiben_json(erwarteter_pfad, lauf, separators=(",", ":"))
                    print(f"{kurz}: Ensemble-Slot {lauf['init']} sofort gespeichert -- "
                          f"{lauf['mitglieder_n']} Mitglieder; Hauptlauf wird nachgereicht")
            else:
                geaendert = normalisiere_slot(bereits)
                if geaendert:
                    atomar_schreiben_json(erwarteter_pfad, bereits, separators=(",", ":"))
                print(f"{kurz}: Ensemble-Slot {vorab_info['lauf']:%Y-%m-%dT%H:%MZ} bereits vorhanden")

        # Danach mehrere offene Slots pruefen. Der Hauptlauf wird ueber die
        # Initialisierungszeit fest angefordert; deshalb darf inzwischen schon
        # ein neueres Ensemble erschienen sein.
        offene_dateien = sorted(OUT.glob(f"{kurz}_*.json"), key=lambda p: p.name, reverse=True)[:8]
        for pfad in offene_dateien:
            try:
                slot = json.loads(pfad.read_text(encoding="utf-8"))
            except Exception:
                continue
            geaendert = normalisiere_slot(slot)
            if not slot["ensemble_vollstaendig"]:
                if geaendert:
                    atomar_schreiben_json(pfad, slot, separators=(",", ":"))
                continue
            if not slot["hauptlauf_vollstaendig"]:
                ergaenzt, meldung = ergaenze_hauptlauf(slot, cfg, fehler)
                geaendert = geaendert or ergaenzt
                print(f"{kurz}: {meldung}")
            if geaendert:
                atomar_schreiben_json(pfad, slot, separators=(",", ":"))

        entfernt = aufraeumen(kurz)
        if entfernt:
            print(f"{kurz}: {len(entfernt)} aeltere Laufdatei(en) aufgeraeumt")
    if fehler:
        print("FEHLER:", *fehler, sep="\n  ")


if __name__ == "__main__":
    main()
