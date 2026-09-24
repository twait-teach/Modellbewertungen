"""Browsertests fuer den Reiter "Vorhersage" (Mittelfrist): Temperaturkurve mit Band,
Niederschlagsflaeche mit Wahrscheinlichkeitsfaerbung, Tagessymbole, Modellvergleich."""
import datetime as dt

import pytest

from test_vorhersage_darstellung import UTC, _daten, _lauf, _seite, browser  # noqa: F401

STUNDE = 3600


def _mit_wetter48(daten, tage=16):
    """Tageswettercodes, wie sie sammeln_48h.py mitliefert (Quelle der Tagessymbole)."""
    start = int(dt.datetime(2026, 10, 25, tzinfo=UTC).timestamp())
    for modell in ("gfs", "ecmwf"):
        daten.setdefault("wetter48", {})[modell] = {
            "modell": modell, "zeitpunkte_unix": [start], "temperatur_2m": [8.0], "niederschlag": [0.0],
            "wettercode": [3], "tag": [1], "abgerufen": "2026-10-25T00:00Z",
            "tage_unix": [start + i * 86400 for i in range(tage)],
            "tageswettercode": [61 if i % 2 else 3 for i in range(tage)]}
    return daten


@pytest.fixture(scope="module")
def mittelfrist(tmp_path_factory):
    gfs = [_lauf("gfs", dt.datetime(2026, 10, 25, 0, tzinfo=UTC), 6)]
    ecmwf = [_lauf("ecmwf", dt.datetime(2026, 10, 25, 0, tzinfo=UTC), 6, mitglieder=20, basis=9.0)]
    return _seite(tmp_path_factory.mktemp("mittelfrist"), _mit_wetter48(_daten(gfs, ecmwf)), "mittelfrist.html")


def _oeffnen(browser, datei, breite=1366):
    seite = browser.new_page(viewport={"width": breite, "height": 1000})
    seite.fehler = []
    seite.on("pageerror", lambda e: seite.fehler.append(str(e)))
    seite.goto(f"file://{datei}#vorhersage")
    seite.wait_for_timeout(400)
    return seite


def _serien(seite):
    return seite.evaluate("""() => { const c = {};
        document.querySelectorAll('#plot-mittelfrist [data-serie]').forEach(e => c[e.dataset.serie] = (c[e.dataset.serie] || 0) + 1);
        return c; }""")


def test_niederschlag_wird_auf_drei_stunden_normiert_und_nach_anteil_eingefaerbt(browser, mittelfrist):
    seite = _oeffnen(browser, mittelfrist)
    r = seite.evaluate("""() => { const T = window.__TESTMF__;
        const l = T.lauf('gfs'), s = T.niederschlagsschritte(l);
        const u = l.niederschlag.zeitpunkte_unix, m = l.niederschlag.mitglieder;
        // erwartete Menge im zweiten Schritt: Mittel der Mitgliederzuwaechse, auf 3 h normiert
        const stunden = (u[1] - u[0]) / 3600;
        const zuwachs = m.map(r => r[1] - r[0]);
        return { mittel: s[1].mittel, erwartet: zuwachs.reduce((a, b) => a + b, 0) / zuwachs.length * 3 / stunden,
                 anteil: s[1].anteil, anteilErwartet: zuwachs.filter(d => d >= 0.1).length / zuwachs.length,
                 deckkraft: [...document.querySelectorAll('#plot-mittelfrist [data-serie=niederschlag]')]
                   .map(e => +e.getAttribute('opacity')), anteile: [...document.querySelectorAll('#plot-mittelfrist [data-serie=niederschlag]')]
                   .map(e => +e.dataset.anteil) }; }""")
    seite.close()
    assert r["mittel"] == pytest.approx(r["erwartet"], abs=1e-9)
    assert r["anteil"] == pytest.approx(r["anteilErwartet"], abs=1e-9)
    assert r["deckkraft"], "keine Niederschlagsflaeche gezeichnet"
    # mehr Mitglieder mit Regen -> kraeftigere Farbe, nie ganz deckend und nie unsichtbar
    paare = sorted(zip(r["anteile"], r["deckkraft"]))
    assert all(a <= b for (_, a), (_, b) in zip(paare, paare[1:]))
    assert min(r["deckkraft"]) >= 0.1 and max(r["deckkraft"]) <= 0.85


def test_tagessymbole_stammen_aus_den_tageswettercodes(browser, mittelfrist):
    seite = _oeffnen(browser, mittelfrist)
    serien = _serien(seite)
    fehler = list(seite.fehler)
    seite.close()
    assert serien.get("tagessymbol", 0) >= 4 and serien.get("tageslinie", 0) >= 4
    assert serien.get("mittel") == 1 and serien.get("band") == 1
    assert not fehler, fehler


