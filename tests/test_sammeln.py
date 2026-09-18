import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skripte"))


def _messdatei_merge_simulieren(tmp_path, vorhandene_tage, neue_tage):
    """Reproduziert exakt die in sammeln.py verwendete Merge-Logik (siehe
    main(), Abschnitt 'Messwerte'), ohne das ganze Skript mit Netzwerkabruf
    ausfuehren zu muessen."""
    from gemeinsam import atomar_schreiben_json

    pfad = tmp_path / "messungen_2025-03.json"
    if vorhandene_tage is not None:
        atomar_schreiben_json(pfad, {"monat": "2025-03", "station": "03366", "tage": vorhandene_tage})

    bestehende = {}
    if pfad.exists():
        bestehende = json.loads(pfad.read_text(encoding="utf-8")).get("tage", {})
    zusammengefuehrt = dict(bestehende)
    zusammengefuehrt.update(neue_tage)
    if zusammengefuehrt != bestehende:
        atomar_schreiben_json(pfad, {"monat": "2025-03", "station": "03366", "tage": dict(sorted(zusammengefuehrt.items()))})
    return json.loads(pfad.read_text(encoding="utf-8"))["tage"]


def test_dwd_merge_behaelt_tage_ausserhalb_des_rollierenden_fensters(tmp_path):
    """Regressionstest fuer den gefundenen Bug: das DWD-'akt'-Archiv deckt nur
    ein rollierendes Zeitfenster ab (z.B. ab dem 17. eines Monats). Ein neuer
    Abruf, der nur Tage AB dem 17. liefert, darf die bereits gespeicherten
    Tage 1.-16. NICHT loeschen."""
    vorhandene = {"2025-03-01": 1.1, "2025-03-02": 0.0, "2025-03-17": 2.0}
    neue = {"2025-03-17": 2.2, "2025-03-18": 0.0}  # korrigierter Wert fuer den 17., neuer Tag 18., aber KEINE Tage 1-16
    ergebnis = _messdatei_merge_simulieren(tmp_path, vorhandene, neue)
    assert ergebnis["2025-03-01"] == 1.1  # erhalten
    assert ergebnis["2025-03-02"] == 0.0  # erhalten
    assert ergebnis["2025-03-17"] == 2.2  # korrigierter Wert hat sich durchgesetzt
    assert ergebnis["2025-03-18"] == 0.0  # neuer Tag ergaenzt


def test_dwd_merge_legt_neue_datei_an_wenn_keine_vorhanden(tmp_path):
    ergebnis = _messdatei_merge_simulieren(tmp_path, None, {"2025-03-05": 3.3})
    assert ergebnis == {"2025-03-05": 3.3}


# ---------------------------------------------------------------- main(): Fehlerbehandlung bei Totalausfall
import datetime as dt

import pytest
import sammeln


@pytest.fixture(autouse=True)
def _sammeln_zuruecksetzen(monkeypatch, tmp_path):
    """Isoliert jeden Test: eigenes daten/-Verzeichnis, leere Fehlerliste,
    kein echter Netzwerkzugriff, kein Warten beim Backoff."""
    monkeypatch.setattr(sammeln, "OUT", tmp_path)
    sammeln.fehler.clear()
    monkeypatch.setattr(sammeln.time, "sleep", lambda s: None)
    yield
    sammeln.fehler.clear()


def _totalausfall(monkeypatch):
    def kaputt(*a, **kw):
        raise sammeln.requests.exceptions.ConnectionError("simulierter Totalausfall")
    monkeypatch.setattr(sammeln.requests, "get", kaputt)


def test_main_totalausfall_beendet_sich_mit_fehlercode(monkeypatch):
    _totalausfall(monkeypatch)
    monkeypatch.setattr(sammeln.sys, "argv", ["sammeln.py", "--alles"])
    with pytest.raises(SystemExit) as exc:
        sammeln.main()
    assert exc.value.code != 0


