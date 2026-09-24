"""Browsertests der Vorhersageansicht (Stufe 2): Breite, einklappbare Erklaerungen,
gemeinsame Temperaturachsen, dynamische Bezugslinie, Layoutsprung beim Modellwechsel,
Tageslinien bei Ortsmitternacht (auch an Zeitumstellungen).

Die Testdaten werden mit denselben Funktionen erzeugt wie im Sammler
(``sammeln_vorhersage``), sind aber rein synthetisch.

Browsertests: brauchen Playwright + Chromium und werden ohne Playwright
uebersprungen (z. B. im schnellen Daten-Workflow, der Chromium nicht installiert).
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skripte"))
import sammeln_vorhersage as sv  # noqa: E402

VORLAGE = Path(__file__).resolve().parent.parent / "skripte" / "vorlage.html"
UTC = dt.timezone.utc
BERLIN = ZoneInfo("Europe/Berlin")
H = 3600
BEREICH_IDS = ("temp850", "niederschlag")


# ------------------------------------------------------------------ Testdaten
def _unix_raster(modell, init, horizont):
    start = int(init.timestamp())
    stundenachse = [start + i * H for i in range(horizont * 24 + 1)]
    return sv.modell_zeitfenster(stundenachse, init, horizont, modell)


def _lauf(modell, init, horizont, *, mitglieder=12, basis=12.0, amplitude=5.0, hauptlauf=True,
          hinweise=(), vollstaendig=None, verlauf=None):
    """Ein Laufdokument im Format ``modellnativ-v1``. ``verlauf(u_rel_stunden, m)`` ueberschreibt die Temperatur."""
    zeiten, unix = _unix_raster(modell, init, horizont)
    start = unix[0]

    def temperatur(u, m, versatz):
        h = (u - start) / H
        if verlauf:
            return round(verlauf(h, m) + versatz, 2)
        return round(basis + versatz + amplitude * math.sin(2 * math.pi * h / 24) + 0.15 * m + 0.02 * h, 2)

    def feld(versatz):
        mitglieder_t = [[temperatur(u, m, versatz) for u in unix] for m in range(1, mitglieder + 1)]
        kontrolle = [temperatur(u, 0, versatz) for u in unix] if modell == "gfs" else None
        haupt = [round(temperatur(u, 0, versatz) + 0.3, 2) for u in unix] if hauptlauf else None
        kennzahlen = sv.aggregiere_alle_leads(mitglieder_t, len(unix))
        return {"zeiten": zeiten, "zeitpunkte_unix": unix, "zeitzone": "Europe/Berlin",
                "kontrolllauf": kontrolle, "mitglieder": mitglieder_t, "hauptlauf": haupt, **kennzahlen}

    regen_m = [[round(0.02 * k * (1 + 0.03 * m), 2) for k in range(len(unix))] for m in range(1, mitglieder + 1)]
    kennzahlen = sv.aggregiere_alle_leads(regen_m, len(unix))
    niederschlag = {"zeiten": zeiten, "zeitpunkte_unix": unix, "zeitzone": "Europe/Berlin",
                    "kontrolllauf": regen_m[0] if modell == "gfs" else None, "mitglieder": regen_m,
                    "hauptlauf": [round(0.02 * k, 2) for k in range(len(unix))] if hauptlauf else None,
                    **kennzahlen}
    ensemble_iso = init.strftime("%Y-%m-%dT%H:%MZ")
    ist_vollstaendig = hauptlauf if vollstaendig is None else vollstaendig
    return {
        "modell": modell, "modellname": "GFS" if modell == "gfs" else "ECMWF-IFS",
        "ensemble_datensatz": "x", "init": ensemble_iso, "verfuegbar_seit": ensemble_iso,
        "abgerufen": ensemble_iso, "horizont_tage": horizont, "zeitauflosung": "modellnativ-v1",
        "mitglieder_n": mitglieder, "leads": list(range(1, horizont + 1)), "ziele": [],
        "temperatur_2m": feld(0.0), "temperatur_850hpa": feld(-8.0), "niederschlag": niederschlag,
        "ensemble_vollstaendig": True, "hauptlauf_vollstaendig": hauptlauf, "vollstaendig": ist_vollstaendig,
        "hinweise": list(hinweise),
    }


def _daten(gfs, ecmwf):
    return {"messungen": {}, "history": {}, "forecasts": {}, "datenstand": "2026-10-24T18:00Z",
            "vorhersage": {"gfs": gfs, "ecmwf": ecmwf}}


def _reichhaltige_daten():
    """Beide Modelle, mehrere Laeufe, Umstellung auf Winterzeit (25.10.2026) im Horizont.
    GFS: Kontrolllauf, zwei Laeufe ohne Hauptlauf (Statusmeldung), ein Lauf mit sehr langem Hinweis.
    ECMWF: kein Kontrolllauf."""
    lang = ("Ein bewusst sehr langer Hinweis, der auf schmalen Bildschirmen mehrere Zeilen braucht und "
            "deshalb die Hoehe des Statusbereichs bestimmt, falls diese nicht vorab reserviert wird.")
    gfs = [
        _lauf("gfs", dt.datetime(2026, 10, 24, 18, tzinfo=UTC), 16, hauptlauf=False),
        _lauf("gfs", dt.datetime(2026, 10, 24, 12, tzinfo=UTC), 16, hinweise=[lang]),
        _lauf("gfs", dt.datetime(2026, 10, 24, 6, tzinfo=UTC), 16),
        _lauf("gfs", dt.datetime(2026, 10, 24, 0, tzinfo=UTC), 16, basis=14.0),
    ]
    ecmwf = [
        _lauf("ecmwf", dt.datetime(2026, 10, 24, 12, tzinfo=UTC), 15, mitglieder=50, basis=9.0),
        _lauf("ecmwf", dt.datetime(2026, 10, 24, 0, tzinfo=UTC), 15, mitglieder=50, hauptlauf=False),
    ]
    return _daten(gfs, ecmwf)


def _seite(tmp_path, daten, name="seite.html"):
    vorlage = VORLAGE.read_text(encoding="utf-8")
    ersetzt = vorlage.replace("window.DATEN || /*__DATEN__*/{}", json.dumps(daten, ensure_ascii=False))
    seite = ('<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
             '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
             + ersetzt.split("<style>", 1)[0]
             + "<style>" + ersetzt.split("<style>", 1)[1].split("</style>", 1)[0] + "</style>\n</head>\n<body>\n"
             + ersetzt.split("</style>", 1)[1] + "\n</body>\n</html>\n")
    pfad = tmp_path / name
    pfad.write_text(seite, encoding="utf-8")
    return pfad


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def reich(tmp_path_factory):
    daten = _reichhaltige_daten()
    return {"daten": daten, "datei": _seite(tmp_path_factory.mktemp("reich"), daten)}


def _oeffnen(browser, datei, breite, hoehe=1000):
    seite = browser.new_page(viewport={"width": breite, "height": hoehe})
    seite.fehler = []
    seite.on("pageerror", lambda e: seite.fehler.append(str(e)))
    seite.goto(f"file://{datei}#vorhersage-analyse")
    seite.wait_for_timeout(300)
    return seite


def _modell(seite, bereich, name):
    seite.locator(f"#modellwahl-{bereich} button", has_text=name).click()
    seite.wait_for_timeout(60)


# ------------------------------------------------------------------ Temperaturskala
def _erwartete_skala(werte):
    lo, hi = min(werte), max(werte)
    rand = min(1.5, max(1.0, (hi - lo) * 0.05))
    unten, oben = math.floor(lo - rand), math.ceil(hi + rand)
    schritt = 1 if oben - unten <= 9 else 5
    ticks = list(range(math.ceil(unten / schritt) * schritt, oben + 1, schritt))
    return unten, oben, schritt, ticks


@pytest.mark.parametrize("werte, unten, oben, ticks", [
    ([1.7, 28.8], 0, 31, [0, 5, 10, 15, 20, 25, 30]),            # Beispiel der Anweisung
    ([10.2, 12.7], 9, 14, [9, 10, 11, 12, 13, 14]),              # enger Bereich: Schritt 1
    ([-7.3, 2.1], -9, 4, [-5, 0]),                               # negativ, Spannweite 13: Schritt 5, Grenzen keine Fuenfer
    ([-20.0, 30.0], -22, 32, [-20, -15, -10, -5, 0, 5, 10, 15, 20, 25, 30]),
])
def test_temperaturskala_beispiele(browser, reich, werte, unten, oben, ticks):
    seite = _oeffnen(browser, reich["datei"], 1366)
    skala = seite.evaluate("w => window.__TEST__.temperaturSkala(w)", werte)
    seite.close()
    assert (skala["unten"], skala["oben"]) == (unten, oben)
    assert skala["ticks"] == ticks
    assert skala["schritt"] <= 5
    assert skala["unten"] < min(werte) and skala["oben"] > max(werte)     # nichts beruehrt den Rand


def test_temperaturskala_grenzen_und_gitter_sind_getrennt(browser, reich):
    """Die Grenzen (0 und 31) sind keine Vielfachen des Gitterschritts (5)."""
    seite = _oeffnen(browser, reich["datei"], 1366)
    skala = seite.evaluate("w => window.__TEST__.temperaturSkala(w)", [1.7, 28.8])
    seite.close()
    assert skala["oben"] % skala["schritt"] != 0
    assert all(t % skala["schritt"] == 0 for t in skala["ticks"])


@pytest.mark.parametrize("bereich", ["temp850"])
def test_beide_modelle_teilen_die_achse_und_nichts_wird_abgeschnitten(browser, reich, bereich):
    d = reich["daten"]["vorhersage"]
    feld = "temperatur_850hpa"
    werte = []
    for modell in ("gfs", "ecmwf"):
        f = d[modell][0][feld]
        werte += [v for reihe in f["mitglieder"] for v in reihe]
        for name in ("kontrolllauf", "hauptlauf", "mittel", "p10", "p90"):
            werte += [v for v in (f[name] or []) if v is not None]
    unten, oben, schritt, ticks = _erwartete_skala(werte)

    seite = _oeffnen(browser, reich["datei"], 1366)
    def achse():
        return seite.evaluate("""b => { const s = document.querySelector('#chart-' + b);
            return {unten: +s.dataset.unten, oben: +s.dataset.oben,
                    labels: [...s.querySelectorAll('text.ax')].filter(t => t.getAttribute('text-anchor') === 'end').map(t => t.textContent),
                    ausserhalb: [...s.querySelectorAll('path')].filter(p => { const r = p.getBBox(); return r.y < 0 || r.y + r.height > s.viewBox.baseVal.height; }).length }; }""", bereich)
    ecmwf = achse()
    _modell(seite, bereich, "GFS")
    gfs = achse()
    seite.close()
    assert ecmwf == gfs or (ecmwf["unten"], ecmwf["oben"], ecmwf["labels"]) == (gfs["unten"], gfs["oben"], gfs["labels"])
    assert (gfs["unten"], gfs["oben"]) == (unten, oben)
    assert [int(t) for t in gfs["labels"]] == ticks and schritt <= 5
    assert gfs["ausserhalb"] == 0
    assert gfs["unten"] <= min(werte) - 1 and gfs["oben"] >= max(werte) + 1
    assert gfs["oben"] - max(werte) < 2.6 and min(werte) - gfs["unten"] < 2.6    # deutlich weniger ungenutzter Raum


# ------------------------------------------------------------------ Bezugslinie
def test_zeitgewichteter_mittelwert_gewichtet_3h_und_6h_schritte(browser, reich):
    seite = _oeffnen(browser, reich["datei"], 1366)
    # Stuetzstellen bei 0, 3 und 9 Stunden, Werte 0, 6, 6: Trapezmittel = 45/9 = 5 (ungewichtet waeren es 4)
    wert = seite.evaluate("([u, w]) => window.__TEST__.zeitgewichteterMittelwert(u, w, 0, 9 * 3600)", [[0, 3 * H, 9 * H], [0, 6, 6]])
    teil = seite.evaluate("([u, w]) => window.__TEST__.zeitgewichteterMittelwert(u, w, 3 * 3600, 9 * 3600)", [[0, 3 * H, 9 * H], [0, 6, 6]])
    luecke = seite.evaluate("([u, w]) => window.__TEST__.zeitgewichteterMittelwert(u, w, 0, 9 * 3600)", [[0, 3 * H, 9 * H], [0, None, 6]])
    seite.close()
    assert wert == pytest.approx(5.0)
    assert teil == pytest.approx(6.0)
    assert luecke is None      # Teilstuecke mit fehlendem Wert zaehlen nicht mit


@pytest.mark.parametrize("niveau, erwartet", [(12.8, 15), (12.4, 10), (12.5, 15), (-1.2, -0), (27.4, 25)])
def test_bezugslinie_ist_die_naechste_vorhandene_5_grad_gitterlinie(browser, reich, niveau, erwartet):
    seite = _oeffnen(browser, reich["datei"], 1366)
    wert = seite.evaluate("([n, t]) => window.__TEST__.bezugslinieWert(n, t)", [niveau, list(range(-5, 36, 5))])
    kein = seite.evaluate("t => window.__TEST__.bezugslinieWert(12.8, t)", [11, 12, 13, 14])
    seite.close()
    assert wert == erwartet
    assert kein is None        # ohne 5-Grad-Linie im Bereich wird keine erfunden


def _einfacher_lauf(modell, unix, wert, mitglieder=4):
    """Lauf mit konstantem Ensemble-Mittel ``wert`` (in beiden Temperaturfeldern)."""
    zeiten = [sv.lokal_text(u) for u in unix]
    n = len(unix)
    def feld():
        return {"zeiten": zeiten, "zeitpunkte_unix": unix, "zeitzone": "Europe/Berlin",
                "kontrolllauf": [wert] * n if modell == "gfs" else None,
                "mitglieder": [[wert + (m - 1.5) for _ in unix] for m in range(mitglieder)],
                "hauptlauf": None, "mittel": [wert] * n, "p10": [wert - 1] * n, "p50": [wert] * n,
                "p90": [wert + 1] * n, "min": [wert - 2] * n, "max": [wert + 2] * n, "n": [mitglieder] * n}
    regen = {"zeiten": zeiten, "zeitpunkte_unix": unix, "zeitzone": "Europe/Berlin",
             "kontrolllauf": [0.0] * n if modell == "gfs" else None,
             "mitglieder": [[0.0] * n for _ in range(mitglieder)], "hauptlauf": None,
             "mittel": [0.0] * n, "p10": [0.0] * n, "p50": [0.0] * n, "p90": [0.0] * n, "min": [0.0] * n,
             "max": [0.0] * n, "n": [mitglieder] * n}
    iso = dt.datetime.fromtimestamp(unix[0], UTC).strftime("%Y-%m-%dT%H:%MZ")
    return {"modell": modell, "modellname": modell.upper(), "init": iso, "verfuegbar_seit": iso, "abgerufen": iso,
            "horizont_tage": 10, "zeitauflosung": "modellnativ-v1", "mitglieder_n": mitglieder, "leads": [], "ziele": [],
            "temperatur_2m": feld(), "temperatur_850hpa": feld(), "niederschlag": regen,
            "ensemble_vollstaendig": True, "hauptlauf_vollstaendig": False, "vollstaendig": False, "hinweise": []}


def _niveau_seite(browser, tmp_path, ecmwf_wert, gfs_wert, ecmwf_bereich, gfs_bereich, name):
    t0 = int(dt.datetime(2026, 9, 21, 0, tzinfo=UTC).timestamp())
    e_unix = list(range(t0 + ecmwf_bereich[0] * 86400, t0 + ecmwf_bereich[1] * 86400 + 1, 3 * H))
    g_unix = list(range(t0 + gfs_bereich[0] * 86400, t0 + gfs_bereich[1] * 86400 + 1, 6 * H))
    daten = _daten([_einfacher_lauf("gfs", g_unix, gfs_wert)], [_einfacher_lauf("ecmwf", e_unix, ecmwf_wert)])
    return _oeffnen(browser, _seite(tmp_path, daten, name), 1366)


def test_niveau_gewichtet_beide_modelle_gleich_und_nutzt_nur_den_gemeinsamen_zeitraum(browser, tmp_path):
    # ECMWF (3-h-Punkte) konstant 10 ueber Tag 0-10, GFS (6-h-Punkte) konstant 20 ueber Tag 2-12:
    # gleiche Gewichtung -> 15, unabhaengig von Punktzahl und Schrittweite
    seite = _niveau_seite(browser, tmp_path, 10.0, 20.0, (0, 10), (2, 12), "niveau1.html")
    info = seite.evaluate("b => window.__TEST__.temperaturNiveau(window.__TEST__.BEREICHE.find(x => x.id === b))", "temp850")
    svg = seite.evaluate("() => ({n: document.querySelector('#chart-temp850').dataset.niveau, b: document.querySelector('#chart-temp850').dataset.bezug})")
    seite.close()
    assert info["niveau"] == pytest.approx(15.0)
    assert info["von"] == int(dt.datetime(2026, 9, 23, tzinfo=UTC).timestamp())      # gemeinsamer Zeitraum: Tag 2 ...
    assert info["bis"] == int(dt.datetime(2026, 10, 1, tzinfo=UTC).timestamp())      # ... bis Tag 10
    assert float(svg["n"]) == pytest.approx(15.0) and float(svg["b"]) == 15


def test_niveau_beschriftung_ist_neutral_und_bezugslinie_liegt_auf_der_gitterlinie(browser, tmp_path):
    seite = _niveau_seite(browser, tmp_path, 12.8, 12.8, (0, 10), (0, 10), "niveau2.html")
    r = seite.evaluate("""() => { const s = document.querySelector('#chart-temp850');
        const ref = s.querySelector('[data-serie=temperatur-referenz]');
        const gitter = [...s.querySelectorAll('line.gitter')].filter(l => l.getAttribute('x1') === l.getAttribute('x2') ? false : true);
        const tickY = [...s.querySelectorAll('text.ax')].filter(t => t.getAttribute('text-anchor') === 'end' && t.textContent === '15')[0];
        return { niveau: s.querySelector('[data-serie=referenz-niveau]').textContent,
                 linie: s.querySelector('[data-serie=referenz-linie]').textContent,
                 refBreite: +ref.getAttribute('stroke-width'), gitterBreite: parseFloat(getComputedStyle(gitter[0]).strokeWidth),
                 refY: +ref.getAttribute('y1'), tickY: +tickY.getAttribute('y') - 3.5 }; }""")
    text = seite.evaluate("document.querySelector('#chart-temp850').textContent")
    seite.close()
    assert r["niveau"] == "Temperaturniveau: 12,8 °C" and r["linie"] == "Bezugslinie: 15 °C"
    assert r["refBreite"] > 2 * r["gitterBreite"]                 # deutlich dicker als das Gitter
    assert r["refY"] == pytest.approx(r["tickY"], abs=0.01)        # liegt genau auf der 15-Grad-Linie
    for wort in ("mild", "sommerlich", "kalt", "warm", "heiß"):
        assert wort not in text.lower()                           # keine automatische Bewertung


def test_niveau_gilt_auch_beim_wechsel_des_modells_unveraendert(browser, reich):
    seite = _oeffnen(browser, reich["datei"], 1366)
    lesen = lambda: seite.evaluate("() => { const s = document.querySelector('#chart-temp850'); return [s.dataset.niveau, s.dataset.bezug, s.dataset.unten, s.dataset.oben]; }")
    ecmwf = lesen()
    _modell(seite, "temp850", "GFS")
    gfs = lesen()
    seite.close()
    assert ecmwf == gfs and ecmwf[0] is not None


# ------------------------------------------------------------------ Erklaerungen
@pytest.mark.parametrize("bereich", BEREICH_IDS)
def test_erklaerung_ist_standardmaessig_zu_und_per_maus_und_tastatur_bedienbar(browser, reich, bereich):
    seite = _oeffnen(browser, reich["datei"], 1366)
    details = seite.locator(f"#erklaerung-{bereich}")
    text = details.locator(".erklaerungstext")
    kurz = seite.locator(f"#s-{bereich} .kurzhinweis")
    assert kurz.is_visible() and len(kurz.inner_text().split(". ")) == 1          # genau ein Satz
    assert details.get_attribute("open") is None and not text.is_visible()
    leiste_y = lambda: seite.evaluate("b => document.querySelector('#bedienleiste-' + b).getBoundingClientRect().top + scrollY", bereich)
    vorher = leiste_y()

    details.locator("summary").click()                                            # Maus
    assert details.get_attribute("open") is not None and text.is_visible()
    assert leiste_y() == vorher                                                    # Bedienleiste bleibt stehen
    details.locator("summary").click()
    assert details.get_attribute("open") is None

    details.locator("summary").focus()                                            # Tastatur
    seite.keyboard.press("Enter")
    assert details.get_attribute("open") is not None
    seite.keyboard.press("Enter")
    assert details.get_attribute("open") is None
    seite.keyboard.press("Space")
    assert details.get_attribute("open") is not None and text.is_visible()
    seite.close()


def test_erklaerungsbox_nutzt_volle_breite_und_begrenzt_nur_die_zeilenlaenge(browser, reich):
    seite = _oeffnen(browser, reich["datei"], 1920)
    seite.locator("#erklaerung-temp850 summary").click()
    m = seite.evaluate("""() => { const d = document.querySelector('#erklaerung-temp850'), p = document.querySelector('#s-temp850 .plot');
        const t = d.querySelector('.erklaerungstext'); return { box: d.getBoundingClientRect().width, plot: p.getBoundingClientRect().width, text: t.getBoundingClientRect().width }; }""")
    inhalt = seite.locator("#erklaerung-temp850 .erklaerungstext").inner_text()
    seite.close()
    assert m["box"] == pytest.approx(m["plot"], abs=1)
    assert 1000 <= m["text"] <= 1110
    # sachliche 850-hPa-Einordnung, ohne automatische Schluesse
    assert "unter 0 °C" in inhalt and "kalte Luftmasse" in inhalt and "Bodenfrost" in inhalt
    assert "20 °C" in inhalt and "Hitzepotenzial" in inhalt and "nicht automatisch" in inhalt


# ------------------------------------------------------------------ Breite
@pytest.mark.parametrize("breite", [390, 800, 1366, 1920])
def test_kein_horizontales_seitenscrollen_auf_beiden_seiten(browser, reich, breite):
    seite = _oeffnen(browser, reich["datei"], breite)
    vorhersage = seite.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    seite.evaluate("location.hash = '#analyse'")
    seite.wait_for_timeout(200)
    analyse = seite.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert not seite.fehler, seite.fehler
    seite.close()
    assert vorhersage[0] <= vorhersage[1] and analyse[0] <= analyse[1]


def test_inhalt_ist_auf_1400_px_begrenzt_und_diagramme_nutzen_die_volle_breite(browser, reich):
    gemessen = {}
    for breite in (800, 1366, 1920):
        seite = _oeffnen(browser, reich["datei"], breite)
        gemessen[breite] = seite.evaluate("""() => { const w = document.querySelector('.wrap').getBoundingClientRect().width;
            const p = document.querySelector('#s-temp850 .plot'), s = document.querySelector('#chart-temp850');
            const cs = getComputedStyle(p); const innen = p.getBoundingClientRect().width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 2;
            return { wrap: w, plot: p.getBoundingClientRect().width, svg: s.getBoundingClientRect().width, innen,
                     viewBox: s.viewBox.baseVal.width, info: document.querySelector('#laufinfoZeile-temp850').getBoundingClientRect().width,
                     leiste: document.querySelector('#bedienleiste-temp850').getBoundingClientRect().width, hoehe: s.getBoundingClientRect().height }; }""")
        seite.close()
    assert gemessen[1920]["wrap"] == 1400                           # nie breiter
    assert gemessen[1366]["wrap"] == 1366 - 40
    for breite, m in gemessen.items():
        assert m["svg"] == pytest.approx(m["innen"], abs=2)         # Diagramm fuellt seine Huelle ...
        assert m["viewBox"] == pytest.approx(m["svg"], abs=2)       # ... ohne Skalierung von Schrift und Linien
        assert m["plot"] == pytest.approx(m["wrap"], abs=1)         # Huelle = ganze Inhaltsbreite
        assert m["info"] == pytest.approx(m["wrap"], abs=1) and m["leiste"] == pytest.approx(m["wrap"], abs=1)
    assert gemessen[1920]["svg"] > 1.35 * 900                        # deutlich groesser als vorher (max. 900 px Basis)
    assert gemessen[1920]["hoehe"] > gemessen[800]["hoehe"]


def test_groessenaenderung_zeichnet_das_diagramm_neu(browser, reich):
    seite = _oeffnen(browser, reich["datei"], 1920)
    breit = seite.evaluate("document.querySelector('#chart-temp850').viewBox.baseVal.width")
    seite.set_viewport_size({"width": 800, "height": 1000})
    seite.wait_for_timeout(400)
    schmal = seite.evaluate("[document.querySelector('#chart-temp850').viewBox.baseVal.width, document.querySelector('#chart-niederschlag').viewBox.baseVal.width, document.documentElement.scrollWidth]")
    seite.set_viewport_size({"width": 1920, "height": 1000})
    seite.wait_for_timeout(400)
    wieder = seite.evaluate("document.querySelector('#chart-temp850').viewBox.baseVal.width")
    assert not seite.fehler, seite.fehler
    seite.close()
    assert breit > 1300 and schmal[0] < 800 and schmal[1] < 800 and schmal[2] <= 800 and wieder == breit


# ------------------------------------------------------------------ Kein Layoutsprung
@pytest.mark.parametrize("breite", [390, 800, 1920])
def test_kein_layoutsprung_beim_wechsel_von_modell_lauf_und_haken(browser, reich, breite):
    """Rahmenoberkante des Diagramms, Bedienleiste und Legende bleiben in JEDEM Zustand an derselben Stelle."""
    seite = _oeffnen(browser, reich["datei"], breite, 1200)

    def lage(bereich):
        return seite.evaluate("""b => { const sec = document.querySelector('#s-' + b).getBoundingClientRect().top;
            const t = id => { const r = document.querySelector(id).getBoundingClientRect(); return [Math.round((r.top - sec) * 10) / 10, Math.round(r.height * 10) / 10]; };
            return { leiste: t('#bedienleiste-' + b), info: t('#laufinfoZeile-' + b), status: t('#laufwarnung-' + b), legende: t('#leg-' + b) }; }""", bereich)

    def rahmen(bereich):
        return seite.evaluate("""b => { const sec = document.querySelector('#s-' + b).getBoundingClientRect().top;
            const r = document.querySelector('#chart-' + b).parentElement.getBoundingClientRect(); return [Math.round((r.top - sec) * 10) / 10, Math.round(r.height * 10) / 10]; }""", bereich)

    for bereich in BEREICH_IDS:
        referenz = (lage(bereich)["leiste"], lage(bereich)["info"], lage(bereich)["status"], lage(bereich)["legende"], rahmen(bereich))
        zustaende = []
        for modell in ("GFS", "ECMWF-IFS"):
            _modell(seite, bereich, modell)
            for i in range(seite.locator(f"#laufwahl-{bereich} button").count()):
                seite.locator(f"#laufwahl-{bereich} button").nth(i).click()
                seite.wait_for_timeout(30)
                for an in (False, True):
                    # alle Haken zugleich aus bzw. an (die laengste Legende entsteht mit allen)
                    for haken in ("hauptlauf", "vorlaeufe", "anderes"):
                        seite.locator(f"#{haken}Ein-{bereich}").set_checked(an)
                    seite.wait_for_timeout(30)
                    l = lage(bereich)
                    zustaende.append((modell, i, an, (l["leiste"], l["info"], l["status"], l["legende"], rahmen(bereich))))
        assert len(zustaende) >= 12
        abweichend = [z for z in zustaende if z[3] != referenz]
        assert not abweichend, f"{bereich} @ {breite}px: {abweichend[:3]} != {referenz}"
    assert not seite.fehler, seite.fehler
    seite.close()


@pytest.mark.parametrize("breite", [390, 800, 1920])
def test_diagrammrahmen_beginnt_vor_und_nach_dem_modellwechsel_an_derselben_stelle(browser, reich, breite):
    seite = _oeffnen(browser, reich["datei"], breite, 1200)
    oben = lambda b: seite.evaluate("b => document.querySelector('#chart-' + b).parentElement.getBoundingClientRect().top + scrollY", b)
    for bereich in BEREICH_IDS:
        vorher = oben(bereich)
        _modell(seite, bereich, "GFS")
        gfs = oben(bereich)
        _modell(seite, bereich, "ECMWF-IFS")
        nachher = oben(bereich)
        assert vorher == gfs == nachher, (bereich, vorher, gfs, nachher)
    seite.close()


# ------------------------------------------------------------------ Zeitachse
def _erwartete_mitternaechte(von, bis):
    tag = dt.datetime.fromtimestamp(von, BERLIN).date()
    out = []
    while True:
        u = int(dt.datetime.combine(tag, dt.time(0), tzinfo=BERLIN).timestamp())
        if u > bis:
            return out
        if u >= von:
            out.append(u)
        tag += dt.timedelta(days=1)


@pytest.mark.parametrize("modell, init, horizont", [
    ("ecmwf", dt.datetime(2026, 10, 24, 12, tzinfo=UTC), 15),      # Winterzeit-Umstellung 25.10.2026 im Horizont
    ("gfs", dt.datetime(2026, 10, 24, 18, tzinfo=UTC), 16),
    ("ecmwf", dt.datetime(2027, 3, 26, 0, tzinfo=UTC), 15),        # Sommerzeit-Umstellung 28.03.2027
    ("gfs", dt.datetime(2026, 9, 20, 0, tzinfo=UTC), 16),          # ohne Umstellung
])
def test_tageslinien_liegen_bei_echter_ortsmitternacht_auch_an_umstelltagen(browser, tmp_path, modell, init, horizont):
    daten = _daten([_lauf("gfs", init, horizont)] if modell == "gfs" else [],
                   [_lauf("ecmwf", init, horizont, mitglieder=6)] if modell == "ecmwf" else [])
    lauf = daten["vorhersage"][modell][0]
    unix = lauf["temperatur_2m"]["zeitpunkte_unix"]
    seite = _oeffnen(browser, _seite(tmp_path, daten, f"t_{modell}_{init:%Y%m%d}.html"), 1366)
    for bereich in BEREICH_IDS:
        r = seite.evaluate("""b => { const s = document.querySelector('#chart-' + b);
            const linien = [...s.querySelectorAll('[data-serie=tageslinie]')].map(l => [+l.dataset.unix, +l.getAttribute('x1')]);
            return { linien, breite: s.viewBox.baseVal.width }; }""", bereich)
        erwartet = _erwartete_mitternaechte(unix[0], unix[-1])
        assert [u for u, _ in r["linien"]] == erwartet
        # x ist linear in der Unixzeit (keine Verschiebung auf den ersten Datenpunkt des Tages)
        x0, x1 = 46, r["breite"] - 18
        for u, x in r["linien"]:
            assert x == pytest.approx(x0 + (u - unix[0]) / (unix[-1] - unix[0]) * (x1 - x0), abs=0.01)
    tage = [b - a for a, b in zip(erwartet, erwartet[1:])]
    seite.close()
    if init.year == 2026 and init.month == 10:
        assert 25 * H in tage                                       # 25-Stunden-Tag
    if init.year == 2027:
        assert 23 * H in tage                                       # 23-Stunden-Tag


@pytest.mark.parametrize("breite", [390, 800, 1366, 1920])
@pytest.mark.parametrize("init", [dt.datetime(2026, 10, 24, 0, tzinfo=UTC), dt.datetime(2026, 10, 24, 12, tzinfo=UTC),
                                  dt.datetime(2026, 9, 20, 6, tzinfo=UTC), dt.datetime(2026, 9, 20, 22, tzinfo=UTC)])
def test_datumsbeschriftungen_werden_nie_abgeschnitten_und_ueberlappen_nicht(browser, tmp_path, init, breite):
    """Auch die letzte Beschriftung liegt vollstaendig im Diagramm (z. B. wenn Mitternacht kurz vor dem Ende liegt)."""
    daten = _daten([], [_lauf("ecmwf", init, 15, mitglieder=4)])
    seite = _oeffnen(browser, _seite(tmp_path, daten, f"b_{init:%m%d%H}_{breite}.html"), breite)
    for bereich in BEREICH_IDS:
        r = seite.evaluate("""b => { const s = document.querySelector('#chart-' + b), B = s.viewBox.baseVal.width;
            const t = [...s.querySelectorAll('[data-serie=tagesbeschriftung]')].map(x => { const r = x.getBBox(); return [r.x, r.x + r.width]; });
            return { B, t }; }""", bereich)
        assert r["t"], "keine Datumsbeschriftung"
        assert all(a >= 0 and e <= r["B"] for a, e in r["t"]), r
        assert all(n[0] >= v[1] - 0.5 for v, n in zip(r["t"], r["t"][1:])), r     # kein Ueberlappen
    assert not seite.fehler, seite.fehler
    seite.close()


def test_letzte_beschriftung_ist_vorhanden_und_sichtbar_wenn_das_ende_kurz_nach_mitternacht_liegt(browser, tmp_path):
    # ECMWF 00Z + 15 Tage endet lokal um 02:00 (Sommerzeit) bzw. 01:00: die letzte Mitternacht liegt fast am rechten Rand
    init = dt.datetime(2026, 9, 20, 0, tzinfo=UTC)
    daten = _daten([], [_lauf("ecmwf", init, 15, mitglieder=4)])
    seite = _oeffnen(browser, _seite(tmp_path, daten, "ende.html"), 1920)
    r = seite.evaluate("""() => { const s = document.querySelector('#chart-temp850'); const B = s.viewBox.baseVal.width;
        const l = [...s.querySelectorAll('[data-serie=tagesbeschriftung]')]; const z = l[l.length - 1];
        const b = z.getBBox(); const linien = [...s.querySelectorAll('[data-serie=tageslinie]')];
        return { text: z.textContent, rechts: b.x + b.width, B, letzteLinie: +linien[linien.length - 1].getAttribute('x1') }; }""")
    seite.close()
    assert r["text"] == "Mo 5.10." and r["rechts"] <= r["B"]
    assert r["B"] - r["letzteLinie"] < 30                               # Testvoraussetzung: Linie fast am Rand


def test_tooltip_und_tabelle_zeigen_ortszeit_aus_der_unixzeit_auch_in_der_doppelten_stunde(browser, tmp_path):
    init = dt.datetime(2026, 10, 24, 22, tzinfo=UTC)               # = 00:00 Ortszeit am 25.10. (Sommerzeit)
    daten = _daten([], [_lauf("ecmwf", init, 3, mitglieder=4)])
    unix = daten["vorhersage"]["ecmwf"][0]["temperatur_2m"]["zeitpunkte_unix"]
    seite = _oeffnen(browser, _seite(tmp_path, daten, "doppel.html"), 1366)
    tabelle = seite.evaluate("[...document.querySelectorAll('#tab-temp850 tbody tr')].map(r => [r.cells[0].textContent, r.cells[1].textContent])")
    ortsteile = seite.evaluate("u => u.map(x => { const t = window.__TEST__.ortsTeile(x); return [t.iso, t.stunde, t.minute]; })", unix)
    # Ortszeit 02:00 kommt an diesem Tag zweimal vor -- beide Zeilen sind eindeutige, verschiedene Zeitpunkte
    zwei_uhr = [i for i, u in enumerate(unix) if dt.datetime.fromtimestamp(u, BERLIN).strftime("%H:%M") == "02:00"]
    seite.locator("#chart-temp850 rect.treffer").nth(zwei_uhr[0]).hover(force=True)
    tip = seite.locator("#tip").inner_text()
    seite.close()
    erwartet = [dt.datetime.fromtimestamp(u, BERLIN).strftime("%H:%M") for u in unix]
    assert [z for _, z in tabelle] == erwartet
    assert [(t[0], f"{t[1]:02d}:{t[2]:02d}") for t in ortsteile] == [(dt.datetime.fromtimestamp(u, BERLIN).date().isoformat(), e) for u, e in zip(unix, erwartet)]
    assert "02:00 Uhr" in tip and "25.10." in tip


def test_ortsmitternacht_hilfsfunktion_an_den_umstelltagen(browser, reich):
    seite = _oeffnen(browser, reich["datei"], 1366)
    r = seite.evaluate("() => [[2026,10,25],[2026,10,26],[2027,3,28],[2027,3,29],[2026,9,20]].map(([j,m,t]) => window.__TEST__.ortsMitternacht(j,m,t))")
    seite.close()
    erwartet = [int(dt.datetime(j, m, t, tzinfo=BERLIN).timestamp()) for j, m, t in
                [(2026, 10, 25), (2026, 10, 26), (2027, 3, 28), (2027, 3, 29), (2026, 9, 20)]]
    assert r == erwartet
    assert r[1] - r[0] == 25 * H and r[3] - r[2] == 23 * H


# ------------------------------------------------------------------ Unveraendert: Tabellen, Analyse, Legende
def test_tabelle_legende_und_analyse_funktionieren_weiter(browser, reich):
    seite = _oeffnen(browser, reich["datei"], 1366)
    zeilen = seite.locator("#tab-temp850 tbody tr").count()
    punkte = len(reich["daten"]["vorhersage"]["ecmwf"][0]["temperatur_2m"]["zeitpunkte_unix"])
    legende = seite.locator("#leg-temp850").inner_text()
    _modell(seite, "temp850", "GFS")
    legende_gfs = seite.locator("#leg-temp850").inner_text()
    seite.locator('#hauptnav a[data-seite="analyse"]').click()
    seite.wait_for_timeout(200)
    sichtbar = seite.evaluate("[...document.querySelectorAll('main[id^=seite-]')].filter(m => !m.hidden).map(m => m.id)")
    analyse_breite = seite.evaluate("document.querySelector('#seite-analyse').getBoundingClientRect().width")
    seite.locator('#hauptnav a[data-seite="vorhersage"]').click()
    seite.wait_for_timeout(300)
    nach_rueckkehr = seite.evaluate("document.querySelector('#chart-temp850').viewBox.baseVal.width")
    fehler = list(seite.fehler)
    seite.close()
    assert zeilen == punkte
    assert "Hauptlauf (deterministisch)" in legende and "Kontrolllauf" not in legende   # ECMWF: kein Kontrolllauf
    assert "Kontrolllauf" in legende_gfs
    assert sichtbar == ["seite-analyse"] and analyse_breite <= 980
    assert nach_rueckkehr > 1200
    assert not fehler, fehler


def test_seite_startet_auch_bei_analyse_hash_und_zeichnet_die_vorhersage_beim_einblenden(browser, reich):
    seite = browser.new_page(viewport={"width": 1920, "height": 1000})
    seite.goto(f"file://{reich['datei']}#analyse")
    seite.wait_for_timeout(300)
    seite.evaluate("location.hash = '#vorhersage-analyse'")
    seite.wait_for_timeout(400)
    r = seite.evaluate("""() => { const s = document.querySelector('#chart-temp850'); return [s.viewBox.baseVal.width, s.getBoundingClientRect().width,
        document.querySelector('#bedienleiste-temp850').style.minHeight]; }""")
    seite.close()
    assert r[0] > 1300 and r[0] == pytest.approx(r[1], abs=2)
    assert r[2] not in ("", "0px")            # Mindesthoehen wurden nach dem Einblenden gemessen


# ------------------------------------------------------------------ Korrekturen (Rueckmeldung nach dem ersten Einsatz)
def test_einleitungstext_nutzt_die_volle_breite(browser, reich):
    seite = _oeffnen(browser, reich["datei"], 1366)
    r = seite.evaluate("""() => ({ text: document.querySelector('.unterzeile[data-fuer~="vorhersage-analyse"]').getBoundingClientRect().width,
        kopf: document.querySelector('header.kopf').getBoundingClientRect().width })""")
    seite.close()
    assert r["text"] == pytest.approx(r["kopf"], abs=2) and r["text"] > 1000


def _tafel(seite, bereich="temp850"):
    return seite.evaluate("""b => { const s = document.querySelector('#chart-' + b);
        const r = s.querySelector('[data-serie=referenz-tafel]');
        return { rechts: +r.getAttribute('x') + +r.getAttribute('width'), oben: +r.getAttribute('y'),
                 unten: +r.getAttribute('y') + +r.getAttribute('height'), breite: s.viewBox.baseVal.width,
                 text: [...s.querySelectorAll('[data-serie^=referenz-]:not([data-serie=referenz-tafel])')].map(t => t.textContent).join(' | ') }; }""", bereich)


@pytest.mark.parametrize("breite", [900, 1366, 1920])
def test_niveautafel_sitzt_fest_oben_rechts_ausserhalb_der_kurven(browser, reich, breite):
    seite = _oeffnen(browser, reich["datei"], breite)
    a = _tafel(seite)                                   # ECMWF
    _modell(seite, "temp850", "GFS")
    b = _tafel(seite)
    seite.locator("#laufwahl-temp850 button").nth(3).click()   # anderer Lauf -> anderes Niveau
    seite.wait_for_timeout(60)
    c = _tafel(seite)
    seite.close()
    for t in (a, b, c):
        assert "Temperaturniveau:" in t["text"] and "Bezugslinie:" in t["text"]
        assert t["rechts"] == pytest.approx(t["breite"] - 18, abs=0.01)     # rechtsbuendig am Diagrammrand
        assert t["oben"] >= 0 and t["unten"] <= 28                           # im freien Rand, ueber der Zeichenflaeche
    assert (a["rechts"], a["oben"], a["unten"]) == (b["rechts"], b["oben"], b["unten"]) == (c["rechts"], c["oben"], c["unten"])


def _regenseite(browser, tmp_path, ausreisser_faktor):
    """ECMWF-Lauf, bei dem ein einzelnes Mitglied viel mehr Niederschlag liefert als der Rest."""
    lauf = _lauf("ecmwf", dt.datetime(2026, 10, 24, 12, tzinfo=UTC), 15, mitglieder=50, basis=9.0)
    regen = lauf["niederschlag"]
    regen["mitglieder"][0] = [round(v * ausreisser_faktor, 2) for v in regen["mitglieder"][0]]
    regen.update(sv.aggregiere_alle_leads(regen["mitglieder"], len(regen["zeiten"])))
    datei = _seite(tmp_path, _daten([], [lauf]), f"regen{ausreisser_faktor}.html")
    return _oeffnen(browser, datei, 1366), regen


@pytest.mark.parametrize("faktor", [1, 25])
def test_regenachse_endet_20_prozent_ueber_dem_p90_und_ausreisser_werden_abgeschnitten(browser, tmp_path, faktor):
    seite, regen = _regenseite(browser, tmp_path, faktor)
    r = seite.evaluate("""() => { const s = document.querySelector('#chart-niederschlag');
        const cp = s.querySelector('clipPath rect');
        const m = [...s.querySelectorAll('[data-serie=mitglied]')];
        const gitter = [...s.querySelectorAll('text.ax')].filter(t => t.getAttribute('text-anchor') === 'end').map(t => +t.textContent);
        return { oben: +s.dataset.oben, unten: +s.dataset.unten, gitter,
                 klemmeY: +cp.getAttribute('y'), klemmeH: +cp.getAttribute('height'),
                 geklemmt: m.length ? m.every(p => p.getAttribute('clip-path') === 'url(#klemme-niederschlag)') : null,
                 nMitglieder: m.length, gitterLinien: s.querySelectorAll('line.gitter').length }; }""")
    seite.close()
    p90max = max(v for v in regen["p90"] if v is not None)
    erwartet = max(5.0, 1.2 * p90max)
    assert r["oben"] == pytest.approx(erwartet, abs=1e-6) and r["unten"] == 0
    assert r["nMitglieder"] == 50 and r["geklemmt"] is True
    assert r["klemmeY"] == 28 and r["klemmeH"] > 100                       # Zeichenflaeche als Klemmrechteck
    assert all(float(t).is_integer() for t in r["gitter"]) and max(r["gitter"]) <= r["oben"] and r["gitter"][0] == 0
    assert 4 <= len(r["gitter"]) <= 9 and r["gitterLinien"] >= len(r["gitter"])
    hoechstes = max(max(reihe) for reihe in regen["mitglieder"])
    if faktor > 1:
        assert hoechstes > 3 * r["oben"]                                   # das Mitglied bricht deutlich nach oben aus
    else:
        assert hoechstes <= r["oben"] + 1e-9                               # ohne Ausreisser bleibt alles im Bild


def test_regenachse_ausreisser_stauchen_die_achse_nicht(browser, tmp_path):
    mit, _ = _regenseite(browser, tmp_path, 25)
    oben_mit = mit.evaluate("+document.querySelector('#chart-niederschlag').dataset.oben")
    mit.close()
    ohne, _ = _regenseite(browser, tmp_path, 1)
    oben_ohne = ohne.evaluate("+document.querySelector('#chart-niederschlag').dataset.oben")
    ohne.close()
    assert oben_mit < 3 * oben_ohne and oben_mit < 60      # ein Mitglied mit 25-fachem Regen verschiebt die Achse kaum


# ------------------------------------------------------------------ Nachbesserungen

def _y_beschriftung(seite, bereich):
    return seite.evaluate(
        "id => [...document.querySelectorAll(`#chart-${id} text`)]"
        ".filter(t => t.getAttribute('text-anchor') === 'end').map(t => t.textContent)", bereich)


def test_niederschlagsachse_ist_fuer_beide_modelle_dieselbe(browser, reich):
    """Ohne gemeinsame Achse sehen beide Modelle gleich nass aus, obwohl die Mengen
    unterschiedlich sind. Die Achse richtet sich nach dem hoechsten 90.-Perzentil."""
    seite = _oeffnen(browser, reich["datei"], 1366)
    _modell(seite, "niederschlag", "GFS")
    gfs = _y_beschriftung(seite, "niederschlag")
    _modell(seite, "niederschlag", "ECMWF-IFS")
    ecmwf = _y_beschriftung(seite, "niederschlag")
    p90max = seite.evaluate(
        "() => window.__TEST__.gemeinsamesP90Maximum(window.__TEST__.BEREICHE.find(b => b.id === 'niederschlag'))")
    fehler = seite.fehler
    seite.close()
    assert not fehler, fehler
    assert gfs and gfs == ecmwf, (gfs, ecmwf)
    assert p90max and p90max > 0


def test_reiterleiste_springt_beim_seitenwechsel_nicht(browser, reich):
    """Der Einleitungstext ist je Reiter unterschiedlich lang. Die Kopfzone haelt
    deshalb die groesste Hoehe frei; die Reiterleiste bleibt an ihrem Platz."""
    seite = _oeffnen(browser, reich["datei"], 1000)
    oben = {}
    for reiter in ("vorhersage", "station-heute", "station-verlauf", "analyse"):
        seite.evaluate("h => location.hash = h", "#" + reiter)
        seite.wait_for_timeout(120)
        oben[reiter] = seite.evaluate("() => document.querySelector('#hauptnav').getBoundingClientRect().top")
    fehler = seite.fehler
    seite.close()
    assert not fehler, fehler
    assert max(oben.values()) - min(oben.values()) <= 1, oben


def test_jeder_reiter_hat_eine_eigene_einzeilige_ueberschrift(browser, reich):
    """Gleiche Ueberschrift auf mehreren Reitern war verwirrend; zwei Zeilen kosten Platz."""
    titel = {}
    for breite in (1366, 700, 390, 320):
        seite = _oeffnen(browser, reich["datei"], breite)
        for reiter in ("vorhersage", "wetter48", "station-heute", "station-verlauf", "analyse"):
            seite.evaluate("h => location.hash = h", "#" + reiter)
            seite.wait_for_timeout(120)
            r = seite.evaluate("""() => {
                const s = [...document.querySelectorAll('.kopf h1 span')].find(e => e.offsetParent);
                const stil = getComputedStyle(s);
                return { text: s.textContent.trim(),
                         zeilen: Math.round(s.getBoundingClientRect().height / parseFloat(stil.lineHeight)) };
            }""")
            assert r["zeilen"] == 1, (breite, reiter, r)
            titel.setdefault(reiter, r["text"])
        fehler = seite.fehler
        seite.close()
        assert not fehler, fehler
    assert titel["vorhersage"] != titel["wetter48"] != titel["analyse"] != titel["vorhersage"]
    assert titel["station-heute"] == titel["station-verlauf"] == "Wetterstation Stefanskirchen"
