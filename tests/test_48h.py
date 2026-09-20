"""Reiter "48h Wetter": Sammler, Einbettung in die Seite und Darstellung.

Ohne Netz: Der Abruf wird durch eine Funktion ersetzt, die feste Antworten liefert.
Der Browsertest wird ohne Playwright uebersprungen (z. B. im schnellen Daten-Workflow).
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skripte"))
import bauen  # noqa: E402
import sammeln_48h as s48  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
UTC = dt.timezone.utc
START = int(dt.datetime(2026, 9, 21, 0, tzinfo=UTC).timestamp())
STUNDEN = [START + i * 3600 for i in range(49)]


def _antwort(n=49, fehlend=None):
    reihen = {
        "time": STUNDEN[:n],
        "temperature_2m": [round(12 + 6 * (i % 24) / 24, 1) for i in range(n)],
        "precipitation": [0.0 if i % 6 else 0.4 for i in range(n)],
        "weather_code": [3 if i % 6 else 61 for i in range(n)],
        "is_day": [1 if 6 <= (i % 24) < 19 else 0 for i in range(n)],
    }
    for f in fehlend or []:
        reihen.pop(f)
    return {"hourly": reihen}


def _hole(antwort):
    def hole_(url, params=None, fehlerliste=None, **kw):
        assert "forecast" in url and params["models"]
        return antwort
    return hole_


# ------------------------------------------------------------------ Sammler

def test_abruf_liefert_alle_vier_reihen():
    d = s48.abrufen("gfs", [], hole_=_hole(_antwort()))
    assert d["modell"] == "gfs" and d["modellname"] == "GFS"
    assert len(d["zeitpunkte_unix"]) == 49
    for feld in ("temperatur_2m", "niederschlag", "wettercode", "tag"):
        assert len(d[feld]) == 49
    assert d["wettercode"][0] == 61 and d["tag"][0] == 0


@pytest.mark.parametrize("kaputt", [{"fehlend": ["weather_code"]}, {"n": 0}])
def test_unbrauchbare_antwort_gibt_nichts_zurueck(kaputt):
    assert s48.abrufen("ecmwf", [], hole_=_hole(_antwort(**kaputt))) is None


def test_ohne_antwort_bleibt_der_bisherige_stand(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(s48, "OUT", tmp_path)
    assert s48.main(["--modell", "gfs"], hole_=lambda *a, **k: None) == 0
    assert not list(tmp_path.glob("*.json"))
    assert "bisheriger Stand bleibt" in capsys.readouterr().out


def test_gleiche_werte_erzeugen_keine_neue_datei(tmp_path, monkeypatch):
    monkeypatch.setattr(s48, "OUT", tmp_path)
    assert s48.main(["--modell", "gfs"], hole_=_hole(_antwort())) == 0
    pfad = tmp_path / "gfs.json"
    vorher = pfad.read_bytes()
    assert s48.main(["--modell", "gfs"], hole_=_hole(_antwort())) == 0
    assert pfad.read_bytes() == vorher, "nur der Abrufzeitpunkt aendert sich — kein neuer Commit"
    geaendert = _antwort()
    geaendert["hourly"]["temperature_2m"][5] = 99.9
    assert s48.main(["--modell", "gfs"], hole_=_hole(geaendert)) == 0
    assert pfad.read_bytes() != vorher


# ------------------------------------------------------------------ Einbettung

@pytest.fixture
def gebaut(tmp_path, monkeypatch):
    daten, docs = tmp_path / "daten", tmp_path / "docs"
    (daten / "48h").mkdir(parents=True)
    (daten / "forecasts_2026-09-21.json").write_text(json.dumps(
        {"lauf": "2026-09-21", "abgerufen": "2026-09-21T06:00+02:00", "leads": []}), encoding="utf-8")
    monkeypatch.setattr(s48, "OUT", daten / "48h")
    s48.main(["--modell", "gfs"], hole_=_hole(_antwort()))
    monkeypatch.setattr(bauen, "DATEN", daten)
    monkeypatch.setattr(bauen, "START_ZIEL", docs / "index.html")
    monkeypatch.setattr(bauen, "ZIEL", docs / "app.html")
    monkeypatch.setattr(bauen, "DATEN_ZIEL", docs / "daten.js")
    bauen.main()
    text = (docs / "daten.js").read_text(encoding="utf-8")
    return json.loads(text.split("=", 1)[1].rstrip(";\n"))


def test_stundenwerte_landen_in_der_seite(gebaut):
    w = gebaut["wetter48"]
    assert set(w) == {"gfs"}
    assert len(w["gfs"]["zeitpunkte_unix"]) == 49 and w["gfs"]["wettercode"][0] == 61


def test_fehlende_48h_daten_sind_kein_fehler(tmp_path, monkeypatch):
    daten, docs = tmp_path / "daten", tmp_path / "docs"
    daten.mkdir()
    (daten / "forecasts_2026-09-21.json").write_text(json.dumps(
        {"lauf": "2026-09-21", "abgerufen": "2026-09-21T06:00+02:00", "leads": []}), encoding="utf-8")
    monkeypatch.setattr(bauen, "DATEN", daten)
    monkeypatch.setattr(bauen, "START_ZIEL", docs / "index.html")
    monkeypatch.setattr(bauen, "ZIEL", docs / "app.html")
    monkeypatch.setattr(bauen, "DATEN_ZIEL", docs / "daten.js")
    bauen.main()
    paket = json.loads((docs / "daten.js").read_text(encoding="utf-8").split("=", 1)[1].rstrip(";\n"))
    assert paket["wetter48"] == {}


# ------------------------------------------------------------------ Darstellung

def test_reiter_und_erklaerung_stehen_in_der_vorlage():
    seite = (WURZEL / "skripte" / "vorlage.html").read_text(encoding="utf-8")
    assert '<a href="#wetter48" data-seite="wetter48">48h Wetter</a>' in seite
    assert '<main id="seite-wetter48" hidden>' in seite
    assert '"vorhersage", "wetter48"' in seite
    assert "WMO-Wettercode" in seite