def test_main_totalausfall_ueberschreibt_vorhandene_gueltige_daten_nicht(monkeypatch, tmp_path):
    heute = dt.date.today()
    zieldatei = tmp_path / f"forecasts_{heute.isoformat()}.json"
    gueltig = {
        "lauf": heute.isoformat(), "abgerufen": "vorher", "erfasste_modelle": ["gfs", "ecmwf"],
        "ensemble_n": {"gfs": 31, "ecmwf": 51},
        "modelllaeufe": {"gfs/hl": {"lauf": f"{heute.isoformat()}T00:00Z", "verfuegbar_seit": "x"}},
        "lauf_wie_erwartet": True, "laufhinweise": [],
        "leads": [{
            "lead": 1, "ziel": (heute + dt.timedelta(days=1)).isoformat(),
            "gfs": {"hl": 5.5, "ens": 4.4, "p10": 1.0, "p90": 9.0, "min": 0.0, "max": 12.0, "p_ueber5": 0.3},
            "ecmwf": {"hl": 6.6, "ens": 5.5, "p10": 2.0, "p90": 10.0, "min": 0.0, "max": 13.0, "p_ueber5": 0.4},
        }],
    }
    zieldatei.write_text(json.dumps(gueltig), encoding="utf-8")

    _totalausfall(monkeypatch)
    monkeypatch.setattr(sammeln.sys, "argv", ["sammeln.py", "--alles"])
    with pytest.raises(SystemExit):
        sammeln.main()

    nachher = json.loads(zieldatei.read_text(encoding="utf-8"))
    assert nachher["leads"][0]["gfs"]["hl"] == 5.5
    assert nachher["leads"][0]["ecmwf"]["hl"] == 6.6
    assert nachher["ensemble_n"] == {"gfs": 31, "ecmwf": 51}


def test_main_totalausfall_markiert_modell_nicht_als_erfasst_ohne_vorherigen_erfolg(monkeypatch, tmp_path):
    """Kein vorhandener Tageseintrag, alles schlaegt fehl: 'erfasste_modelle'
    darf dann leer sein, nicht ['gfs', 'ecmwf']."""
    heute = dt.date.today()
    zieldatei = tmp_path / f"forecasts_{heute.isoformat()}.json"
    assert not zieldatei.exists()

    _totalausfall(monkeypatch)
    monkeypatch.setattr(sammeln.sys, "argv", ["sammeln.py", "--alles"])
    with pytest.raises(SystemExit):
        sammeln.main()

    nachher = json.loads(zieldatei.read_text(encoding="utf-8"))
    assert nachher["erfasste_modelle"] == []
    assert nachher["leads"][0]["gfs"]["hl"] is None
    assert nachher["ensemble_n"] == {}


def test_main_erfolg_setzt_keinen_fehlercode(monkeypatch, tmp_path):
    """Gegenprobe: erfolgreiche Abrufe duerfen den Fehlerpfad nicht ausloesen."""
    heute = dt.date.today()

    class Antwort:
        def raise_for_status(self):
            pass

        def json(self):
            return {"daily": {"time": [(heute + dt.timedelta(days=i)).isoformat() for i in range(0, 16)],
                               "precipitation_sum": [1.0] * 16}}

    monkeypatch.setattr(sammeln.requests, "get", lambda *a, **k: Antwort())
    monkeypatch.setattr(sammeln.sys, "argv", ["sammeln.py", "--modell", "gfs"])
    sammeln.main()  # darf NICHT mit SystemExit abbrechen
    zieldatei = tmp_path / f"forecasts_{heute.isoformat()}.json"
    nachher = json.loads(zieldatei.read_text(encoding="utf-8"))
    assert nachher["erfasste_modelle"] == ["gfs"]
    assert nachher["leads"][0]["gfs"]["hl"] == 1.0


# ---------------------------------------------------------------- Perzentil-Ensemble-Aggregation (bestehende Logik in sammeln.py)
def test_ensemble_perzentil_und_schwelle_konsistent():
    import statistics
    from gemeinsam import perzentil

    werte = sorted([0.0, 0.0, 2.0, 6.0, 10.0])
    n = len(werte)
    p_ueber5 = sum(1 for x in werte if x >= 5.0) / n
    assert p_ueber5 == 0.4
    assert perzentil(werte, 0.5) == 2.0
    assert abs(statistics.fmean(werte) - 3.6) < 1e-9

