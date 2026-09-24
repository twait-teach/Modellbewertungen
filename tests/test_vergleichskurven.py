"""Browsertests fuer die Haken im Reiter "Vorhersage Analyse": Haupt-/Kontrolllauf,
Vorlaeufe (die drei vorangegangenen Laeufe desselben Modells) und das jeweils andere Modell."""
import datetime as dt

import pytest

from test_vorhersage_darstellung import UTC, _daten, _lauf, _oeffnen, _seite, browser  # noqa: F401

H = 3600


@pytest.fixture(scope="module")
def vergleich(tmp_path_factory):
    # Winterzeit-Umstellung (25.10.2026) liegt im Zeitraum -- das gleitende Mittel rechnet in echter Zeit.
    gfs = [_lauf("gfs", dt.datetime(2026, 10, 25, t, tzinfo=UTC), 5, basis=12.0 + t / 10) for t in (6, 0)] \
        + [_lauf("gfs", dt.datetime(2026, 10, d, 0, tzinfo=UTC), 5, basis=10.0 - (25 - d)) for d in (24, 23, 22)]
    ecmwf = [_lauf("ecmwf", dt.datetime(2026, 10, 25, 0, tzinfo=UTC), 5, mitglieder=20, basis=8.0)]
    daten = _daten(gfs, ecmwf)
    return _seite(tmp_path_factory.mktemp("vergleich"), daten, "vergleich.html")


def _serien(seite, bereich):
    return seite.evaluate("b => [...document.querySelectorAll('#chart-' + b + ' [data-serie]')].map(e => e.dataset.serie)", bereich)


def test_vorlaeufe_erscheinen_als_eigene_kurven_mit_abstand_in_der_legende(browser, vergleich):
    seite = _oeffnen(browser, vergleich, 1366)
    seite.locator("#modellwahl-temp850 button", has_text="GFS").click()
    seite.locator("#laufwahl-temp850 button").nth(1).click()          # GFS 25.10., 00 UTC
    seite.locator("#vorlaeufeEin-temp850").check()
    serien = _serien(seite, "temp850")
    legende = seite.locator("#leg-temp850").inner_text()
    fehler = list(seite.fehler)
    seite.close()
    assert serien.count("vorlauf") == 3
    for text in ("Vorlauf 24.10., 00 UTC (−24 h)", "Vorlauf 23.10., 00 UTC (−48 h)", "Vorlauf 22.10., 00 UTC (−72 h)"):
        assert text in legende                               # die drei vorangegangenen Laeufe, mit Abstand
    assert not fehler, fehler


def test_vorlaeufe_sind_die_drei_vorangegangenen_laeufe_und_passender_lauf_des_anderen_modells(browser, vergleich):
    seite = _oeffnen(browser, vergleich, 1366)
    r = seite.evaluate("""() => { const T = window.__TEST__, D = window.DATEN || {};
        const laeufe = (typeof DATEN !== 'undefined' ? DATEN : D).vorhersage;
        const g00 = laeufe.gfs.find(l => l.init === '2026-10-25T00:00Z'), g06 = laeufe.gfs.find(l => l.init === '2026-10-25T06:00Z');
        return { vor00: T.vorlaeufeVon(g00).map(v => v.lauf && v.lauf.init),
                 vor06: T.vorlaeufeVon(g06).map(v => v.lauf && v.lauf.init),
                 partner06: T.partnerLauf(g06).init, partnerEcmwf: T.partnerLauf(laeufe.ecmwf[0]).init }; }""")
    seite.close()
    assert r["vor00"] == ["2026-10-24T00:00Z", "2026-10-23T00:00Z", "2026-10-22T00:00Z"]
    assert r["vor06"] == ["2026-10-25T00:00Z", "2026-10-24T00:00Z", "2026-10-23T00:00Z"]   # beliebige Startzeit
    assert r["partner06"] == "2026-10-25T00:00Z"             # ECMWF hat kein 06 UTC -> der 6 h aeltere
    assert r["partnerEcmwf"] == "2026-10-25T00:00Z"


def test_niederschlag_der_vorlaeufe_beginnt_beim_start_des_gewaehlten_laufs(browser, vergleich):
    seite = _oeffnen(browser, vergleich, 1366)
    r = seite.evaluate("""() => { const T = window.__TEST__, laeufe = DATEN.vorhersage;
        const b = T.BEREICHE.find(x => x.id === 'niederschlag');
        const aktuell = laeufe.gfs.find(l => l.init === '2026-10-25T00:00Z'), alt = laeufe.gfs.find(l => l.init === '2026-10-24T00:00Z');
        const start = Date.parse(aktuell.init) / 1000;
        const r = T.vergleichsreihe(b, alt, start), eigen = T.vergleichsreihe(b, aktuell, start);
        const ab = r.unix.map((u, i) => [u, r.werte[i]]).filter(p => p[1] != null);
        return { erster: ab[0][0] - start, ersterWert: ab[0][1], vorStart: r.unix.filter((u, i) => u < start && r.werte[i] != null).length,
                 eigenGleichMittel: eigen.werte.every((v, i) => Math.abs(v - aktuell.niederschlag.mittel[i]) < 0.011) }; }""")
    seite.close()
    assert r["vorStart"] == 0                                # vor dem Start des gewaehlten Laufs: keine Kurve
    assert 0 <= r["erster"] <= 6 * H and r["ersterWert"] < 0.2
    assert r["eigenGleichMittel"]                            # der gewaehlte Lauf selbst bleibt unveraendert


