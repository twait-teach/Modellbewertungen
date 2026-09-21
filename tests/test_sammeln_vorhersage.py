import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skripte"))
import sammeln_vorhersage as sv
from gemeinsam import perzentil


# ---------------------------------------------------------------- kumulieren
def test_kumulieren_einfach():
    tagesreihe = {"2026-01-01": 1.0, "2026-01-02": 2.0, "2026-01-03": 0.5}
    ziele = ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert sv.kumulieren(tagesreihe, ziele) == [1.0, 3.0, 3.5]


def test_kumulieren_bricht_bei_luecke_ab_statt_null_anzunehmen():
    """Fehlt ein Tageswert mitten in der Reihe, muss ab dort (und fuer den
    Rest) None stehen -- die Luecke darf NICHT stillschweigend als 0 mm in
    die Summe eingehen (sonst waere die Fortsetzung der Summe falsch)."""
    tagesreihe = {"2026-01-01": 1.0, "2026-01-03": 5.0}  # Tag 2 fehlt
    ziele = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
    out = sv.kumulieren(tagesreihe, ziele)
    assert out[0] == 1.0
    assert out[1] is None
    assert out[2] is None  # auch wenn fuer Tag 3 ein Wert vorhanden waere -- die Kette ist gerissen
    assert out[3] is None


def test_kumulieren_beginnt_bei_null():
    tagesreihe = {"2026-01-01": 0.0}
    assert sv.kumulieren(tagesreihe, ["2026-01-01"]) == [0.0]


# ---------------------------------------------------------------- Mittel/Perzentile: Kommutativitaet praezise geprueft
#
# Mathematisch gilt fuer eine FESTE, VOLLSTAENDIGE Menge von Ensemblemitgliedern:
#   sum_t Mittel_m(x_m,t) == Mittel_m(sum_t x_m,t)
# -- "erst mitteln, dann summieren" und "erst summieren, dann mitteln" sind
# bei vollstaendigen Daten also GLEICHWERTIG fuer den Mittelwert. Fuer
# Perzentile/Quantile gilt diese Vertauschbarkeit dagegen grundsaetzlich NICHT:
#   sum_t Q_p(x_m,t) != Q_p(sum_t x_m,t)
# Der Code (und die Tests) akkumulieren trotzdem grundsaetzlich zuerst je
# Mitglied und bilden erst danach Mittel/Perzentile -- nicht weil das beim
# Mittelwert bei vollstaendigen Daten ein anderes Ergebnis liefern wuerde
# (das tut es nachweislich nicht, siehe Test unten), sondern damit EIN
# Verfahren fuer Mittel UND Perzentile ausreicht, und weil bei UNVOLLSTAEN-
# DIGEN Mitgliederreihen (siehe kumulieren(), das die Kette bei einer Luecke
# abbricht) die Menge der noch gueltigen Mitglieder von Lead zu Lead kleiner
# werden kann -- und sobald die Menge nicht mehr fest ist, gilt die Gleichheit
# auch fuer den Mittelwert nicht mehr (dritter Test unten).

def test_mittelwert_kommutiert_bei_vollstaendigen_daten():
    """Bei einer festen, vollstaendigen Mitgliedermenge muss
    sum_t Mittel_m(taegliche Werte) exakt Mittel_m(akkumulierte Kurve) ergeben."""
    mitglied_a = {"2026-01-01": 2.0, "2026-01-02": 2.0}
    mitglied_b = {"2026-01-01": 6.0, "2026-01-02": 2.0}
    mitglied_c = {"2026-01-01": 4.0, "2026-01-02": 8.0}
    ziele = ["2026-01-01", "2026-01-02"]
    kurven = [sv.kumulieren(m, ziele) for m in (mitglied_a, mitglied_b, mitglied_c)]
    assert kurven == [[2.0, 4.0], [6.0, 8.0], [4.0, 12.0]]

    # Weg 1 (im Code verwendet): je Mitglied akkumulieren, dann ueber die
    # Mitglieder zu Tag 2 mitteln.
    mittel_akkumuliert_tag2 = sum(k[1] for k in kurven) / 3

    # Weg 2 (Kontrolle): je Tag ueber die Mitglieder mitteln, dann die
    # taeglichen Mittel bis Tag 2 aufsummieren.
    tagesmittel_tag1 = sum(m["2026-01-01"] for m in (mitglied_a, mitglied_b, mitglied_c)) / 3
    tagesmittel_tag2 = sum(m["2026-01-02"] for m in (mitglied_a, mitglied_b, mitglied_c)) / 3
    mittel_tagesweise_summiert = tagesmittel_tag1 + tagesmittel_tag2

    assert mittel_akkumuliert_tag2 == pytest.approx(mittel_tagesweise_summiert)
    assert mittel_akkumuliert_tag2 == pytest.approx(8.0)  # (4+8+12)/3


def test_perzentile_kommutieren_nicht_selbst_bei_vollstaendigen_daten():
    """Fuer denselben vollstaendigen Datensatz wie oben: der Median der
    AKKUMULIERTEN Kurven zu Tag 2 weicht vom (falschen) Weg ab, taegliche
    Mediane zu bilden und diese aufzusummieren."""
    mitglied_a = {"2026-01-01": 2.0, "2026-01-02": 2.0}
    mitglied_b = {"2026-01-01": 6.0, "2026-01-02": 2.0}
    mitglied_c = {"2026-01-01": 4.0, "2026-01-02": 8.0}
    ziele = ["2026-01-01", "2026-01-02"]
    kurven = [sv.kumulieren(m, ziele) for m in (mitglied_a, mitglied_b, mitglied_c)]

    p50_akkumuliert_tag2 = perzentil(sorted(k[1] for k in kurven), 0.5)  # Median von [4,8,12] = 8

    p50_tag1 = perzentil(sorted(m["2026-01-01"] for m in (mitglied_a, mitglied_b, mitglied_c)), 0.5)  # Median [2,4,6]=4
    p50_tag2 = perzentil(sorted(m["2026-01-02"] for m in (mitglied_a, mitglied_b, mitglied_c)), 0.5)  # Median [2,2,8]=2
    p50_tagesweise_summiert = p50_tag1 + p50_tag2  # 4 + 2 = 6

    assert p50_akkumuliert_tag2 == 8.0
    assert p50_tagesweise_summiert == 6.0
    assert p50_akkumuliert_tag2 != p50_tagesweise_summiert


