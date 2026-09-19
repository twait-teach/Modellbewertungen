import datetime as dt
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


def _ensemble_antwort(ziele, member_werte, kontrolle_werte, temp2m_stunden=None, temp850_stunden=None):
    """Baut eine Fake-Ensemble-Antwort. temp2m_stunden/temp850_stunden sind
    optional: {'JJJJ-MM-TTThh:mm': [kontrolle, member1, member2, ...]} je
    Zeitstempel -- wird nur gebraucht, wenn ein Test Temperatur pruefen will."""
    daily = {"time": ziele, "precipitation_sum": kontrolle_werte}
    for i, werte in enumerate(member_werte, start=1):
        daily[f"precipitation_sum_member{i:02d}"] = werte
    antwort = {"daily": daily}
    for feld, praefix, quelle in (("temperature_2m", "temperature_2m", temp2m_stunden),
                                   ("temperature_850hPa", "temperature_850hPa", temp850_stunden)):
        if quelle is None:
            continue
        zeiten = sorted(quelle)
        hourly = antwort.setdefault("hourly", {"time": zeiten})
        hourly[praefix] = [quelle[t][0] for t in zeiten]
        n_mitglieder = len(next(iter(quelle.values()))) - 1
        for i in range(1, n_mitglieder + 1):
            hourly[f"{praefix}_member{i:02d}"] = [quelle[t][i] for t in zeiten]
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
    ens_antwort = _ensemble_antwort(ziele, member_werte, kontrolle)

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
            return {"daily": {"time": ziele, "precipitation_sum": [0.4, 0.4, 0.4, 0.4]}}
        return None

    monkeypatch.setattr(sv, "hole", hole)
    fehler = []
    lauf, hinweise = sv.verarbeite_modell("gfs", cfg, fehler, heute)
    assert lauf is not None
    assert lauf["vollstaendig"] is True
    assert lauf["mitglieder_n"] == 30
    # korrekt akkumuliert: 1 mm/Tag -> [1,2,3]
    assert lauf["mitglieder_kumulativ"][0] == [1.0, 2.0, 3.0]
    assert lauf["mittel_kumulativ"] == [1.0, 2.0, 3.0]
    assert lauf["kontrolllauf_kumulativ"] == [0.5, 1.0, 1.5]
    # deterministischer Hauptlauf mit exakt passender Initialisierung wurde uebernommen
    assert lauf["hauptlauf_kumulativ"] == [0.4, 0.8, 1.2]


