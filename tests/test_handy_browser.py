"""Browsertests der Handy-Fassung "WoazeWeather" (Playwright + Chromium).

Prueft an einem Handy-Bildschirm (390 px, Touch): Start auf "Station heute", schlanke Ansicht,
untere Leiste, Zwei-Finger-Zoom mit echten Touch-Ereignissen (Chromium-Fernsteuerung), Zuruecksetzen
und dass die normale Seite (app.html) davon nichts abbekommt. Testdaten sind rein synthetisch.
"""
import datetime as dt
import json
import math
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("playwright.sync_api", reason="Browsertests brauchen Playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "skripte"))
import bauen  # noqa: E402

ZONE = ZoneInfo("Europe/Berlin")
LETZTE = int(dt.datetime(2026, 9, 20, 12, 0, tzinfo=ZONE).timestamp())          # "jetzt" der Testdaten
MITTERNACHT = int(dt.datetime(2026, 9, 20, 0, 0, tzinfo=ZONE).timestamp())


def _stationsdaten(docs):
    aussen = [[ts, round(14 + 8 * math.sin((ts - MITTERNACHT) / 86400 * 2 * math.pi - 1.6), 1), 70.0]
              for ts in range(MITTERNACHT - 86400, LETZTE + 1, 300)]
    regen = [[ts, 0.4 if 39000 < ts - MITTERNACHT < 42000 else 0.0] for ts in range(MITTERNACHT - 86400, LETZTE + 1, 300)]
    heute = {"ort": "Stefanskirchen", "letzte_aktualisierung": "2026-09-20T10:02:00Z", "letzte_messung": LETZTE,
             "aussen": aussen, "regen": regen, "regen_vorhanden": True, "monate": ["2026-09"],
             "erste_messung": MITTERNACHT - 7 * 86400, "erste_regen": MITTERNACHT - 7 * 86400,
             "rueckfuellung_fertig": True, "normal": None}
    (docs / "station").mkdir(parents=True, exist_ok=True)
    (docs / "station" / "heute.js").write_text("window.STATION_HEUTE=" + json.dumps(heute) + ";\n", encoding="utf-8")
    start = MITTERNACHT - 7 * 86400
    stunden = [[ts, round(15 + 6 * math.sin(ts / 13000), 1), 9.0, 22.0, 70, 0.1, 12]
               for ts in range(start, LETZTE, 3600)]
    (docs / "station" / "verlauf_2026-09.js").write_text(
        'window.STATION_VERLAUF=window.STATION_VERLAUF||{};window.STATION_VERLAUF["2026-09"]='
        + json.dumps({"monat": "2026-09", "stunden": stunden}) + ";\n", encoding="utf-8")


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    wurzel = tmp_path_factory.mktemp("handy")
    daten, docs = wurzel / "daten", wurzel / "docs"
    (daten / "vorhersage").mkdir(parents=True)
    (daten / "forecasts_2026-09-19.json").write_text(json.dumps(
        {"lauf": "2026-09-19", "abgerufen": "2026-09-19T20:54+02:00", "leads": []}), encoding="utf-8")
    mp = pytest.MonkeyPatch()
    mp.setattr(bauen, "DATEN", daten)
    mp.setattr(bauen, "START_ZIEL", docs / "index.html")
    mp.setattr(bauen, "ZIEL", docs / "app.html")
    mp.setattr(bauen, "DATEN_ZIEL", docs / "daten.js")
    bauen.main()
    mp.undo()
    _stationsdaten(docs)
    return docs


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _handy(browser, url, breite=390, warten="#st-plotHeuteTemp svg"):
    ctx = browser.new_context(viewport={"width": breite, "height": 844}, is_mobile=True, has_touch=True,
                              locale="de-DE", timezone_id="Europe/Berlin")
    seite = ctx.new_page()
    fehler = []
    seite.on("pageerror", lambda e: fehler.append(str(e)))
    seite.goto(url)
    seite.wait_for_selector(warten, timeout=8000)
    return ctx, seite, fehler


def _beschriftungen(seite, box):
    return seite.evaluate("s => [...document.querySelectorAll(s + ' svg text.ax')].map(t => t.textContent)", box)


class _Finger:
    def __init__(self, ctx, seite):
        self.cdp = ctx.new_cdp_session(seite)

    def sende(self, art, punkte):
        self.cdp.send("Input.dispatchTouchEvent", {"type": art, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(punkte)]})

    def spreizen(self, seite, cx, cy, von=20, bis=200, schritte=10):
        self.sende("touchStart", [(cx - von, cy), (cx + von, cy)])
        for k in range(1, schritte + 1):
            d = von + (bis - von) * k / schritte
            self.sende("touchMove", [(cx - d, cy), (cx + d, cy)])
            seite.wait_for_timeout(25)
        self.sende("touchEnd", [])
        seite.wait_for_timeout(300)

    def doppeltippen(self, seite, x, y):
        for _ in range(2):
            self.sende("touchStart", [(x, y)])
            seite.wait_for_timeout(40)
            self.sende("touchEnd", [])
            seite.wait_for_timeout(80)
        seite.wait_for_timeout(300)