def test_fehlende_mitgliedswerte_werden_ausgeschlossen_nicht_als_null_gewertet():
    """Bricht die Kette eines Mitglieds wegen einer Luecke ab (siehe
    test_kumulieren_bricht_bei_luecke_ab_statt_null_anzunehmen), darf dieses
    Mitglied ab dort nicht mit 0 in Mittel/Perzentil eingehen, sondern muss
    aus der Aggregation dieses Leads herausfallen. Als Nebenbefund zeigt der
    Test, warum die Vertauschbarkeit aus dem Test oben NICHT mehr gilt, sobald
    die Mitgliedermenge dadurch von Lead zu Lead unterschiedlich gross ist --
    das ist erwartet (die Mitgliedermenge ist dann nicht mehr "fest"), keine
    Verletzung der mathematischen Aussage fuer vollstaendige Daten."""
    mitglied_a = {"2026-01-01": 2.0, "2026-01-02": 2.0}          # vollstaendig
    mitglied_b = {"2026-01-01": 6.0}                              # Tag 2 fehlt -> Kette bricht dort ab
    mitglied_c = {"2026-01-01": 4.0, "2026-01-02": 8.0}          # vollstaendig
    ziele = ["2026-01-01", "2026-01-02"]
    kum_a = sv.kumulieren(mitglied_a, ziele)
    kum_b = sv.kumulieren(mitglied_b, ziele)
    kum_c = sv.kumulieren(mitglied_c, ziele)
    assert kum_a == [2.0, 4.0]
    assert kum_b == [6.0, None]   # Tag 1 bleibt gueltig, Tag 2 und folgende NICHT
    assert kum_c == [4.0, 12.0]

    # So aggregiert der Produktionscode (siehe verarbeite_modell): nur
    # nicht-None-Werte je Lead gehen ein.
    kurven = [kum_a, kum_b, kum_c]
    mittel_tag1 = sum(k[0] for k in kurven if k[0] is not None) / sum(1 for k in kurven if k[0] is not None)
    mittel_tag2 = sum(k[1] for k in kurven if k[1] is not None) / sum(1 for k in kurven if k[1] is not None)
    assert mittel_tag1 == pytest.approx(4.0)   # (2+6+4)/3, alle drei noch dabei
    assert mittel_tag2 == pytest.approx(8.0)   # (4+12)/2, b faellt raus -- NICHT (2+0+12)/3

    # Zum Vergleich der (falsche) Weg, der Mitglied b's fehlenden Tag-2-Wert
    # als 0 in den Tagesmittelwert einrechnen wuerde:
    falsch_mit_null = (mitglied_a["2026-01-02"] + 0.0 + mitglied_c["2026-01-02"]) / 3
    assert falsch_mit_null == pytest.approx(3.333, abs=0.001)
    assert falsch_mit_null != mittel_tag2

    # Und: weil Mitglied b ab Tag 2 fehlt, ist die Mitgliedermenge nicht mehr
    # fest -- "Tagesmittel aufsummiert" (ueber die jeweils an diesem Tag
    # verfuegbaren Mitglieder) weicht deshalb vom akkumulierten Mittel ab,
    # obwohl beide Wege fuer sich genommen korrekt "fehlende Werte ausschliessen":
    tagesmittel_tag1_alle_drei = sum(m.get("2026-01-01", 0) for m in
                                      ({"2026-01-01": 2.0}, {"2026-01-01": 6.0}, {"2026-01-01": 4.0})) / 3
    tagesmittel_tag2_nur_a_c = (mitglied_a["2026-01-02"] + mitglied_c["2026-01-02"]) / 2  # b hat gar keinen Tag-2-Wert
    tagesweise_summiert_tag2 = tagesmittel_tag1_alle_drei + tagesmittel_tag2_nur_a_c
    assert tagesweise_summiert_tag2 != mittel_tag2  # 4 + 6 = 10, nicht 8 -- genau der erwartete Unterschied


