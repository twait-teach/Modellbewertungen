"""Browsertests fuer die Haken im Meteogramm: Haupt-/Kontrolllauf, gleitendes 24-h-Mittel,
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


def test_gleitendes_mittel_nimmt_den_tagesgang_heraus_und_laesst_die_raender_leer(browser, vergleich):
    seite = _oeffnen(browser, vergleich, 1366)
    r = seite.evaluate("""() => { const T = window.__TEST__;
        const u = [], w = []; for (let h = 0; h <= 96; h += 3) { u.push(1792800000 + h * 3600); w.push(10 + 5 * Math.sin(2 * Math.PI * h / 24)); }
        const g = T.gleitendesMittel(u, w);
        return { leer: [g[0], g[3], g[g.length - 1]], mitte: g.filter(v => v != null) }; }""")
    seite.close()
    assert r["leer"] == [None, None, None]                   # erste und letzte 12 h ohne volles Fenster
    assert all(abs(v - 10) < 1e-6 for v in r["mitte"])       # reiner Tagesgang mittelt sich exakt weg


def test_vorlaeufe_sperren_das_gleitende_mittel_bei_der_2m_temperatur(browser, vergleich):
    seite = _oeffnen(browser, vergleich, 1366)
    seite.locator("#modellwahl-temp2m button", has_text="GFS").click()
    seite.locator("#laufwahl-temp2m button").nth(1).click()          # GFS 25.10., 00 UTC
    glatt = lambda: seite.evaluate("() => { const g = document.querySelector('#glattEin-temp2m'); return [g.checked, g.disabled]; }")
    vorher = glatt()
    seite.locator("#vorlaeufeEin-temp2m").check()
    gesperrt = glatt()
    serien = _serien(seite, "temp2m")
    legende = seite.locator("#leg-temp2m").inner_text()
    seite.locator("#vorlaeufeEin-temp2m").uncheck()
    danach = glatt()
    fehler = list(seite.fehler)
    seite.close()
    assert vorher == [False, False]
    assert gesperrt == [True, True]
    assert danach == [True, False]                           # bleibt angehakt, ist aber wieder frei
    assert serien.count("gleitendes-mittel") == 1 and serien.count("vorlauf") == 3
    for text in ("Vorlauf 24.10., 00 UTC (−24 h)", "23.10., 00 UTC (−48 h)", "22.10., 00 UTC (−72 h)"):
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
    seite.locator("#modellwahl-temp2m button", has_text="GFS").click()
    seite.locator("#laufwahl-temp2m button").last.click()               # aeltester GFS-Lauf: nichts davor
    seite.locator("#vorlaeufeEin-temp2m").check()
    legende = seite.locator("#leg-temp2m").inner_text()
    serien = _serien(seite, "temp2m")
    seite.close()
    assert "keine gespeichert" in legende and "vorlauf" not in serien