def test_modellvergleich_blendet_die_hauptlaeufe_aus(browser, mittelfrist):
    seite = _oeffnen(browser, mittelfrist)
    seite.locator("#hauptlaufEin-mittelfrist").check()
    assert "hauptlauf" in _serien(seite)
    seite.locator("#anderesEin-mittelfrist").check()
    seite.wait_for_timeout(120)
    mit = _serien(seite)
    gesperrt = seite.evaluate("""() => { const h = document.querySelector('#hauptlaufEin-mittelfrist');
        return [h.checked, h.disabled]; }""")
    legende = seite.locator("#leg-mittelfrist").inner_text()
    fehler = list(seite.fehler)
    seite.close()
    assert "hauptlauf" not in mit and gesperrt == [False, True]
    assert mit.get("anderes-mittel") == 1 and mit.get("anderes-band") == 2 and mit.get("anderes-niederschlag") == 1
    assert "tagessymbol" not in mit                 # Symbole entfallen beim Vergleich
    assert "ECMWF-IFS" in legende and "GFS" in legende
    assert not fehler, fehler


def test_achse_bleibt_beim_zuschalten_des_anderen_modells_stehen(browser, mittelfrist):
    """Die Skalen richten sich nur nach dem gewaehlten Modell; das andere darf aus dem Bild laufen."""
    seite = _oeffnen(browser, mittelfrist)
    skala = "() => { const s = document.querySelector('#plot-mittelfrist svg'); return [s.dataset.unten, s.dataset.oben, s.dataset.regenOben]; }"
    vorher = seite.evaluate(skala)
    seite.locator("#anderesEin-mittelfrist").check()
    seite.wait_for_timeout(120)
    nachher = seite.evaluate(skala)
    geklemmt = seite.evaluate("""() => {
        const e = document.querySelector('#plot-mittelfrist [data-serie=anderes-mittel]');
        return !!(e && e.parentNode.getAttribute('clip-path')); }""")
    fehler = list(seite.fehler)
    seite.close()
    assert vorher == nachher, (vorher, nachher)
    assert geklemmt, "Kurven des anderen Modells muessen am Diagrammrand abgeschnitten werden"
    assert not fehler, fehler


def test_tagessymbol_folgt_der_entscheidungsregel(browser, mittelfrist):
    """Hauptlauf-Code liefert die Art, das Ensemble entscheidet ueber den Niederschlag."""
    seite = _oeffnen(browser, mittelfrist)
    r = seite.evaluate("""() => { const t = window.__TESTMF__.tagesart;
        const tag = (p, pr, menge, temp) => ({ pNass: p, pRegen: pr, menge, temp, n: 20 });
        return {
          trocken:      t('klar',     tag(0.05, 0.00, 0.1, 10)),
          schauer:      t('klar',     tag(0.40, 0.10, 1.0, 10)),
          entregnet:    t('regen',    tag(0.10, 0.00, 0.2, 10)),
          regen:        t('klar',     tag(0.90, 0.80, 5.0, 10)),
          schnee:       t('klar',     tag(0.90, 0.80, 5.0, -2)),
          gewitter:     t('gewitter', tag(0.90, 0.80, 5.0, 10)),
          bedeckt:      t('bedeckt',  tag(0.05, 0.00, 0.1, 10)),
          ohneEnsemble: t('wolkig',   null),
        }; }""")
    arten = seite.evaluate("""() => [...document.querySelectorAll('#plot-mittelfrist [data-serie=tagessymbol]')]
        .map(e => [e.dataset.art, (e.querySelector('title') || {}).textContent || ''])""")
    fehler = list(seite.fehler)
    seite.close()
    assert r == {"trocken": "klar", "schauer": "schauer", "entregnet": "bedeckt", "regen": "regen",
                 "schnee": "schnee", "gewitter": "gewitter", "bedeckt": "bedeckt", "ohneEnsemble": "wolkig"}
    assert arten and all(a for a, _ in arten)
    assert all("% der Mitglieder" in titel for _, titel in arten), arten
    assert not fehler, fehler


def test_ohne_gespeicherten_lauf_erscheint_ein_hinweis(browser, tmp_path_factory):
    leer = _seite(tmp_path_factory.mktemp("mf_leer"), _daten([], []), "leer.html")
    seite = _oeffnen(browser, leer)
    text = seite.locator("#plot-mittelfrist").inner_text()
    fehler = list(seite.fehler)
    seite.close()
    assert "noch kein gespeicherter Lauf" in text and not fehler
