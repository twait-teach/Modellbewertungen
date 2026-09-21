"""Browsertest des Reiters "48h Wetter" (Playwright + Chromium).

Getrennt von tests/test_48h.py, damit die schnellen Tests im Daten-Workflow ohne
Chromium laufen. Testdaten sind rein synthetisch.
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="Browsertests brauchen Playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skripte"))
import sammeln_48h as s48  # noqa: E402

from test_48h import _antwort, _hole, START  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent


def _ensemble_lauf(modell):
    unix = [START + i * 3 * 3600 for i in range(17)]
    mittel = [12 + 5 * (i % 8) / 8 for i in range(len(unix))]
    return {"modell": modell, "init": "2026-09-20T18:00Z", "abgerufen": "2026-09-20T20:00Z",
            "zeitauflosung": "modellnativ-v1", "mitglieder_n": 3, "horizont_tage": 2,
            "temperatur_2m": {"zeiten": ["x"] * len(unix), "zeitpunkte_unix": unix,
                              "mitglieder": [mittel], "kontrolllauf": mittel if modell == "gfs" else None,
                              "hauptlauf": mittel, "mittel": mittel,
                              "p10": [m - 1.5 for m in mittel], "p90": [m + 1.5 for m in mittel],
                              "n": [3] * len(unix)}}


@pytest.fixture(scope="module")
def seite48(tmp_path_factory):
    gfs = s48.abrufen("gfs", [], hole_=_hole(_antwort()))
    ecmwf = dict(s48.abrufen("ecmwf", [], hole_=_hole(_antwort())), temperatur_2m=[8.0] * 49)
    daten = {"messungen": {}, "history": {}, "forecasts": {}, "datenstand": "2026-09-20T20:00Z",
             "vorhersage": {"gfs": [_ensemble_lauf("gfs")], "ecmwf": []},
             "wetter48": {"gfs": gfs, "ecmwf": ecmwf}}
    vorlage = (WURZEL / "skripte" / "vorlage.html").read_text(encoding="utf-8")
    ersetzt = vorlage.replace("window.DATEN || /*__DATEN__*/{}", json.dumps(daten, ensure_ascii=False))
    inhalt = ('<!doctype html>\n<html lang="de"><head><meta charset="utf-8">'
              + ersetzt.split("<style>", 1)[0]
              + "<style>" + ersetzt.split("<style>", 1)[1].split("</style>", 1)[0] + "</style></head><body>"
              + ersetzt.split("</style>", 1)[1] + "</body></html>")
    pfad = tmp_path_factory.mktemp("w48") / "seite.html"
    pfad.write_text(inhalt, encoding="utf-8")
    return pfad


def test_diagramm_zeigt_kurve_balken_und_symbole(seite48):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        seite = browser.new_page(viewport={"width": 1200, "height": 900})
        fehler = []
        seite.on("pageerror", lambda e: fehler.append(str(e)))
        seite.goto(f"file://{seite48}#wetter48")
        seite.wait_for_timeout(400)
        seite.locator("#modellwahl-wetter48 button", has_text="GFS").click()
        seite.wait_for_timeout(200)
        gfs = seite.evaluate("""() => ({
            kurve: document.querySelectorAll('#plot-wetter48 .w-linie').length,
            band: document.querySelectorAll('#plot-wetter48 .w-band').length,
            balken: document.querySelectorAll('#plot-wetter48 .w-regen').length,
            symbole: document.querySelectorAll('#plot-wetter48 .wsym').length,
            nacht: document.querySelectorAll('#plot-wetter48 .w-nacht').length,
            info: document.querySelector('#laufinfoZeile-wetter48').textContent })""")
        seite.locator("#modellwahl-wetter48 button", has_text="ECMWF-IFS").click()
        seite.wait_for_timeout(200)
        ecmwf = seite.evaluate("""() => ({
            band: document.querySelectorAll('#plot-wetter48 .w-band').length,
            kurve: document.querySelectorAll('#plot-wetter48 .w-linie').length,
            warnung: document.querySelector('#laufwarnung-wetter48').textContent.trim(),
            info: document.querySelector('#laufinfoZeile-wetter48').textContent })""")
        browser.close()
    assert not fehler, fehler
    assert gfs["kurve"] == 1 and gfs["band"] == 1 and gfs["balken"] > 0 and gfs["nacht"] > 0
    assert 14 <= gfs["symbole"] <= 17, gfs["symbole"]    # 48 Stunden im 3-Stunden-Abstand
    assert "GFS" in gfs["info"] and "Ensemble vom" in gfs["info"]
    # ECMWF hat in diesen Testdaten keinen Ensemble-Lauf: Kurve ja, Band nein, Hinweis sichtbar
    assert ecmwf["kurve"] == 1 and ecmwf["band"] == 0 and "nur der Hauptlauf" in ecmwf["warnung"]
    assert "ohne Ensemble" in ecmwf["info"]


def test_kurve_ist_mittel_aus_hauptlauf_und_ensemble_und_geglaettet(seite48):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        seite = browser.new_page()
        seite.goto(f"file://{seite48}#wetter48")
        seite.wait_for_timeout(300)
        erg = seite.evaluate("""() => {
            const T = window.__TEST48__;
            const d = T.aufbereiten('gfs');
            const roh = d.stunden.map((_, i) => (d.hauptlauf[i] + d.ensembleMittel[i]) / 2);
            const zacken = r => r.slice(1, -1).reduce((s, v, i) => s + Math.abs(2 * v - r[i] - r[i + 2]), 0);
            return { geglaettet: zacken(d.linie), roh: zacken(roh),
                     mittig: d.linie.every((v, i) => v >= Math.min(...roh) - 0.01 && v <= Math.max(...roh) + 0.01),
                     glaettung: T.glaetten([0, 4, 0]), raster: T.aufStunden(null, 'mittel', [1, 2]) };
        }""")
        browser.close()
    assert erg["glaettung"] == [1, 2, 1]                 # 1-2-1-Gewichtung
    assert erg["raster"] == [None, None]                 # ohne Ensemble bleibt es leer
    assert erg["geglaettet"] < erg["roh"], "die Kurve muss ruhiger sein als die Rohwerte"
    assert erg["mittig"]


def test_naechster_hoechstwert_ist_bei_fallender_temperatur_nicht_der_wert_von_jetzt(seite48):
    """17 Uhr, Temperatur faellt: Hoechstwert ist der von morgen (06-20 Uhr), Tiefstwert der der Nacht."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    start = int(dt.datetime(2026, 9, 21, 17, 0, tzinfo=ZoneInfo("Europe/Berlin")).timestamp())
    stunden = [start + h * 3600 for h in range(48)]
    # Tagesgang mit Maximum um 15 Uhr: 17 Uhr (h=0) liegt auf dem absteigenden Ast
    import math
    linie = [round(12 + 6 * math.cos((h + 2) / 24 * 2 * math.pi), 2) for h in range(48)]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(timezone_id="Europe/Berlin")
        seite = ctx.new_page()
        seite.goto(f"file://{seite48}#wetter48")
        seite.wait_for_timeout(300)
        r = seite.evaluate("([s, l]) => window.__TEST48__.extremwerte({ stunden: s, linie: l }, s[0])", [stunden, linie])
        browser.close()
    zeit = lambda ts: dt.datetime.fromtimestamp(ts, ZoneInfo("Europe/Berlin"))
    assert r["hoch"]["v"] == max(linie[16:28]) and zeit(r["hoch"]["ts"]).day == 22 and 6 <= zeit(r["hoch"]["ts"]).hour <= 20
    assert r["hoch"]["v"] != linie[0]
    assert zeit(r["tief"]["ts"]).hour <= 10 and zeit(r["tief"]["ts"]).day == 22
