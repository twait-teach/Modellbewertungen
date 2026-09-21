"""Handy-Fassung "WoazeWeather": Bau, Trennung von der normalen Seite, App-Dateien.

Schnelle Tests ohne Browser. Die Browsertests stehen in test_handy_browser.py.
"""
import json
import struct
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "skripte"))
import bauen  # noqa: E402

DOCS = WURZEL / "docs"


@pytest.fixture
def gebaut(tmp_path, monkeypatch):
    """Baut die Seite in einen Wegwerf-Ordner (nie ins echte docs/)."""
    daten, docs = tmp_path / "daten", tmp_path / "docs"
    (daten / "vorhersage").mkdir(parents=True)
    (daten / "forecasts_2026-09-19.json").write_text(json.dumps(
        {"lauf": "2026-09-19", "abgerufen": "2026-09-19T20:54+02:00", "leads": []}), encoding="utf-8")
    monkeypatch.setattr(bauen, "DATEN", daten)
    monkeypatch.setattr(bauen, "START_ZIEL", docs / "index.html")
    monkeypatch.setattr(bauen, "ZIEL", docs / "app.html")
    monkeypatch.setattr(bauen, "DATEN_ZIEL", docs / "daten.js")
    bauen.main()
    return docs


def test_bau_schreibt_beide_handy_dateien_neben_app_html(gebaut):
    assert (gebaut / "handy.html").is_file() and (gebaut / "handy-app.html").is_file()


def test_normale_seite_kennt_die_handy_fassung_nicht(gebaut):
    app = (gebaut / "app.html").read_text(encoding="utf-8")
    index = (gebaut / "index.html").read_text(encoding="utf-8")
    for spur in ("WW_ZOOM", "WW_NEU", 'class="handy"', "body.handy", "WoazeWeather", "manifest"):
        assert spur not in app, spur
        assert spur not in index, spur
    assert "<title>Vorhersage und Analyse Mühldorf</title>" in app


def test_handy_fassung_enthaelt_alles_noetige(gebaut):
    h = (gebaut / "handy-app.html").read_text(encoding="utf-8")
    assert '<body class="handy">' in h
    assert h.count("window.WW_ZOOM = {") == 1                       # Zoom-Skript einmal eingebettet
    assert h.count("if (window.WW_ZOOM) o = window.WW_ZOOM.anwenden(ziel, o);") == 1   # Verbindung in diagramm()
    assert h.count("window.WW_NEU = () => zeichnen();") == 1
    assert "body.handy nav.hauptnav" in h                            # Stylesheet
    assert '<link rel="manifest" href="handy/manifest.webmanifest">' in h
    assert "viewport-fit=cover" in h and 'content="noindex"' in h
    assert "<title>WoazeWeather</title>" in h


def test_handy_fassung_ist_sonst_die_normale_seite(gebaut):
    """Ohne die eingesetzten Teile ist die Handy-Fassung die normale Seite, Wort fuer Wort."""
    app = (gebaut / "app.html").read_text(encoding="utf-8")
    h = (gebaut / "handy-app.html").read_text(encoding="utf-8")
    css, js = bauen.HANDY_CSS.read_text(encoding="utf-8"), bauen.HANDY_JS.read_text(encoding="utf-8")
    zurueck = (h.replace(bauen.HANDY_KOPF, '<meta name="viewport" content="width=device-width,initial-scale=1">')
                .replace('content="noindex"', 'content="index,follow"')
                .replace("<title>WoazeWeather</title>", "<title>Vorhersage und Analyse Mühldorf</title>")
                .replace("</style>\n<style>\n" + css + "</style>\n</head>\n<body class=\"handy\">\n<script>\n" + js + "</script>\n",
                         "</style>\n</head>\n<body>\n")
                .replace(bauen.HANDY_EINSATZ, bauen.HANDY_ANKER))
    assert zurueck == app


def test_lader_startet_ohne_hash_mit_station_heute(gebaut):
    lader = (gebaut / "handy.html").read_text(encoding="utf-8")
    assert "handy-app.html?v=' + Date.now() + (location.hash || '#station-heute')" in lader
    assert 'rel="manifest"' in lader


def test_wiederholter_bau_ist_bytegleich(gebaut):
    vorher = {n: (gebaut / n).read_bytes() for n in ("handy.html", "handy-app.html", "app.html")}
    bauen.main()
    assert vorher == {n: (gebaut / n).read_bytes() for n in vorher}


@pytest.mark.parametrize("fehlt", [bauen.HANDY_ANKER, "<title>Vorhersage und Analyse Mühldorf</title>",
                                   '<meta name="viewport" content="width=device-width,initial-scale=1">'])
def test_bau_bricht_ab_wenn_eine_stelle_fehlt_oder_doppelt_ist(fehlt):
    seite = ('<meta name="viewport" content="width=device-width,initial-scale=1">\n'
             '<meta name="robots" content="index,follow">\n<title>Vorhersage und Analyse Mühldorf</title>\n'
             '</style>\n</head>\n<body>\n' + bauen.HANDY_ANKER + "\n")
    bauen.handy_seite(seite, "", "")                               # vollstaendig: geht
    with pytest.raises(SystemExit):
        bauen.handy_seite(seite.replace(fehlt, "", 1), "", "")     # Stelle fehlt
    with pytest.raises(SystemExit):
        bauen.handy_seite(seite + fehlt, "", "")                   # Stelle doppelt


def test_handy_js_darf_die_seite_nicht_beenden():
    with pytest.raises(SystemExit):
        bauen.handy_seite("x", "", "var a = '</script>';")


def _png_groesse(pfad):
    kopf = pfad.read_bytes()[:24]
    assert kopf[:8] == b"\x89PNG\r\n\x1a\n", pfad
    return struct.unpack(">II", kopf[16:24])


def test_manifest_verweist_auf_vorhandene_dateien():
    ordner = DOCS / "handy"
    m = json.loads((ordner / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["name"] == "WoazeWeather" and m["display"] == "standalone"
    assert (ordner / m["start_url"]).resolve() == (DOCS / "handy.html").resolve()
    assert (ordner / m["scope"]).resolve() == DOCS.resolve()
    zwecke = set()
    for i in m["icons"]:
        breite, hoehe = _png_groesse(ordner / i["src"])
        assert f"{breite}x{hoehe}" == i["sizes"], i
        zwecke.add(i["purpose"])
    assert zwecke == {"any", "maskable"}
    assert any(i["sizes"] == "192x192" for i in m["icons"]) and any(i["sizes"] == "512x512" for i in m["icons"])


def test_dienst_speichert_nichts_zwischen():
    """Der Dienst darf keine Wetterdaten festhalten (sonst zeigt die App veraltete Werte)."""
    sw = (DOCS / "handy-sw.js").read_text(encoding="utf-8")
    assert "caches" not in sw and "fetch(event.request)" in sw


def test_eingecheckte_handy_dateien_entsprechen_dem_bau(gebaut):
    """docs/handy*.html im Repo sind exakt das, was bauen.py aus der Vorlage macht."""
    for n in ("handy.html", "handy-app.html"):
        assert (DOCS / n).read_bytes() == (gebaut / n).read_bytes(), n