# ---------------------------------------------------------------- Laufpruefung
def _fake_hole_baustein(antworten):
    """Ersetzt gemeinsam.hole() innerhalb von sammeln_vorhersage durch eine
    Funktion, die feste Antworten anhand der URL zurueckgibt -- kein Netzwerk noetig."""
    def hole(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
        for muster, antwort in antworten.items():
            if muster in url:
                return antwort
        return None
    return hole


def _meta(lauf: dt.datetime, verfuegbar: dt.datetime):
    return {
        "last_run_initialisation_time": int(lauf.timestamp()),
        "last_run_availability_time": int(verfuegbar.timestamp()),
    }


def _u(ortszeit):
    """Unixsekunden zu einem lesbaren Ortszeit-Text der Testdaten (Europe/Berlin).

    Nur eine Schreibhilfe fuer die Testdaten: Im September gilt 02:00 Ortszeit
    als 00:00 UTC. Die Produktivlogik selbst arbeitet nur mit Unixzeit.
    """
    from zoneinfo import ZoneInfo
    return int(dt.datetime.fromisoformat(ortszeit).replace(tzinfo=ZoneInfo("Europe/Berlin")).timestamp())


def _ensemble_antwort(ziele, member_werte, kontrolle_werte, temp2m_stunden=None, temp850_stunden=None):
    """Baut eine Fake-Ensemble-Antwort. temp2m_stunden/temp850_stunden sind
    optional: {'JJJJ-MM-TTThh:mm': [kontrolle, member1, member2, ...]} je
    Zeitstempel -- wird nur gebraucht, wenn ein Test Temperatur pruefen will."""
    # Vereinfachtes lokales Stundenraster: 00Z entspricht hier im September
    # 02 Uhr Ortszeit. Niederschlagswerte an den folgenden 02-Uhr-Punkten
    # repraesentieren in diesen Tests jeweils das vorangegangene Intervall.
    regen_zeiten = [f"{tag}T02:00" for tag in ziele]
    alle_zeiten = set(regen_zeiten)
    alle_zeiten.update((temp2m_stunden or {}).keys())
    alle_zeiten.update((temp850_stunden or {}).keys())
    zeiten = sorted(alle_zeiten, key=_u)
    regen_kontrolle = dict(zip(regen_zeiten, kontrolle_werte))
    # Die API liefert (timeformat=unixtime) eindeutige Unixsekunden.
    hourly = {"time": [_u(t) for t in zeiten],
              "precipitation": [regen_kontrolle.get(t, 0.0) for t in zeiten]}
    for i, werte in enumerate(member_werte, start=1):
        mapping = dict(zip(regen_zeiten, werte))
        hourly[f"precipitation_member{i:02d}"] = [mapping.get(t, 0.0) for t in zeiten]
    antwort = {"hourly": hourly}
    for feld, praefix, quelle in (("temperature_2m", "temperature_2m", temp2m_stunden),
                                   ("temperature_850hPa", "temperature_850hPa", temp850_stunden)):
        if quelle is None:
            continue
        hourly[praefix] = [quelle[t][0] if t in quelle else None for t in zeiten]
        n_mitglieder = len(next(iter(quelle.values()))) - 1
        for i in range(1, n_mitglieder + 1):
            hourly[f"{praefix}_member{i:02d}"] = [quelle[t][i] if t in quelle else None for t in zeiten]
    return antwort


def test_verarbeite_modell_lehnt_falsche_laufstunde_ab(monkeypatch):
    heute = dt.date(2026, 9, 17)
    init = dt.datetime(2026, 9, 17, 6, tzinfo=dt.timezone.utc)  # 06Z ist fuer ECMWF nicht erlaubt
    antworten = {
        sv.MODELLE["ecmwf"]["meta_ensemble"]: _meta(init, init + dt.timedelta(hours=10)),
    }
    monkeypatch.setattr(sv, "hole", _fake_hole_baustein(antworten))
    fehler = []
    lauf, hinweise = sv.verarbeite_modell("ecmwf", sv.MODELLE["ecmwf"], fehler, heute)
    assert lauf is None
    assert any("erlaubten Stunden" in h for h in hinweise)


def test_verarbeite_modell_akzeptiert_gueltigen_lauf_und_akkumuliert_korrekt(monkeypatch):
    heute = dt.date(2026, 9, 17)
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    cfg = dict(sv.MODELLE["gfs"])
    cfg["horizont"] = 3  # kleiner Testhorizont
    ziele = ["2026-09-17", "2026-09-18", "2026-09-19", "2026-09-20"]  # heute + 3 Tage (forecast_days=horizont+1)

    # 30 Mitglieder mit 1 mm/Tag, damit Erwartungspruefung (>= 28 Mitglieder) erfuellt ist
    member_werte = [[1.0, 1.0, 1.0, 1.0] for _ in range(30)]
    kontrolle = [0.5, 0.5, 0.5, 0.5]
    # Beide Temperaturfelder reichen vom Modellstart (02 Uhr Ortszeit) bis
    # exakt zum dreitaegigen Horizont; sonst ist der Gesamtlauf absichtlich
    # noch nicht speicherfertig.
    temp_stunden = {}
    for i, zeit in enumerate(("2026-09-17T02:00", "2026-09-18T02:00",
                              "2026-09-19T02:00", "2026-09-20T02:00")):
        temp_stunden[zeit] = [10.0 + i] + [10.0 + i] * 30
    ens_antwort = _ensemble_antwort(
        ziele, member_werte, kontrolle,
        temp2m_stunden=temp_stunden, temp850_stunden=temp_stunden,
    )

    antworten = {
        "meta.json": None,  # wird unten gezielt ueberschrieben
        cfg["ensemble_datensatz"]: None,
    }

    def hole(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
        if cfg["meta_ensemble"] in url:
            return _meta(init, init + dt.timedelta(hours=6))
        if cfg["meta_hauptlauf"] in url:
            return _meta(init, init + dt.timedelta(hours=7))
        if "ensemble-api" in url:
            return ens_antwort
        if "api.open-meteo.com/v1/forecast" in url:
            return _ensemble_antwort(
                ziele, [], [0.4, 0.4, 0.4, 0.4],
                temp2m_stunden={t: [v[0]] for t, v in temp_stunden.items()},
                temp850_stunden={t: [v[0]] for t, v in temp_stunden.items()},
            )
        return None

    monkeypatch.setattr(sv, "hole", hole)
    fehler = []
    lauf, hinweise = sv.verarbeite_modell("gfs", cfg, fehler, heute)
    assert lauf is not None
    assert lauf["ensemble_vollstaendig"] is True
    assert lauf["hauptlauf_vollstaendig"] is False
    assert lauf["vollstaendig"] is False
    assert lauf["mitglieder_n"] == 30
    # korrekt akkumuliert: 1 mm/Tag -> [1,2,3]
    assert lauf["niederschlag"]["mitglieder"][0] == [0.0, 1.0, 2.0, 3.0]
    assert lauf["niederschlag"]["mittel"] == [0.0, 1.0, 2.0, 3.0]
    assert lauf["niederschlag"]["kontrolllauf"] == [0.0, 0.5, 1.0, 1.5]
    # Der Ensemble-Slot wird sofort veroeffentlicht; der Hauptlauf kommt separat.
    assert lauf["niederschlag"]["hauptlauf"] is None


def test_verarbeite_modell_wartet_nicht_auf_aktuelle_hauptlauf_metadaten(monkeypatch):
    heute = dt.date(2026, 9, 17)
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    cfg = dict(sv.MODELLE["gfs"])
    cfg["horizont"] = 2
    ziele = ["2026-09-17", "2026-09-18", "2026-09-19"]
    member_werte = [[1.0, 1.0, 1.0] for _ in range(30)]
    ens_antwort = _ensemble_antwort(ziele, member_werte, [0.5, 0.5, 0.5])

    def hole(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
        if cfg["meta_ensemble"] in url:
            return _meta(init, init + dt.timedelta(hours=6))
        if cfg["meta_hauptlauf"] in url:
            raise AssertionError("Die aktuellen Hauptlauf-Metadaten duerfen den Ensemble-Slot nicht blockieren")
        if "ensemble-api" in url:
            return ens_antwort
        return None

    monkeypatch.setattr(sv, "hole", hole)
    fehler = []
    lauf, hinweise = sv.verarbeite_modell("gfs", cfg, fehler, heute)
    assert lauf is not None
    assert lauf["init"] == "2026-09-17T00:00Z"
    assert lauf["hauptlauf_vollstaendig"] is False


def test_ecmwf_speichert_nur_operationellen_hauptlauf_ohne_kontrolllauf(monkeypatch):
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    cfg = dict(sv.MODELLE["ecmwf"])
    cfg["horizont"] = 1
    ziele = ["2026-09-17", "2026-09-18"]
    temperatur = {
        "2026-09-17T02:00": [10.0] + [10.0] * 50,
        "2026-09-18T02:00": [11.0] + [11.0] * 50,
    }
    ensemble = _ensemble_antwort(
        ziele, [[1.0, 1.0] for _ in range(50)], [0.5, 0.5],
        temp2m_stunden=temperatur, temp850_stunden=temperatur,
    )
    hauptlauf = _ensemble_antwort(
        ziele, [], [0.4, 0.4],
        temp2m_stunden={t: [v[0] + 2] for t, v in temperatur.items()},
        temp850_stunden={t: [v[0] - 2] for t, v in temperatur.items()},
    )

    def hole(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
        if cfg["meta_ensemble"] in url:
            return _meta(init, init + dt.timedelta(hours=10))
        if cfg["meta_hauptlauf"] in url:
            return _meta(init, init + dt.timedelta(hours=11))
        if "ensemble-api" in url:
            return ensemble
        if "api.open-meteo.com/v1/forecast" in url:
            return hauptlauf
        return None

    monkeypatch.setattr(sv, "hole", hole)
    lauf, hinweise = sv.verarbeite_modell("ecmwf", cfg, [], init.date())
    assert lauf["ensemble_vollstaendig"] is True, hinweise
    for feld in ("niederschlag", "temperatur_2m", "temperatur_850hpa"):
        assert lauf[feld]["kontrolllauf"] is None
        assert lauf[feld]["hauptlauf"] is None

    # Der spaetere Abruf ist auf GENAU diesen Slot fixiert, nicht auf den
    # inzwischen neuesten Echtzeitlauf.
    angefragte_runs = []
    def single_runs(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
        assert "single-runs-api" in url
        angefragte_runs.append(params["run"])
        if params["forecast_hours"] == 1:
            return {"hourly": {"temperature_2m": [12.0]}}
        return hauptlauf

    monkeypatch.setattr(sv, "hole", single_runs)
    ensemble_vorher = json.loads(json.dumps(lauf["temperatur_2m"]["mitglieder"]))
    geaendert, meldung = sv.ergaenze_hauptlauf(lauf, cfg, [])
    assert geaendert is True, meldung
    assert angefragte_runs == ["2026-09-17T00:00", "2026-09-17T00:00"]
    assert lauf["vollstaendig"] is True
    assert lauf["temperatur_2m"]["mitglieder"] == ensemble_vorher
    for feld in ("niederschlag", "temperatur_2m", "temperatur_850hpa"):
        assert lauf[feld]["kontrolllauf"] is None
        assert lauf[feld]["hauptlauf"]


def test_normalisiere_slot_verwirft_falsch_zugeordneten_alt_hauptlauf():
    reihe = {"zeiten": ["2026-09-17T02:00"], "zeitpunkte_unix": [1],
             "mitglieder": [[1.0]], "kontrolllauf": [0.8], "hauptlauf": [9.9]}
    lauf = {"modell": "gfs", "zeitauflosung": "modellnativ-v1",
            "temperatur_2m": dict(reihe), "temperatur_850hpa": dict(reihe),
            "niederschlag": dict(reihe),
            "hinweise": ["deterministischer Lauf ist 19.09.00Z, passt nicht zum Ensemble-Lauf"]}
    assert sv.normalisiere_slot(lauf) is True
    assert lauf["ensemble_vollstaendig"] is True
    assert lauf["hauptlauf_vollstaendig"] is False
    assert lauf["vollstaendig"] is False
    assert lauf["hinweise"] == []
    assert all(lauf[f]["hauptlauf"] is None for f in ("temperatur_2m", "temperatur_850hpa", "niederschlag"))


def test_verarbeite_modell_meldet_zu_wenig_mitglieder(monkeypatch):
    heute = dt.date(2026, 9, 17)
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    cfg = dict(sv.MODELLE["gfs"])
    cfg["horizont"] = 2
    ziele = ["2026-09-17", "2026-09-18", "2026-09-19"]
    member_werte = [[1.0, 1.0, 1.0] for _ in range(5)]  # viel zu wenige Mitglieder
    ens_antwort = _ensemble_antwort(ziele, member_werte, [0.5, 0.5, 0.5])

    def hole(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
        if cfg["meta_ensemble"] in url:
            return _meta(init, init + dt.timedelta(hours=6))
        if cfg["meta_hauptlauf"] in url:
            return _meta(init, init + dt.timedelta(hours=7))
        if "ensemble-api" in url:
            return ens_antwort
        if "api.open-meteo.com/v1/forecast" in url:
            return ens_antwort
        return None

    monkeypatch.setattr(sv, "hole", hole)
    fehler = []
    lauf, hinweise = sv.verarbeite_modell("gfs", cfg, fehler, heute)
    assert lauf is not None
    assert lauf["vollstaendig"] is False
    assert any("Mitglieder" in h for h in hinweise)


# ---------------------------------------------------------------- Temperatur: nicht akkumuliert
def test_stundenreihe_keine_kette():
    """Anders als beim Niederschlag darf eine fehlende Temperatur zu einem
    Zeitpunkt NICHT die folgenden Zeitpunkte mit-beeinflussen -- jeder
    Zeitschritt ist unabhaengig."""
    start = 1767225600  # 2026-01-01T00:00Z
    serie = {start: 5.0, start + 7200: 7.0}  # +1 h fehlt
    zeiten = [start, start + 3600, start + 7200, start + 10800]
    out = sv.stundenreihe(serie, zeiten)
    assert out == [5.0, None, 7.0, None]  # 02:00 ist trotz Luecke bei 01:00 intakt


def test_modell_zeitfenster_beginnt_am_modellstart_und_nutzt_dreistundenschritte():
    """Auch bei lokaler Zeitdarstellung muss das Meteogramm am echten
    UTC-Modellstart beginnen und exakt am Horizont enden."""
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)  # 02:00 MESZ
    verfuegbar = [_u(t) for t in (
        "2026-09-17T01:00",  # vor Initialisierung -> raus
        "2026-09-17T02:00",  # Initialisierung -> rein
        "2026-09-17T03:00",  # +1 h, interpoliert -> raus
        "2026-09-17T05:00",  # +3 h, modellnah -> rein
        "2026-09-19T02:00",  # exakt +48h -> rein
        "2026-09-19T03:00",  # nach Horizont -> raus
    )]
    zeiten, unix = sv.modell_zeitfenster(verfuegbar, init, 2, "ecmwf")
    assert zeiten == ["2026-09-17T02:00", "2026-09-17T05:00", "2026-09-19T02:00"]
    assert unix[0] == int(init.timestamp())
    assert unix[-1] == int((init + dt.timedelta(days=2)).timestamp())


def test_gfs_modell_zeitfenster_wechselt_nach_240_stunden_auf_sechsstuendlich():
    init = dt.datetime(2026, 1, 5, 0, tzinfo=dt.timezone.utc)  # 01:00 MEZ
    zeiten = [
        "2026-01-05T01:00",  # +0
        "2026-01-15T01:00",  # +240
        "2026-01-15T04:00",  # +243 -> nach Grenze nicht mehr modellnah
        "2026-01-15T07:00",  # +246 -> rein
    ]
    ausgewaehlt, unix = sv.modell_zeitfenster([_u(t) for t in zeiten], init, 11, "gfs")
    assert ausgewaehlt == [zeiten[0], zeiten[1], zeiten[3]]
    assert unix[2] - unix[1] == 6 * 3600


def test_niederschlag_wird_aus_stundenmengen_zu_intervallen_kumuliert():
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)  # 02 Uhr MESZ
    alle = [_u(f"2026-09-17T{h:02d}:00") for h in range(2, 9)]
    ausgabe = [alle[0], alle[3], alle[6]]  # +0, +3, +6 h
    serie = {t: 1.0 for t in alle}
    assert sv.niederschlag_kumulieren(serie, alle, ausgabe, init) == [0.0, 3.0, 6.0]


def test_niederschlag_luecke_bricht_kumulationskette_ab():
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    alle = [_u(f"2026-09-17T{h:02d}:00") for h in range(2, 9)]
    ausgabe = [alle[0], alle[3], alle[6]]
    serie = {t: 1.0 for t in alle}
    serie[_u("2026-09-17T04:00")] = None
    assert sv.niederschlag_kumulieren(serie, alle, ausgabe, init) == [0.0, None, None]


def test_aggregiere_lead_mittel_und_perzentile():
    # 3 Mitglieder an einem Lead: -2.0, 3.0, 5.0
    mitglieder = [[-2.0, 1.0], [3.0, 1.0], [5.0, 1.0]]
    k = sv.aggregiere_lead(mitglieder, 0)
    assert k["mittel"] == 2.0
    assert k["min"] == -2.0
    assert k["max"] == 5.0
    assert k["n"] == 3
    assert k["p50"] == 3.0


def test_aggregiere_lead_fehlender_mitgliedswert_wird_ausgeschlossen_nicht_als_null():
    """Ein fehlender Mitgliedswert (None) darf das Mittel nicht Richtung 0 ziehen."""
    mitglieder = [[10.0], [12.0], [None]]  # drittes Mitglied fehlt an diesem Lead
    k = sv.aggregiere_lead(mitglieder, 0)
    assert k["n"] == 2
    assert k["mittel"] == 11.0  # (10+12)/2, NICHT (10+12+0)/3


def test_aggregiere_lead_ohne_daten_liefert_none_ueberall():
    k = sv.aggregiere_lead([[None], [None]], 0)
    assert k == {"mittel": None, "p10": None, "p50": None, "p90": None, "min": None, "max": None, "n": 0}


def test_aggregiere_lead_negative_temperaturen_korrekt_sortiert():
    """Negative Werte muessen numerisch (nicht als Text) sortiert werden --
    -10 ist kleiner als -2, obwohl "-10" als Text nach "-2" kaeme."""
    mitglieder = [[-2.0], [-10.0], [-5.0]]
    k = sv.aggregiere_lead(mitglieder, 0)
    assert k["min"] == -10.0
    assert k["max"] == -2.0
    assert k["mittel"] == pytest.approx(-17.0 / 3, abs=0.01)


def test_verarbeite_modell_liefert_volle_stundenreihe(monkeypatch):
    """End-to-End: Stunden-API wird auf modellnahe 3-h-Punkte reduziert."""
    heute = dt.date(2026, 9, 17)
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    cfg = dict(sv.MODELLE["gfs"])
    cfg["horizont"] = 2
    ziele = ["2026-09-17", "2026-09-18", "2026-09-19"]

    member_werte_regen = [[1.0, 1.0, 1.0] for _ in range(30)]
    # Stuendliche API-Werte mit Tagesgang; gespeichert werden nur +0,+3,...
    temp2m_stunden = {}
    lokaler_start = dt.datetime(2026, 9, 17, 2)
    for lead in range(49):
        text = (lokaler_start + dt.timedelta(hours=lead)).strftime("%Y-%m-%dT%H:%M")
        wert = -3.0 + (lead % 24) / 3
        temp2m_stunden[text] = [wert] + [wert + i * 0.1 for i in range(30)]
    # Wert vor dem echten Modellstart muss ausgeschlossen werden.
    temp2m_stunden["2026-09-17T01:00"] = [99.0] + [99.0] * 30
    temp2m_stunden["2026-09-19T06:00"] = [88.0] + [88.0] * 30
    ens_antwort = _ensemble_antwort(ziele, member_werte_regen, [0.5, 0.5, 0.5], temp2m_stunden=temp2m_stunden)

    gesehene_parameter = []

    def hole(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
        if cfg["meta_ensemble"] in url:
            return _meta(init, init + dt.timedelta(hours=6))
        if cfg["meta_hauptlauf"] in url:
            return _meta(init, init + dt.timedelta(hours=7))
        if "ensemble-api" in url:
            gesehene_parameter.append(params)
            return ens_antwort
        if "api.open-meteo.com/v1/forecast" in url:
            return ens_antwort
        return None

    monkeypatch.setattr(sv, "hole", hole)
    fehler = []
    lauf, hinweise = sv.verarbeite_modell("gfs", cfg, fehler, heute)
    assert lauf is not None
    t2 = lauf["temperatur_2m"]
    assert t2 is not None
    # Ab echtem Modellstart bis exakt +48 Stunden. Der Wert vor dem Start und
    # der Wert nach dem Horizont duerfen nicht enthalten sein.
    assert len(t2["zeiten"]) == 17
    assert t2["zeiten"][:3] == ["2026-09-17T02:00", "2026-09-17T05:00", "2026-09-17T08:00"]
    assert len(t2["kontrolllauf"]) == 17
    assert len(t2["mittel"]) == 17
    assert len(t2["zeitpunkte_unix"]) == 17
    assert t2["zeitpunkte_unix"][0] == int(init.timestamp())
    assert t2["zeitpunkte_unix"][-1] == int((init + dt.timedelta(days=2)).timestamp())
    assert gesehene_parameter[0]["past_days"] == 1
    # Tagesgang innerhalb eines Tages sichtbar.
    assert t2["kontrolllauf"][3] > t2["kontrolllauf"][0]
    # negative Werte korrekt uebernommen, nicht akkumuliert
    assert t2["kontrolllauf"][0] == -3.0
    assert t2["n"] == [30] * 17
    # 850 hPa wurde in dieser Antwort nicht mitgeschickt -> muss None sein, kein Crash
    assert lauf["temperatur_850hpa"] is None
    assert any("temperatur_850hpa" in h for h in hinweise)


# ---------------------------------------------------------------- main(): erst speichern, wenn vollstaendig
def test_main_speichert_unvollstaendigen_lauf_nicht(monkeypatch, tmp_path):
    heute = dt.date(2026, 9, 17)
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(sv, "OUT", tmp_path)

    unvollstaendiger_lauf = {
        "modell": "gfs", "modellname": "GFS", "init": init.strftime("%Y-%m-%dT%H:%MZ"),
        "mitglieder_n": 5, "vollstaendig": False, "hinweise": ["zu wenige Mitglieder"],
        "hauptlauf_kumulativ": None, "temperatur_2m": None, "temperatur_850hpa": None,
        "horizont_tage": 16,
    }
    monkeypatch.setattr(sv, "verarbeite_modell", lambda kurz, cfg, fehler, heute, **kw: (unvollstaendiger_lauf, ["zu wenige Mitglieder"]))
    monkeypatch.setattr(sv, "laufinfo", lambda datensatz, fehler: None)  # Vorab-Check findet nichts -> faellt durch zu verarbeite_modell

    import sys as _sys
    monkeypatch.setattr(_sys, "argv", ["sammeln_vorhersage.py", "--modell", "gfs"])
    sv.main()

    erwartete_datei = tmp_path / sv.dateiname("gfs", init)
    assert not erwartete_datei.exists(), "unvollstaendiger Lauf wurde faelschlich gespeichert"


def test_alte_vollstaendige_laufdatei_ohne_modellformat_wird_nicht_uebersprungen():
    """Auch bisherige Stundenkurven muessen ohne neuen Marker neu abgerufen werden."""
    alt = {
        "vollstaendig": True,
        "temperatur_2m": {"zeiten": ["2026-09-17T12:00"], "mittel": [15.0]},
        "temperatur_850hpa": {"zeiten": ["2026-09-17T12:00"], "mittel": [5.0]},
    }
    neu = {
        "modell": "gfs",
        "vollstaendig": True,
        "zeitauflosung": "modellnativ-v1",
        "temperatur_2m": {"zeiten": ["2026-09-17T02:00"], "zeitpunkte_unix": [1789603200], "mitglieder": [[15.0]], "hauptlauf": None, "kontrolllauf": [14.0]},
        "temperatur_850hpa": {"zeiten": ["2026-09-17T02:00"], "zeitpunkte_unix": [1789603200], "mitglieder": [[5.0]], "hauptlauf": None, "kontrolllauf": [4.0]},
        "niederschlag": {"zeiten": ["2026-09-17T02:00"], "zeitpunkte_unix": [1789603200], "mitglieder": [[1.0]], "hauptlauf": None, "kontrolllauf": [0.8]},
    }
    assert sv.hat_modellnative_meteogrammdaten(alt) is False
    assert sv.hat_modellnative_meteogrammdaten(neu) is True


def test_main_speichert_vollstaendigen_ensemble_slot_ohne_hauptlauf(monkeypatch, tmp_path):
    heute = dt.date(2026, 9, 17)
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(sv, "OUT", tmp_path)

    reihe = {"zeiten": ["2026-09-17T02:00"], "zeitpunkte_unix": [1789603200],
             "mitglieder": [[1.0]], "kontrolllauf": [0.8], "hauptlauf": None}
    vollstaendiger_lauf = {
        "modell": "gfs", "modellname": "GFS", "init": init.strftime("%Y-%m-%dT%H:%MZ"),
        "mitglieder_n": 30, "ensemble_vollstaendig": True,
        "hauptlauf_vollstaendig": False, "vollstaendig": False, "hinweise": [],
        "zeitauflosung": "modellnativ-v1", "niederschlag": dict(reihe),
        "temperatur_2m": dict(reihe), "temperatur_850hpa": dict(reihe), "horizont_tage": 16,
    }
    monkeypatch.setattr(sv, "verarbeite_modell", lambda kurz, cfg, fehler, heute, **kw: (vollstaendiger_lauf, []))
    monkeypatch.setattr(sv, "laufinfo", lambda datensatz, fehler: {"lauf": init, "verfuegbar": init})
    monkeypatch.setattr(sv, "ergaenze_hauptlauf", lambda lauf, cfg, fehler: (False, "noch nicht da"))

    import sys as _sys
    monkeypatch.setattr(_sys, "argv", ["sammeln_vorhersage.py", "--modell", "gfs"])
    sv.main()

    erwartete_datei = tmp_path / sv.dateiname("gfs", init)
    assert erwartete_datei.exists(), "vollstaendiger Ensemble-Slot wurde nicht sofort gespeichert"
    gespeichert = __import__("json").loads(erwartete_datei.read_text(encoding="utf-8"))
    assert gespeichert["hauptlauf_vollstaendig"] is False


# ---------------------------------------------------------------- Sortierung ueber Tagesgrenzen
def test_aufraeumen_sortiert_ueber_tagesgrenzen_korrekt(tmp_path, monkeypatch):
    """dateiname() codiert die volle Initialisierung (JJJJ-MM-TTThh), ein reiner
    Textvergleich muss deshalb ueber Monats-/Tagesgrenzen hinweg richtig
    chronologisch sortieren (z.B. ...09-30T18 vor ...10-01T00, nicht danach)."""
    monkeypatch.setattr(sv, "OUT", tmp_path)
    monkeypatch.setattr(sv, "AUFBEWAHREN", 2)
    laeufe = [
        dt.datetime(2026, 9, 30, 18, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 10, 1, 0, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 10, 1, 6, tzinfo=dt.timezone.utc),
    ]
    for init in laeufe:
        (tmp_path / sv.dateiname("gfs", init)).write_text("{}", encoding="utf-8")
    entfernt = sv.aufraeumen("gfs")
    # AUFBEWAHREN=2 -> die beiden juengsten (10-01 06Z, 10-01 00Z) bleiben,
    # der aelteste (09-30 18Z) wird entfernt
    assert entfernt == [sv.dateiname("gfs", laeufe[0])]
    verbleibend = sorted(p.name for p in tmp_path.glob("gfs_*.json"))
    assert verbleibend == sorted([sv.dateiname("gfs", laeufe[1]), sv.dateiname("gfs", laeufe[2])])


def test_dateinamen_string_sortierung_entspricht_chronologischer_reihenfolge():
    """Regressionstest fuer genau das Muster aus Punkt 6 der Aufgabenstellung:
    GFS-Lauffolge ueber eine Tagesgrenze, rein als String verglichen."""
    namen = [
        sv.dateiname("gfs", dt.datetime(2026, 9, 17, 18, tzinfo=dt.timezone.utc)),
        sv.dateiname("gfs", dt.datetime(2026, 9, 18, 0, tzinfo=dt.timezone.utc)),
        sv.dateiname("gfs", dt.datetime(2026, 9, 18, 6, tzinfo=dt.timezone.utc)),
        sv.dateiname("gfs", dt.datetime(2026, 9, 18, 12, tzinfo=dt.timezone.utc)),
    ]
    assert sorted(namen) == namen  # aufsteigend sortiert == chronologisch aufsteigend


# ---------------------------------------------------------------- Laufwechsel waehrend des Ensemble-Abrufs
def _vollstaendiger_lauf(init):
    reihe = {"zeiten": ["2026-09-17T02:00"], "zeitpunkte_unix": [1789603200],
             "mitglieder": [[1.0]], "kontrolllauf": [0.8], "hauptlauf": None}
    return {
        "modell": "gfs", "modellname": "GFS", "init": init.strftime("%Y-%m-%dT%H:%MZ"),
        "mitglieder_n": 30, "ensemble_vollstaendig": True,
        "hauptlauf_vollstaendig": False, "vollstaendig": False, "hinweise": [],
        "zeitauflosung": "modellnativ-v1", "niederschlag": dict(reihe),
        "temperatur_2m": dict(reihe), "temperatur_850hpa": dict(reihe), "horizont_tage": 16,
    }


def _main_gfs(monkeypatch, tmp_path, metadaten, lauf):
    """Startet main() fuer GFS. ``metadaten`` ist die Folge der nacheinander
    gemeldeten Initialisierungszeiten (None = Metadaten nicht abrufbar)."""
    monkeypatch.setattr(sv, "OUT", tmp_path)
    folge = iter(metadaten)
    aufrufe = []

    def laufinfo(datensatz, fehler):
        aufrufe.append(datensatz)
        init = next(folge)
        return None if init is None else {"lauf": init, "verfuegbar": init}

    verarbeitet = []

    def verarbeite(kurz, cfg, fehler, heute, **kw):
        verarbeitet.append(kw)
        return lauf, []

    monkeypatch.setattr(sv, "laufinfo", laufinfo)
    monkeypatch.setattr(sv, "verarbeite_modell", verarbeite)
    monkeypatch.setattr(sv, "ergaenze_hauptlauf", lambda l, c, f: (False, "noch nicht da"))
    import sys as _sys
    monkeypatch.setattr(_sys, "argv", ["sammeln_vorhersage.py", "--modell", "gfs"])
    sv.main()
    return aufrufe, verarbeitet


def test_laufwechsel_waehrend_des_abrufs_speichert_keinen_slot(monkeypatch, tmp_path):
    init_a = dt.datetime(2026, 9, 17, 6, tzinfo=dt.timezone.utc)
    init_b = dt.datetime(2026, 9, 17, 12, tzinfo=dt.timezone.utc)  # inzwischen erschienen
    lauf = _vollstaendiger_lauf(init_a)

    # bereits gespeicherter, gueltiger Slot eines aelteren Laufs -- darf sich nicht aendern
    alt = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    alt_pfad = tmp_path / sv.dateiname("gfs", alt)
    alt_inhalt = json.dumps(_vollstaendiger_lauf(alt), separators=(",", ":"))
    alt_pfad.write_text(alt_inhalt, encoding="utf-8")

    # 1. Aufruf: vor dem Abruf -> A; 2. Aufruf: unmittelbar vor dem Speichern -> B
    _main_gfs(monkeypatch, tmp_path, [init_a, init_b], lauf)

    assert not (tmp_path / sv.dateiname("gfs", init_a)).exists(), "Slot trotz Laufwechsel gespeichert"
    assert not (tmp_path / sv.dateiname("gfs", init_b)).exists(), "Antwort wurde einem falschen Slot zugeordnet"
    assert alt_pfad.read_text(encoding="utf-8") == alt_inhalt


def test_nach_laufwechsel_gelingt_der_naechste_durchlauf(monkeypatch, tmp_path):
    init_b = dt.datetime(2026, 9, 17, 12, tzinfo=dt.timezone.utc)
    lauf = _vollstaendiger_lauf(init_b)
    _main_gfs(monkeypatch, tmp_path, [init_b, init_b], lauf)
    gespeichert = tmp_path / sv.dateiname("gfs", init_b)
    assert gespeichert.exists()
    assert json.loads(gespeichert.read_text(encoding="utf-8"))["init"] == "2026-09-17T12:00Z"


def test_nicht_abrufbare_kontroll_metadaten_speichern_nicht(monkeypatch, tmp_path):
    init_a = dt.datetime(2026, 9, 17, 6, tzinfo=dt.timezone.utc)
    _main_gfs(monkeypatch, tmp_path, [init_a, None], _vollstaendiger_lauf(init_a))
    assert not (tmp_path / sv.dateiname("gfs", init_a)).exists()


def test_vorab_ermittelte_metadaten_werden_an_die_verarbeitung_durchgereicht(monkeypatch, tmp_path):
    init_a = dt.datetime(2026, 9, 17, 6, tzinfo=dt.timezone.utc)
    _, verarbeitet = _main_gfs(monkeypatch, tmp_path, [init_a, init_a], _vollstaendiger_lauf(init_a))
    assert verarbeitet and verarbeitet[0]["ens_info"]["lauf"] == init_a


def test_verarbeite_modell_nutzt_uebergebene_metadaten_statt_neuer_abfrage(monkeypatch):
    init = dt.datetime(2026, 9, 17, 6, tzinfo=dt.timezone.utc)
    aufrufe = []
    monkeypatch.setattr(sv, "laufinfo", lambda d, f: aufrufe.append(d))
    monkeypatch.setattr(sv, "hole", _fake_hole_baustein({}))  # Ensemble nicht abrufbar
    lauf, hinweise = sv.verarbeite_modell("gfs", sv.MODELLE["gfs"], [], dt.date(2026, 9, 17),
                                          ens_info={"lauf": init, "verfuegbar": init})
    assert lauf is None and aufrufe == []   # keine zweite Metadatenabfrage innerhalb der Verarbeitung


# ---------------------------------------------------------------- Nachladen des Langfristteils (Stufe 3)
def _slot_mit_hauptlauf(init, wert=1.0, hauptlauf=15.0, abgerufen="2026-09-17T06:00Z"):
    lauf = _vollstaendiger_lauf(init)
    for feld in ("niederschlag", "temperatur_2m", "temperatur_850hpa"):
        lauf[feld] = {**lauf[feld], "mitglieder": [[wert]], "hauptlauf": [hauptlauf]}
    lauf["abgerufen"] = abgerufen
    lauf["hauptlauf_abgerufen"] = "2026-09-17T08:00Z"
    lauf["hauptlauf_vollstaendig"] = lauf["vollstaendig"] = True     # so, wie normalisiere_slot ihn ablegt
    return lauf


def _neu_abgerufen(init, wert):
    lauf = _vollstaendiger_lauf(init)
    for feld in ("niederschlag", "temperatur_2m", "temperatur_850hpa"):
        lauf[feld] = {**lauf[feld], "mitglieder": [[wert]], "hauptlauf": None}
    lauf["abgerufen"] = "2026-09-17T12:00Z"
    return lauf


def _durchlauf_mit_bestehendem_slot(monkeypatch, tmp_path, bestehend, neu, metadaten):
    init = dt.datetime.strptime(bestehend["init"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
    pfad = tmp_path / sv.dateiname("gfs", init)
    sv.atomar_schreiben_json(pfad, bestehend, separators=(",", ":"))
    vorher = pfad.read_text(encoding="utf-8")
    _main_gfs(monkeypatch, tmp_path, metadaten, neu)
    return pfad, vorher


def test_geaenderter_langfristteil_ersetzt_das_ensemble_und_behaelt_den_hauptlauf(monkeypatch, tmp_path):
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    pfad, vorher = _durchlauf_mit_bestehendem_slot(
        monkeypatch, tmp_path, _slot_mit_hauptlauf(init, wert=1.0), _neu_abgerufen(init, wert=7.5), [init, init])
    nachher = json.loads(pfad.read_text(encoding="utf-8"))
    assert nachher["temperatur_2m"]["mitglieder"] == [[7.5]]                   # neuer Stand des Ensembles
    assert nachher["niederschlag"]["mitglieder"] == [[7.5]]
    assert nachher["temperatur_2m"]["hauptlauf"] == [15.0]                      # Hauptlauf bleibt erhalten
    assert nachher["hauptlauf_vollstaendig"] is True and nachher["vollstaendig"] is True
    assert nachher["hauptlauf_abgerufen"] == "2026-09-17T08:00Z"
    assert nachher["init"] == "2026-09-17T00:00Z"
    assert nachher["abgerufen"] == "2026-09-17T12:00Z" and pfad.read_text(encoding="utf-8") != vorher


def test_unveraendertes_ensemble_schreibt_nichts_neu(monkeypatch, tmp_path):
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    pfad, vorher = _durchlauf_mit_bestehendem_slot(
        monkeypatch, tmp_path, _slot_mit_hauptlauf(init, wert=1.0), _neu_abgerufen(init, wert=1.0), [init, init])
    # Nur die Abrufzeit ist anders -- das zaehlt nicht als Aenderung (kein Git-Commit im Workflow)
    assert pfad.read_text(encoding="utf-8") == vorher


def test_unvollstaendiger_neuabruf_ersetzt_nichts(monkeypatch, tmp_path):
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    neu = _neu_abgerufen(init, wert=7.5)
    neu["ensemble_vollstaendig"] = False
    pfad, vorher = _durchlauf_mit_bestehendem_slot(monkeypatch, tmp_path, _slot_mit_hauptlauf(init), neu, [init, init])
    assert pfad.read_text(encoding="utf-8") == vorher


def test_neuabruf_mit_weniger_mitgliedern_ersetzt_nichts(monkeypatch, tmp_path):
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    neu = _neu_abgerufen(init, wert=7.5)
    neu["mitglieder_n"] = 12
    pfad, vorher = _durchlauf_mit_bestehendem_slot(monkeypatch, tmp_path, _slot_mit_hauptlauf(init), neu, [init, init])
    assert pfad.read_text(encoding="utf-8") == vorher


def test_laufwechsel_waehrend_des_nachladens_ersetzt_nichts(monkeypatch, tmp_path):
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    inzwischen = dt.datetime(2026, 9, 17, 6, tzinfo=dt.timezone.utc)
    pfad, vorher = _durchlauf_mit_bestehendem_slot(
        monkeypatch, tmp_path, _slot_mit_hauptlauf(init), _neu_abgerufen(init, wert=7.5), [init, inzwischen])
    assert pfad.read_text(encoding="utf-8") == vorher
    assert not (tmp_path / sv.dateiname("gfs", inzwischen)).exists()


def test_anderes_zeitraster_verwirft_den_alten_hauptlauf_zur_neuholung(monkeypatch, tmp_path):
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    neu = _neu_abgerufen(init, wert=7.5)
    for feld in ("niederschlag", "temperatur_2m", "temperatur_850hpa"):
        neu[feld]["zeitpunkte_unix"] = [1789603200 + 3 * 3600]
    pfad, _ = _durchlauf_mit_bestehendem_slot(monkeypatch, tmp_path, _slot_mit_hauptlauf(init), neu, [init, init])
    nachher = json.loads(pfad.read_text(encoding="utf-8"))
    assert nachher["temperatur_2m"]["hauptlauf"] is None and nachher["hauptlauf_vollstaendig"] is False


def test_genug_laeufe_fuer_laufwahl_und_drei_vorlaeufe():
    """Die Laufwahl bietet bis zu 6 Laeufe an, jeder davon braucht 3 Vorlaeufe."""
    assert sv.AUFBEWAHREN >= 6 + 3


# ---------------------------------------------------------------- Plausibilitaet beim Neuabruf
def _mit_850(lauf, reihen):
    """Setzt 850-hPa-Mitglieder (Liste von Reihen) mit passendem Zeitraster."""
    n = len(reihen[0])
    lauf["temperatur_850hpa"] = {**lauf["temperatur_850hpa"], "mitglieder": reihen,
                                 "zeiten": ["x"] * n, "zeitpunkte_unix": [1789603200 + 3 * 3600 * i for i in range(n)]}
    return lauf


SAUBER = [[5.0, 6.0, 7.0, 8.0, 9.0], [4.0, 5.2, 6.1, 7.3, 8.0], [6.0, 6.8, 8.1, 8.9, 10.0]]
# ab dem dritten Zeitpunkt laufen fremde Reihen weiter (wie ECMWF 20.09.2026, +153 h)
KAPUTT = [[5.0, 6.0, 12.0, 12.5, 13.0], [4.0, 5.2, 0.1, 0.4, 1.0], [6.0, 6.8, 11.0, 11.2, 12.0]]


def test_plausibilitaet_erkennt_nicht_zusammengehoerige_reihen():
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    assert sv.ist_plausibel(_mit_850(_vollstaendiger_lauf(init), SAUBER))
    mass, stelle = sv.groesster_mitgliedersprung(_mit_850(_vollstaendiger_lauf(init), KAPUTT))
    assert mass > sv.PLAUSI_SCHWELLE_K and stelle == 2
    assert not sv.ist_plausibel(_mit_850(_vollstaendiger_lauf(init), KAPUTT))


def test_letzter_zeitpunkt_zaehlt_nicht_mit():
    """GFS +384 h ist bei Open-Meteo dauerhaft auffaellig -- darf keinen Lauf verwerfen."""
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    reihen = [r[:-1] + [r[-1] + (8 if i % 2 else -8)] for i, r in enumerate(SAUBER)]
    assert sv.ist_plausibel(_mit_850(_vollstaendiger_lauf(init), reihen))


def test_unplausibler_neuabruf_ersetzt_keinen_plausiblen_slot(monkeypatch, tmp_path):
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    bestehend = _mit_850(_slot_mit_hauptlauf(init, wert=1.0), SAUBER)
    bestehend["temperatur_850hpa"]["hauptlauf"] = [15.0] * 5
    neu = _mit_850(_neu_abgerufen(init, wert=7.5), KAPUTT)
    pfad, vorher = _durchlauf_mit_bestehendem_slot(monkeypatch, tmp_path, bestehend, neu, [init, init])
    assert pfad.read_text(encoding="utf-8") == vorher


def test_plausibler_neuabruf_ersetzt_einen_unplausiblen_slot(monkeypatch, tmp_path):
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    bestehend = _mit_850(_slot_mit_hauptlauf(init, wert=1.0), KAPUTT)
    bestehend["temperatur_850hpa"]["hauptlauf"] = [15.0] * 5
    neu = _mit_850(_neu_abgerufen(init, wert=7.5), SAUBER)
    pfad, _ = _durchlauf_mit_bestehendem_slot(monkeypatch, tmp_path, bestehend, neu, [init, init])
    nachher = json.loads(pfad.read_text(encoding="utf-8"))
    assert nachher["temperatur_850hpa"]["mitglieder"] == SAUBER
    assert nachher["temperatur_2m"]["hauptlauf"] == [15.0]        # Hauptlauf bleibt erhalten