def test_verarbeite_modell_verwirft_hauptlauf_bei_nicht_passender_initialisierung(monkeypatch):
    heute = dt.date(2026, 9, 17)
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    hl_init_anders = dt.datetime(2026, 9, 17, 6, tzinfo=dt.timezone.utc)  # neuerer Hauptlauf als das Ensemble
    cfg = dict(sv.MODELLE["gfs"])
    cfg["horizont"] = 2
    ziele = ["2026-09-17", "2026-09-18", "2026-09-19"]
    member_werte = [[1.0, 1.0, 1.0] for _ in range(30)]
    ens_antwort = _ensemble_antwort(ziele, member_werte, [0.5, 0.5, 0.5])

    def hole(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
        if cfg["meta_ensemble"] in url:
            return _meta(init, init + dt.timedelta(hours=6))
        if cfg["meta_hauptlauf"] in url:
            return _meta(hl_init_anders, hl_init_anders + dt.timedelta(hours=1))
        if "ensemble-api" in url:
            return ens_antwort
        return None  # /v1/forecast darf hier gar nicht erst aufgerufen werden muessen

    monkeypatch.setattr(sv, "hole", hole)
    fehler = []
    lauf, hinweise = sv.verarbeite_modell("gfs", cfg, fehler, heute)
    assert lauf is not None
    assert lauf["hauptlauf_kumulativ"] is None
    assert any("passt nicht zum Ensemble-Lauf" in h for h in hinweise)


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
            return None
        if "ensemble-api" in url:
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
    serie = {"2026-01-01T00:00": 5.0, "2026-01-01T02:00": 7.0}  # 01:00 fehlt
    zeiten = ["2026-01-01T00:00", "2026-01-01T01:00", "2026-01-01T02:00", "2026-01-01T03:00"]
    out = sv.stundenreihe(serie, zeiten)
    assert out == [5.0, None, 7.0, None]  # 02:00 ist trotz Luecke bei 01:00 intakt


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
    """End-to-End (mit gefakter API-Antwort): die Temperatur wird als volle
    stuendliche Reihe uebernommen -- nicht auf einen Wert pro Tag verdichtet
    und nicht akkumuliert."""
    heute = dt.date(2026, 9, 17)
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    cfg = dict(sv.MODELLE["gfs"])
    cfg["horizont"] = 2
    ziele = ["2026-09-17", "2026-09-18", "2026-09-19"]

    member_werte_regen = [[1.0, 1.0, 1.0] for _ in range(30)]
    # Temperatur: mehrere Stunden PRO TAG, mit Tagesgang und negativen Werten
    temp2m_stunden = {}
    for tag, basis in (("2026-09-18", -3.0), ("2026-09-19", 8.0)):
        for stunde, delta in ((0, 0.0), (6, 1.5), (12, 5.0), (18, 2.0)):
            temp2m_stunden[f"{tag}T{stunde:02d}:00"] = [basis + delta] + [basis + delta + i * 0.1 for i in range(30)]
    # ein Tag ausserhalb des Vorhersagefensters -- darf NICHT mitgenommen werden
    temp2m_stunden["2026-09-17T12:00"] = [99.0] + [99.0] * 30
    ens_antwort = _ensemble_antwort(ziele, member_werte_regen, [0.5, 0.5, 0.5], temp2m_stunden=temp2m_stunden)

    def hole(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
        if cfg["meta_ensemble"] in url:
            return _meta(init, init + dt.timedelta(hours=6))
        if cfg["meta_hauptlauf"] in url:
            return None
        if "ensemble-api" in url:
            return ens_antwort
        return None

    monkeypatch.setattr(sv, "hole", hole)
    fehler = []
    lauf, hinweise = sv.verarbeite_modell("gfs", cfg, fehler, heute)
    assert lauf is not None
    t2 = lauf["temperatur_2m"]
    assert t2 is not None
    # 2 Vorhersagetage x 4 Zeitschritte = 8 Punkte; der Tag ausserhalb des
    # Fensters (09-17) ist NICHT dabei
    assert t2["zeiten"] == [
        "2026-09-18T00:00", "2026-09-18T06:00", "2026-09-18T12:00", "2026-09-18T18:00",
        "2026-09-19T00:00", "2026-09-19T06:00", "2026-09-19T12:00", "2026-09-19T18:00",
    ]
    assert len(t2["kontrolllauf"]) == 8
    assert len(t2["mittel"]) == 8
    # Tagesgang innerhalb eines Tages sichtbar (12 Uhr waermer als 0 Uhr)
    assert t2["kontrolllauf"][2] > t2["kontrolllauf"][0]
    # negative Werte korrekt uebernommen, nicht akkumuliert
    assert t2["kontrolllauf"][0] == -3.0
    assert t2["n"] == [30] * 8
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
    monkeypatch.setattr(sv, "verarbeite_modell", lambda kurz, cfg, fehler, heute: (unvollstaendiger_lauf, ["zu wenige Mitglieder"]))
    monkeypatch.setattr(sv, "laufinfo", lambda datensatz, fehler: None)  # Vorab-Check findet nichts -> faellt durch zu verarbeite_modell

    import sys as _sys
    monkeypatch.setattr(_sys, "argv", ["sammeln_vorhersage.py", "--modell", "gfs"])
    sv.main()

    erwartete_datei = tmp_path / sv.dateiname("gfs", init)
    assert not erwartete_datei.exists(), "unvollstaendiger Lauf wurde faelschlich gespeichert"


def test_main_speichert_vollstaendigen_lauf(monkeypatch, tmp_path):
    heute = dt.date(2026, 9, 17)
    init = dt.datetime(2026, 9, 17, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(sv, "OUT", tmp_path)

    vollstaendiger_lauf = {
        "modell": "gfs", "modellname": "GFS", "init": init.strftime("%Y-%m-%dT%H:%MZ"),
        "mitglieder_n": 30, "vollstaendig": True, "hinweise": [],
        "hauptlauf_kumulativ": None, "temperatur_2m": None, "temperatur_850hpa": None,
        "horizont_tage": 16,
    }
    monkeypatch.setattr(sv, "verarbeite_modell", lambda kurz, cfg, fehler, heute: (vollstaendiger_lauf, []))
    monkeypatch.setattr(sv, "laufinfo", lambda datensatz, fehler: None)

    import sys as _sys
    monkeypatch.setattr(_sys, "argv", ["sammeln_vorhersage.py", "--modell", "gfs"])
    sv.main()

    erwartete_datei = tmp_path / sv.dateiname("gfs", init)
    assert erwartete_datei.exists(), "vollstaendiger Lauf wurde nicht gespeichert"


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