def test_start_zeigt_station_heute_in_schlanker_ansicht(browser, docs):
    ctx, seite, fehler = _handy(browser, f"file://{docs}/handy-app.html#station-heute")
    a = seite.evaluate("""() => {
        const cs = s => getComputedStyle(document.querySelector(s));
        const links = [...document.querySelectorAll('#hauptnav a')].sort((p, q) => p.getBoundingClientRect().left - q.getBoundingClientRect().left);
        return { seite: document.body.dataset.seite, nav: cs('#hauptnav').position, kopfzone: cs('#kopfzone').display,
                 reihenfolge: links.map(l => l.dataset.seite),
                 erklaerung: [...document.querySelectorAll('#seite-station-heute details')].every(d => getComputedStyle(d).display === 'none'),
                 fuss: getComputedStyle(document.querySelector('#seite-station-heute footer')).display,
                 breite: document.documentElement.scrollWidth, hoehe: document.querySelector('#st-plotHeuteTemp svg').getBoundingClientRect().height };
    }""")
    ctx.close()
    assert not fehler, fehler
    assert a["seite"] == "station-heute" and a["nav"] == "fixed" and a["kopfzone"] == "none"
    assert a["reihenfolge"] == ["station-heute", "station-verlauf", "wetter48", "vorhersage",
                                "vorhersage-analyse", "analyse"]
    assert a["erklaerung"] and a["fuss"] == "none"
    assert a["breite"] <= 390                       # nie breiter als das Handy
    assert a["hoehe"] >= 240                        # Diagramm ist in der App hoeher als am Desktop (220)


def test_normale_seite_bleibt_unveraendert(browser, docs):
    ctx, seite, fehler = _handy(browser, f"file://{docs}/app.html#station-heute")
    a = seite.evaluate("""() => ({ zoom: typeof window.WW_ZOOM, neu: typeof window.WW_NEU,
        nav: getComputedStyle(document.querySelector('#hauptnav')).position,
        kopfzone: getComputedStyle(document.querySelector('#kopfzone')).display,
        hoehe: document.querySelector('#st-plotHeuteTemp svg').getBoundingClientRect().height,
        knopf: document.querySelectorAll('.ww-zurueck').length, hinweis: document.querySelectorAll('.ww-hinweis').length })""")
    ctx.close()
    assert not fehler, fehler
    assert a["zoom"] == "undefined" and a["neu"] == "undefined"
    assert a["nav"] != "fixed" and a["kopfzone"] != "none"
    assert a["knopf"] == 0 and a["hinweis"] == 0
    assert 215 <= a["hoehe"] <= 225                 # Desktop-Hoehe 220 (Handy skaliert leicht), nicht 250


def test_zwei_finger_zoom_zeitachse_hoehenachse_und_zuruecksetzen(browser, docs):
    ctx, seite, fehler = _handy(browser, f"file://{docs}/handy-app.html#station-heute")
    vorher = _beschriftungen(seite, "#st-plotHeuteTemp")
    assert "00" in vorher and "12" in vorher and "24" in vorher
    box = seite.locator("#st-plotHeuteTemp").bounding_box()
    cx, cy = box["x"] + box["width"] * 0.6, box["y"] + box["height"] / 2
    f = _Finger(ctx, seite)
    f.spreizen(seite, cx, cy)
    nachher = _beschriftungen(seite, "#st-plotHeuteTemp")
    assert any(":" in t for t in nachher), nachher                                  # Uhrzeiten mit Minuten
    assert not ({"03", "09", "21"} & set(nachher))                                  # Achse hat sich geaendert
    assert nachher != vorher
    # beide Diagramme laufen im Gleichschritt
    assert [t for t in _beschriftungen(seite, "#st-plotHeuteRegen") if ":" in t] == [t for t in nachher if ":" in t]
    assert seite.evaluate("() => !document.querySelector('#seite-station-heute .ww-zurueck').hidden")
    # ein Finger schiebt den Ausschnitt
    vor_ziehen = [t for t in _beschriftungen(seite, "#st-plotHeuteTemp") if ":" in t]
    f.sende("touchStart", [(cx, cy)])
    for k in range(1, 9):
        f.sende("touchMove", [(cx + k * 15, cy)])
        seite.wait_for_timeout(25)
    f.sende("touchEnd", [])
    seite.wait_for_timeout(300)
    assert [t for t in _beschriftungen(seite, "#st-plotHeuteTemp") if ":" in t] != vor_ziehen
    # Doppeltippen setzt zurueck
    f.doppeltippen(seite, cx, cy)
    assert _beschriftungen(seite, "#st-plotHeuteTemp") == vorher
    assert seite.evaluate("() => document.querySelector('#seite-station-heute .ww-zurueck').hidden")
    ctx.close()
    assert not fehler, fehler