def test_haken_haupt_kontrolllauf_und_anderes_modell(browser, vergleich):
    seite = _oeffnen(browser, vergleich, 1366)
    seite.locator("#modellwahl-temp850 button", has_text="GFS").click()
    name = seite.locator("#schalter-temp850 .anderes-name").inner_text()
    mit = _serien(seite, "temp850")
    seite.locator("#hauptlaufEin-temp850").uncheck()
    seite.locator("#anderesEin-temp850").check()
    ohne = _serien(seite, "temp850")
    fehler = list(seite.fehler)
    seite.close()
    assert name == "ECMWF-IFS"
    assert "hauptlauf" in mit and "kontrolllauf" in mit
    assert "hauptlauf" not in ohne and "kontrolllauf" not in ohne and "anderes-modell" in ohne
    assert "gleitendes-mittel" not in ohne                   # 850 hPa: ungeglaettet
    assert not fehler, fehler


def test_ohne_gespeicherte_vorlaeufe_steht_ein_hinweis_in_der_legende(browser, vergleich):
    seite = _oeffnen(browser, vergleich, 1366)
    seite.locator("#modellwahl-temp850 button", has_text="GFS").click()
    seite.locator("#laufwahl-temp850 button").last.click()               # aeltester GFS-Lauf: nichts davor
    seite.locator("#vorlaeufeEin-temp850").check()
    legende = seite.locator("#leg-temp850").inner_text()
    serien = _serien(seite, "temp850")
    seite.close()
    assert "keine gespeichert" in legende and "vorlauf" not in serien


def test_850_hpa_zeigt_das_andere_modell_vollstaendig(browser, vergleich):
    seite = _oeffnen(browser, vergleich, 1366)
    seite.locator("#anderesEin-temp850").check()
    seite.locator("#anderesEin-niederschlag").check()
    s850, sRegen = _serien(seite, "temp850"), _serien(seite, "niederschlag")
    legende = seite.locator("#leg-temp850").inner_text()
    fehler = list(seite.fehler)
    seite.close()
    assert s850.count("anderes-band") == 2 and "anderes-mitglied" in s850 and s850.count("anderes-modell") == 1
    assert "anderes-mitglied" not in sRegen and "anderes-band" not in sRegen    # Niederschlag: nur die Vergleichskurve
    for text in ("ECMWF-IFS 10.–90. Perzentil", "GFS 10.–90. Perzentil", "GFS Einzelmitglieder", "Hauptlauf (deterministisch)"):
        assert text in legende
    assert not fehler, fehler


def test_auf_schmalen_bildschirmen_steht_die_vergleichslegende_im_diagramm(browser, vergleich):
    """Sonst schoebe die Legende der Vorlaeufe das Diagramm weit nach unten."""
    seite = _oeffnen(browser, vergleich, 390)
    seite.locator("#modellwahl-temp850 button", has_text="GFS").click()
    seite.locator("#laufwahl-temp850 button").nth(1).click()          # GFS 25.10., 00 UTC (drei Vorlaeufe)
    oben = lambda: seite.evaluate("document.querySelector('#chart-temp850').getBoundingClientRect().top + scrollY")
    vorher = oben()
    seite.locator("#vorlaeufeEin-temp850").check()
    seite.locator("#anderesEin-temp850").check()
    seite.wait_for_timeout(120)
    r = seite.evaluate("""() => ({ legende: document.querySelector('#leg-temp850').innerText,
        tafel: [...document.querySelectorAll('#chart-temp850 [data-serie=legendentafel] text')].map(t => t.textContent) })""")
    nachher = oben()
    seite.close()
    assert abs(nachher - vorher) < 1                       # Diagramm bleibt an derselben Stelle
    assert "Vorlauf" not in r["legende"] and "ECMWF" not in r["legende"]     # Vergleiche stehen nicht mehr oben
    assert any("Vorlauf" in t for t in r["tafel"]) and any(t.startswith("ECMWF") for t in r["tafel"])


def test_auf_breiten_bildschirmen_bleibt_die_legende_ueber_dem_diagramm(browser, vergleich):
    seite = _oeffnen(browser, vergleich, 1366)
    seite.locator("#modellwahl-temp850 button", has_text="GFS").click()
    seite.locator("#laufwahl-temp850 button").nth(1).click()
    seite.locator("#vorlaeufeEin-temp850").check()
    r = seite.evaluate("""() => ({ legende: document.querySelector('#leg-temp850').innerText,
        tafeln: document.querySelectorAll('#chart-temp850 [data-serie=legendentafel]').length })""")
    seite.close()
    assert "Vorlauf" in r["legende"] and r["tafeln"] == 0
