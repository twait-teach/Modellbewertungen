"""bauen.py: deterministischer Bau, Formatfilter, Loader."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skripte"))
import bauen  # noqa: E402
from gemeinsam import ist_aktuelles_format  # noqa: E402


def _reihe(modell, kontroll=True):
    return {"zeiten": ["2026-09-19T02:00", "2026-09-19T05:00"], "zeitpunkte_unix": [1789776000, 1789786800],
            "mitglieder": [[1.0, 2.0]], "kontrolllauf": [1.0, 2.0] if kontroll else None,
            "hauptlauf": None, "mittel": [1.0, 2.0], "p10": [1.0, 2.0], "p90": [1.0, 2.0], "n": [1, 1]}


def _slot(modell, init, marker=True, kontroll=True):
    d = {"modell": modell, "init": init, "abgerufen": init, "mitglieder_n": 1, "horizont_tage": 1,
         "temperatur_2m": _reihe(modell, kontroll), "temperatur_850hpa": _reihe(modell, kontroll),
         "niederschlag": _reihe(modell, kontroll)}
    if marker:
        d["zeitauflosung"] = "modellnativ-v1"
    return d


@pytest.fixture
def baustelle(tmp_path, monkeypatch):
    daten, docs = tmp_path / "daten", tmp_path / "docs"
    (daten / "vorhersage").mkdir(parents=True)
    (daten / "forecasts_2026-09-19.json").write_text(json.dumps(
        {"lauf": "2026-09-19", "abgerufen": "2026-09-19T20:54+02:00", "leads": []}), encoding="utf-8")
    vorlage = tmp_path / "vorlage.html"
    vorlage.write_text(bauen.VORLAGE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(bauen, "DATEN", daten)
    monkeypatch.setattr(bauen, "VORLAGE", vorlage)
    monkeypatch.setattr(bauen, "START_ZIEL", docs / "index.html")
    monkeypatch.setattr(bauen, "ZIEL", docs / "app.html")
    monkeypatch.setattr(bauen, "DATEN_ZIEL", docs / "daten.js")
    return daten, docs


def _dateien(docs):
    return {n: (docs / n).read_bytes() for n in ("index.html", "app.html", "daten.js")}


def test_wiederholter_bau_ohne_quelldatenaenderung_ist_bytegleich(baustelle):
    daten, docs = baustelle
    (daten / "vorhersage" / "gfs_2026-09-19T00.json").write_text(
        json.dumps(_slot("gfs", "2026-09-19T00:00Z")), encoding="utf-8")
    bauen.main()
    erster = _dateien(docs)
    bauen.main()
    assert _dateien(docs) == erster
    assert b'"gebaut"' not in erster["daten.js"]  # kein Uhrzeitfeld mehr


def test_datenstand_wird_aus_den_quelldaten_abgeleitet(baustelle):
    daten, docs = baustelle
    slot = _slot("gfs", "2026-09-19T00:00Z")
    slot["abgerufen"] = "2026-09-19T09:30Z"
    slot["hauptlauf_abgerufen"] = "2026-09-19T21:10Z"
    (daten / "vorhersage" / "gfs_2026-09-19T00.json").write_text(json.dumps(slot), encoding="utf-8")
    bauen.main()
    paket = json.loads((docs / "daten.js").read_text(encoding="utf-8")[len("window.DATEN="):].rstrip().rstrip(";"))
    # neuester Zeitpunkt: 21:10Z (Hauptlauf) gegen 18:54Z (forecasts, +02:00 umgerechnet)
    assert paket["datenstand"] == "2026-09-19T21:10Z"


def test_tatsaechlich_geaenderte_quelldaten_aendern_daten_js_aber_nicht_die_seite(baustelle):
    daten, docs = baustelle
    bauen.main()
    vorher = _dateien(docs)
    (daten / "forecasts_2026-09-19.json").write_text(json.dumps(
        {"lauf": "2026-09-19", "abgerufen": "2026-09-19T22:24+02:00", "leads": [{"lead": 1}]}), encoding="utf-8")
    bauen.main()
    nachher = _dateien(docs)
    assert nachher["daten.js"] != vorher["daten.js"]
    assert nachher["app.html"] == vorher["app.html"]
    assert nachher["index.html"] == vorher["index.html"]


def test_nur_aktuelles_format_wird_eingebettet_und_kein_altbestand_als_ersatz(baustelle):
    daten, docs = baustelle
    v = daten / "vorhersage"
    (v / "gfs_2026-09-19T00.json").write_text(json.dumps(_slot("gfs", "2026-09-19T00:00Z")), encoding="utf-8")
    (v / "gfs_2026-09-18T18.json").write_text(json.dumps(_slot("gfs", "2026-09-18T18:00Z", marker=False)), encoding="utf-8")
    (v / "gfs_2026-09-18T12.json").write_text(json.dumps({"modell": "gfs", "init": "2026-09-18T12:00Z"}), encoding="utf-8")
    (v / "ecmwf_2026-09-18T12.json").write_text(json.dumps(_slot("ecmwf", "2026-09-18T12:00Z", marker=False)), encoding="utf-8")
    bauen.main()
    paket = json.loads((docs / "daten.js").read_text(encoding="utf-8")[len("window.DATEN="):].rstrip().rstrip(";"))
    assert [d["init"] for d in paket["vorhersage"]["gfs"]] == ["2026-09-19T00:00Z"]
    assert paket["vorhersage"]["ecmwf"] == []   # kein Rueckgriff auf Alt-Dateien


@pytest.mark.parametrize("aenderung, erwartet", [
    (lambda d: None, True),
    (lambda d: d.pop("zeitauflosung"), False),
    (lambda d: d.update(zeitauflosung="modellnativ-v0"), False),
    (lambda d: d["temperatur_2m"].pop("zeiten"), False),
    (lambda d: d["niederschlag"].update(zeitpunkte_unix=[1]), False),   # Laenge passt nicht
    (lambda d: d["temperatur_850hpa"].update(mitglieder=[]), False),
    (lambda d: d["temperatur_850hpa"].update(kontrolllauf=None), False),  # GFS braucht Kontrolllauf
    (lambda d: d.update(niederschlag=None), False),
])
def test_formatpruefung_gfs(aenderung, erwartet):
    d = _slot("gfs", "2026-09-19T00:00Z")
    aenderung(d)
    assert ist_aktuelles_format(d) is erwartet
    assert bauen.meteogrammlauf_anzeigbar(d) is erwartet


def test_ecmwf_braucht_keinen_kontrolllauf():
    assert ist_aktuelles_format(_slot("ecmwf", "2026-09-19T00:00Z", kontroll=False)) is True


def test_loader_reicht_den_hash_weiter():
    assert "location.hash" in bauen.STARTSEITE
    assert "app.html?v=" in bauen.STARTSEITE