def test_knopf_ganzer_zeitraum_und_wechsel_auf_gestern_setzen_zurueck(browser, docs):
    ctx, seite, fehler = _handy(browser, f"file://{docs}/handy-app.html#station-heute")
    vorher = _beschriftungen(seite, "#st-plotHeuteTemp")
    box = seite.locator("#st-plotHeuteTemp").bounding_box()
    f = _Finger(ctx, seite)
    f.spreizen(seite, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    assert _beschriftungen(seite, "#st-plotHeuteTemp") != vorher
    seite.locator("#seite-station-heute .ww-zurueck").click()
    seite.wait_for_timeout(300)
    assert _beschriftungen(seite, "#st-plotHeuteTemp") == vorher
    f.spreizen(seite, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    seite.locator("#seite-station-heute [data-tag='1']").click()          # anderer Zeitraum: Zoom faellt weg
    seite.wait_for_timeout(300)
    assert _beschriftungen(seite, "#st-plotHeuteTemp") == vorher
    assert seite.evaluate("() => document.querySelector('#seite-station-heute .ww-zurueck').hidden")
    ctx.close()
    assert not fehler, fehler


def test_wochenansicht_beschriftungen_ueberlappen_sich_nicht(browser, docs):
    ctx, seite, fehler = _handy(browser, f"file://{docs}/handy-app.html#station-verlauf",
                                warten="#st-plotVerlaufTemp svg text.ax")
    texte = [t for t in _beschriftungen(seite, "#st-plotVerlaufTemp") if t and t != "°C" and not t.lstrip("−").isdigit()]
    ctx.close()
    assert not fehler, fehler
    assert 2 <= len(texte) <= 5, texte              # sieben Tage wuerden bei 390 px ineinanderlaufen


def test_andere_diagramme_werden_beim_pinch_breiter_und_setzen_zurueck(browser, docs):
    ctx, seite, fehler = _handy(browser, f"file://{docs}/handy-app.html#station-heute")
    # Ein Diagramm aus der Analyse-Seite: ohne Daten leer, aber der Rahmen genuegt fuer die Geste
    seite.evaluate("() => { location.hash = '#analyse'; }")
    seite.wait_for_timeout(300)
    svg = "#seite-analyse .plot svg"
    seite.evaluate("s => document.querySelector(s).scrollIntoView({block: 'center'})", svg)
    seite.wait_for_timeout(200)
    b0 = seite.evaluate("s => document.querySelector(s).getBoundingClientRect().width", svg)
    box = seite.locator("#seite-analyse .plot").first.bounding_box()
    cx, cy = 195, box["y"] + box["height"] / 2
    f = _Finger(ctx, seite)
    f.spreizen(seite, cx, cy, bis=120)
    b1 = seite.evaluate("s => document.querySelector(s).getBoundingClientRect().width", svg)
    assert b1 > b0 * 1.5
    assert seite.evaluate("() => document.documentElement.scrollWidth") <= 390          # Seite selbst wird nicht breiter
    f.doppeltippen(seite, cx, cy)
    assert abs(seite.evaluate("s => document.querySelector(s).getBoundingClientRect().width", svg) - b0) < 2
    ctx.close()
    assert not fehler, fehler


def test_temperaturachse_der_station_reicht_genau_vom_tiefst_zum_hoechstwert(browser, docs):
    """Keine Stauchung durch Aufrunden: Die Kurve beruehrt oben und unten den Diagrammrand,
    beschriftet sind nur runde Werte innerhalb des Bereichs."""
    ctx = browser.new_context(viewport={"width": 1200, "height": 900}, locale="de-DE", timezone_id="Europe/Berlin")
    seite = ctx.new_page()
    seite.goto(f"file://{docs / 'app.html'}#station-heute")
    seite.wait_for_selector("#st-plotHeuteTemp svg path", timeout=8000)
    r = seite.evaluate("""() => { const s = document.querySelector('#st-plotHeuteTemp svg');
        const pfad = [...s.querySelectorAll('path')].find(p => p.getAttribute('stroke') === 'var(--temp)');
        const ys = pfad.getAttribute('d').match(/-?[0-9.]+,-?[0-9.]+/g).map(p => +p.split(',')[1]);
        const gitter = [...s.querySelectorAll('line')].filter(l => l.getAttribute('x1') !== l.getAttribute('x2')).map(l => +l.getAttribute('y1'));
        const marken = [...s.querySelectorAll('text.ax')].filter(t => t.getAttribute('text-anchor') === 'end' && t.textContent !== '°C').map(t => t.textContent);
        return { oben: Math.min(...ys), unten: Math.max(...ys), achseUnten: Math.max(...gitter), T: 22, marken }; }""")
    ctx.close()
    assert abs(r["oben"] - r["T"]) < 0.6 and abs(r["unten"] - r["achseUnten"]) < 0.6
    assert len(r["marken"]) >= 3 and all("," not in m for m in r["marken"])     # ganze, runde Werte
