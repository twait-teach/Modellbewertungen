"""
Testet die im Browser laufende JS-Logik der Analyse-Seite (Witterungsvergleich,
MAE/Bias, Schwellenwert-Kontingenztafel) gegen frei erfundene, kontrollierte
Testdaten -- unabhaengig vom aktuellen Datenbestand im Repo. Nutzt Playwright,
um die echte Seite mit ausgetauschten DATEN zu laden und die ueber
window.__TEST__ freigegebenen reinen Funktionen aufzurufen.
"""
import datetime as dt
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

SEITE = Path(__file__).resolve().parent.parent / "skripte" / "vorlage.html"


def _seite_mit_testdaten(daten, name):
    """Baut aus der Vorlage (nicht aus docs/index.html, das schon eingebettete
    Echtdaten enthaelt) eine Testseite mit frei gewaehlten DATEN -- exakt nach
    demselben Muster wie skripte/bauen.py, nur mit Testdaten statt echtem Bestand."""
    vorlage = SEITE.read_text(encoding="utf-8")
    ersetzt = vorlage.replace("/*__DATEN__*/{}", json.dumps(daten, ensure_ascii=False))
    seite = ('<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
             + ersetzt.split("<style>", 1)[0]
             + "<style>" + ersetzt.split("<style>", 1)[1].split("</style>", 1)[0] + "</style>\n</head>\n<body>\n"
             + ersetzt.split("</style>", 1)[1] + "\n</body>\n</html>\n")
    pfad = SEITE.parent.parent / "docs" / name
    pfad.write_text(seite, encoding="utf-8")
    return pfad

# Ein Kalendertag-Lauf mit 14 Leads, an einem Datum weit in der Vergangenheit,
# damit alle Fenster (auch Tag 8-14) sicher als "vergangen" gelten.
LAUFDATUM = "2026-01-01"
ZIELE = [(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(1, 15)]
# Vorhersage: konstant 2 mm/Tag fuer ens und hl bei beiden Modellen
LEADS = [{
    "lead": i + 1, "ziel": ZIELE[i],
    "gfs": {"hl": 2.0, "ens": 2.0, "p10": 1.0, "p90": 3.0},
    "ecmwf": {"hl": 2.0, "ens": 2.0, "p10": 1.0, "p90": 3.0},
} for i in range(14)]

# Messungen: vollstaendig fuer Tag 1-3 und 4-7, aber Tag 8-14 hat eine Luecke
# (Tag 10 fehlt) -- dieses Fenster darf NICHT ausgewertet werden.
MESSUNGEN = {ZIELE[i]: 1.0 for i in range(9)}  # Tag 1..9 vorhanden
MESSUNGEN.update({ZIELE[i]: 1.0 for i in range(10, 14)})  # Tag 11..14 vorhanden, Tag 10 (Index 9) fehlt bewusst

# modelllaeufe: alle vier Modell/Quelle-Kombinationen korrekt am erwarteten
# 00-UTC-Lauf dieses Kalendertags -- der Standardfall fuer die uebrigen Tests.
def _modelllaeufe_korrekt(laufdatum):
    return {f"{m}/{q}": {"lauf": f"{laufdatum}T00:00Z", "verfuegbar_seit": f"{laufdatum}T06:00Z"}
            for m in ("gfs", "ecmwf") for q in ("hl", "ens")}

DATEN_TEST = {
    "messungen": MESSUNGEN,
    "history": {},
    "forecasts": {LAUFDATUM: {"lauf": LAUFDATUM, "modelllaeufe": _modelllaeufe_korrekt(LAUFDATUM), "leads": LEADS}},
    "vorhersage": {"gfs": [], "ecmwf": []},
    "gebaut": "2026-09-17T00:00Z",
}


def test_witterungsvergleich_schliesst_unvollstaendiges_fenster_aus():
    testdatei = _seite_mit_testdaten(DATEN_TEST, "_test_index.html")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        fehler = []
        page.on("pageerror", lambda exc: fehler.append(str(exc)))
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(200)
        assert not fehler, f"JS-Laufzeitfehler: {fehler}"

        ergebnis = page.evaluate("""() => {
            const t = window.__TEST__;
            const f13 = t.FENSTER.find(f => f.id === '1-3');
            const f47 = t.FENSTER.find(f => f.id === '4-7');
            const f814 = t.FENSTER.find(f => f.id === '8-14');
            return {
                f13: t.fensterAuswertung(f13, 'gfs', 'ens'),
                f47: t.fensterAuswertung(f47, 'gfs', 'ens'),
                f814: t.fensterAuswertung(f814, 'gfs', 'ens'),
                kategorie_trocken: t.kategorie(1, f13),
                kategorie_maessig: t.kategorie(10, f13),
                kategorie_nass: t.kategorie(30, f13),
            };
        }""")
        browser.close()
    testdatei.unlink()

    # Fenster 1-3 und 4-7: vollstaendig, muessen ausgewertet werden
    assert len(ergebnis["f13"]) == 1
    assert ergebnis["f13"][0]["F"] == 6.0  # 3 Tage x 2mm
    assert ergebnis["f13"][0]["O"] == 3.0  # 3 Tage x 1mm
    assert ergebnis["f13"][0]["E"] == 3.0
    assert len(ergebnis["f47"]) == 1
    # Fenster 8-14: Messluecke an einem Tag -> darf NICHT ausgewertet werden
    assert len(ergebnis["f814"]) == 0, "Fenster mit luekenhafter Messreihe wurde faelschlich ausgewertet"

    # Fenster 1-3 (3 Tage): Schwellen 1.5*3=4.5 / 6*3=18 -> 1 mm ist trocken, 10 maessig, 30 sehr nass
    assert ergebnis["kategorie_trocken"] == "trocken"
    assert ergebnis["kategorie_maessig"] == "mäßig nass"
    assert ergebnis["kategorie_nass"] == "sehr nass"


def test_mae_und_bias_grundrechenarten():
    testdatei = _seite_mit_testdaten(DATEN_TEST, "_test_index2.html")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(200)
        ergebnis = page.evaluate("""() => {
            const t = window.__TEST__;
            const paare = [{ tag: 'a', vor: 3, ist: 1 }, { tag: 'b', vor: 0, ist: 2 }];
            return { mae: t.mae(paare), bias: t.bias(paare) };
        }""")
        browser.close()
    testdatei.unlink()
    # |3-1|=2, |0-2|=2 -> MAE = 2
    assert ergebnis["mae"] == 2
    # (3-1)+(0-2) = 0 -> Bias = 0
    assert ergebnis["bias"] == 0


# ---------------------------------------------------------------- Punkt 2: Altdaten mit falscher/abweichender Initialisierung
# Reproduziert exakt das reale Muster aus daten/forecasts_2026-09-14.json (alle
# vier Modell/Quelle-Kombinationen faelschlich vom 06Z- statt 00Z-Lauf) und
# daten/forecasts_2026-09-15.json (nur ecmwf/ens vom vorherigen 18Z-Lauf,
# alles andere korrekt vom 00Z-Lauf desselben Tages).
TAG_A = "2026-02-01"   # entspricht dem Muster von 09-14: alles falsch (06Z)
TAG_B = "2026-02-02"   # entspricht dem Muster von 09-15: nur ecmwf/ens falsch
ZIEL_A = (dt.date(2026, 2, 1) + dt.timedelta(days=1)).isoformat()
ZIEL_B = (dt.date(2026, 2, 2) + dt.timedelta(days=1)).isoformat()

FORECASTS_KONTAMINIERT = {
    TAG_A: {
        "lauf": TAG_A,
        "modelllaeufe": {f"{m}/{q}": {"lauf": f"{TAG_A}T06:00Z"} for m in ("gfs", "ecmwf") for q in ("hl", "ens")},
        "leads": [{"lead": 1, "ziel": ZIEL_A,
                   "gfs": {"hl": 99.0, "ens": 99.0, "p10": 90, "p90": 100},
                   "ecmwf": {"hl": 99.0, "ens": 99.0, "p10": 90, "p90": 100}}],
    },
    TAG_B: {
        "lauf": TAG_B,
        "modelllaeufe": {
            "gfs/hl": {"lauf": f"{TAG_B}T00:00Z"}, "gfs/ens": {"lauf": f"{TAG_B}T00:00Z"},
            "ecmwf/hl": {"lauf": f"{TAG_B}T00:00Z"},
            "ecmwf/ens": {"lauf": "2026-02-01T18:00Z"},  # abweichender Vorlauf -- NUR diese Kombination
        },
        "leads": [{"lead": 1, "ziel": ZIEL_B,
                   "gfs": {"hl": 4.0, "ens": 4.0, "p10": 2, "p90": 6},
                   "ecmwf": {"hl": 4.0, "ens": 77.0, "p10": 70, "p90": 80}}],
    },
}
DATEN_KONTAMINIERT = {
    "messungen": {ZIEL_A: 1.0, ZIEL_B: 1.0},
    "history": {},
    "forecasts": FORECASTS_KONTAMINIERT,
    "vorhersage": {"gfs": [], "ecmwf": []},
    "gebaut": "2026-09-17T00:00Z",
}


def test_laufvalidierung_schliesst_falsche_initialisierung_pro_modell_und_quelle_aus():
    testdatei = _seite_mit_testdaten(DATEN_KONTAMINIERT, "_test_index_kontaminiert.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        fehler = []
        page.on("pageerror", lambda exc: fehler.append(str(exc)))
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(200)
        assert not fehler, f"JS-Laufzeitfehler: {fehler}"

        ergebnis = page.evaluate("""() => {
            const t = window.__TEST__;
            return {
                // Tag A (alles 06Z): darf fuer KEIN Modell/KEINE Quelle auftauchen
                gfs_ens_tagA: t.paare('gfs', 1, 'ens').some(p => p.tag === '%s'),
                ecmwf_hl_tagA: t.paare('ecmwf', 1, 'hl').some(p => p.tag === '%s'),
                // Tag B: gfs/ens und ecmwf/hl korrekt (00Z) -> muessen auftauchen
                gfs_ens_tagB: t.paare('gfs', 1, 'ens').find(p => p.tag === '%s'),
                ecmwf_hl_tagB: t.paare('ecmwf', 1, 'hl').find(p => p.tag === '%s'),
                // Tag B: ecmwf/ens war noch der 18Z-Lauf vom Vortag -> darf NICHT auftauchen
                ecmwf_ens_tagB: t.paare('ecmwf', 1, 'ens').some(p => p.tag === '%s'),
                laufPasstFuer_A: t.laufPasstFuer(%s, 'gfs', 'hl'),
                laufPasstFuer_B_ecmwf_ens: t.laufPasstFuer(%s, 'ecmwf', 'ens'),
                laufPasstFuer_B_ecmwf_hl: t.laufPasstFuer(%s, 'ecmwf', 'hl'),
            };
        }""" % (ZIEL_A, ZIEL_A, ZIEL_B, ZIEL_B, ZIEL_B,
                 json.dumps(FORECASTS_KONTAMINIERT[TAG_A]),
                 json.dumps(FORECASTS_KONTAMINIERT[TAG_B]),
                 json.dumps(FORECASTS_KONTAMINIERT[TAG_B])))
        browser.close()
    testdatei.unlink()

    assert ergebnis["gfs_ens_tagA"] is False, "Tag mit 06Z-Lauf statt 00Z wurde faelschlich in die Ensemble-Guete uebernommen"
    assert ergebnis["ecmwf_hl_tagA"] is False, "Tag mit 06Z-Lauf statt 00Z wurde faelschlich in die Hauptlauf-Guete uebernommen"
    assert ergebnis["gfs_ens_tagB"] is not None and ergebnis["gfs_ens_tagB"]["vor"] == 4.0
    assert ergebnis["ecmwf_hl_tagB"] is not None and ergebnis["ecmwf_hl_tagB"]["vor"] == 4.0
    assert ergebnis["ecmwf_ens_tagB"] is False, "ecmwf/ens vom abweichenden 18Z-Vorlauf wurde faelschlich uebernommen"
    assert ergebnis["laufPasstFuer_A"] is False
    assert ergebnis["laufPasstFuer_B_ecmwf_ens"] is False
    assert ergebnis["laufPasstFuer_B_ecmwf_hl"] is True


def test_fensterauswertung_schliesst_kontaminierten_lauf_pro_quelle_aus():
    """Fenster 1-3 kann mit dieser Fixture nicht vollstaendig ausgewertet werden
    (nur 1 Lead je Tag gespeichert), deshalb wird laufPasstFuer direkt und ueber
    paare() geprueft -- fensterAuswertung nutzt dieselbe Pruefung, siehe oben."""
    testdatei = _seite_mit_testdaten(DATEN_KONTAMINIERT, "_test_index_kontaminiert2.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(200)
        ergebnis = page.evaluate("""() => {
            const t = window.__TEST__;
            const f = { id: '1-3', von: 1, bis: 1, label: 'Test' };
            return {
                ecmwf_ens: t.fensterAuswertung(f, 'ecmwf', 'ens'),
                ecmwf_hl: t.fensterAuswertung(f, 'ecmwf', 'hl'),
            };
        }""")
        browser.close()
    testdatei.unlink()
    # ecmwf/ens: Tag A (06Z) UND Tag B (18Z-Vorlauf) beide ungueltig -> 0 Treffer
    assert len(ergebnis["ecmwf_ens"]) == 0
    # ecmwf/hl: Tag A ungueltig, Tag B gueltig -> genau 1 Treffer
    assert len(ergebnis["ecmwf_hl"]) == 1
    assert ergebnis["ecmwf_hl"][0]["F"] == 4.0


# ---------------------------------------------------------------- Punkt 4: fensterabhaengige Witterungskategorien
def test_kategorie_schwellen_skalieren_mit_fensterlaenge():
    testdatei = _seite_mit_testdaten(DATEN_TEST, "_test_index_schwellen.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(200)
        ergebnis = page.evaluate("""() => {
            const t = window.__TEST__;
            return t.FENSTER.map(f => ({ id: f.id, ...t.kategorieSchwellen(f) }));
        }""")
        browser.close()
    testdatei.unlink()

    schwellen = {e["id"]: e for e in ergebnis}
    # 1-3 (3 Tage): 1.5*3=4.5 / 6*3=18
    assert schwellen["1-3"]["trocken"] == 4.5
    assert schwellen["1-3"]["maessig"] == 18.0
    # 4-7 (4 Tage): 1.5*4=6 / 6*4=24
    assert schwellen["4-7"]["trocken"] == 6.0
    assert schwellen["4-7"]["maessig"] == 24.0
    # 8-14 (7 Tage): 1.5*7=10.5 / 6*7=42
    assert schwellen["8-14"]["trocken"] == 10.5
    assert schwellen["8-14"]["maessig"] == 42.0
    # Die drei Fenster muessen sich tatsaechlich unterscheiden (Kern der Anforderung)
    assert len({schwellen[f]["trocken"] for f in schwellen}) == 3
    assert len({schwellen[f]["maessig"] for f in schwellen}) == 3


def test_kategorie_grenzfaelle_je_fenster():
    testdatei = _seite_mit_testdaten(DATEN_TEST, "_test_index_grenzfaelle.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(200)
        ergebnis = page.evaluate("""() => {
            const t = window.__TEST__;
            const f13 = t.FENSTER.find(f => f.id === '1-3');   // trocken<4.5, maessig<18
            const f814 = t.FENSTER.find(f => f.id === '8-14'); // trocken<10.5, maessig<42
            return {
                f13_knapp_trocken: t.kategorie(4.4, f13),
                f13_grenze_maessig: t.kategorie(4.5, f13),
                f13_knapp_nass: t.kategorie(17.9, f13),
                f13_grenze_nass: t.kategorie(18.0, f13),
                // derselbe absolute Wert (12 mm) ist im laengeren Fenster (8-14, Schwelle 10.5-42)
                // noch "mäßig nass", im kuerzeren Fenster (1-3, Schwelle 4.5-18) schon "sehr nass"
                // waere er -- hier bewusst ueber der 1-3-Schwelle (18) gewaehlt, um den Unterschied
                // eindeutig zu zeigen: das ist der Kern von Punkt 4.
                zwanzig_mm_im_kurzen_fenster: t.kategorie(20, f13),
                zwanzig_mm_im_langen_fenster: t.kategorie(20, f814),
            };
        }""")
        browser.close()
    testdatei.unlink()
    assert ergebnis["f13_knapp_trocken"] == "trocken"
    assert ergebnis["f13_grenze_maessig"] == "mäßig nass"
    assert ergebnis["f13_knapp_nass"] == "mäßig nass"
    assert ergebnis["f13_grenze_nass"] == "sehr nass"
    assert ergebnis["zwanzig_mm_im_kurzen_fenster"] == "sehr nass"
    assert ergebnis["zwanzig_mm_im_langen_fenster"] == "mäßig nass"



# ---------------------------------------------------------------- Vorhersage-Seite: drei unabhaengige Bereiche
def _lauf(init, *, mit_temperatur=True, horizont=3, mitglieder_n=3, temp_offset=0.0):
    """Baut ein Laufdokument wie sammeln_vorhersage.py es schreibt.
    mit_temperatur=False erzeugt bewusst einen ALTEN Lauf ohne Temperaturfelder."""
    ziele = [(dt.date(2026, 2, 1) + dt.timedelta(days=i)).isoformat() for i in range(1, horizont + 1)]
    d = {
        "modell": "gfs", "modellname": "GFS", "ensemble_datensatz": "gfs_seamless",
        "init": init, "verfuegbar_seit": init, "abgerufen": init,
        "horizont_tage": horizont, "mitglieder_n": mitglieder_n,
        "leads": list(range(1, horizont + 1)), "ziele": ziele,
        "vollstaendig": True, "hinweise": [],
    }
    if mit_temperatur:
        d["zeitauflosung"] = "modellnativ-v1"
        # bewusst NEGATIVE Werte, um die Achsenskalierung zu pruefen
        werte = [-5.0 + temp_offset, 0.0 + temp_offset, 4.0 + temp_offset][:horizont]
        zeiten = [f"2026-02-02T{stunde:02d}:00" for stunde in range(horizont)]
        zeitpunkte_unix = [1769990400 + stunde * 3600 for stunde in range(horizont)]
        for feld in ("temperatur_2m", "temperatur_850hpa"):
            d[feld] = {
                "zeiten": zeiten, "zeitpunkte_unix": zeitpunkte_unix, "zeitzone": "Europe/Berlin",
                "kontrolllauf": werte,
                "mitglieder": [[w + i * 0.5 for w in werte] for i in range(mitglieder_n)],
                "hauptlauf": None,
                "mittel": werte, "p10": [w - 1 for w in werte], "p50": werte, "p90": [w + 1 for w in werte],
                "min": [w - 2 for w in werte], "max": [w + 2 for w in werte], "n": [mitglieder_n] * horizont,
            }
        regen = [1.0, 2.0, 3.0][:horizont]
        d["niederschlag"] = {
            "zeiten": zeiten, "zeitpunkte_unix": zeitpunkte_unix, "zeitzone": "Europe/Berlin",
            "kontrolllauf": regen, "mitglieder": [regen[:] for _ in range(mitglieder_n)],
            "hauptlauf": None, "mittel": regen, "p10": [0.5, 1.5, 2.5][:horizont],
            "p50": regen, "p90": [1.5, 2.5, 3.5][:horizont],
            "min": [0.0, 1.0, 2.0][:horizont], "max": [2.0, 3.0, 4.0][:horizont],
            "n": [mitglieder_n] * horizont,
        }
    else:
        d["temperatur_2m"] = None
        d["temperatur_850hpa"] = None
    return d


DATEN_VORHERSAGE = {
    "messungen": {}, "history": {}, "forecasts": {},
    "vorhersage": {
        # absteigend nach voller Initialisierung, ueber eine Tagesgrenze hinweg
        "gfs": [
            _lauf("2026-02-02T00:00Z"),
            _lauf("2026-02-01T18:00Z", temp_offset=1.0),
            _lauf("2026-02-01T12:00Z", mit_temperatur=False),  # ALTER Lauf ohne Temperaturdaten
        ],
        "ecmwf": [],
    },
    "gebaut": "2026-09-18T00:00Z",
}


def _seite_vorhersage(name="_test_vorhersage.html", daten=None):
    return _seite_mit_testdaten(daten or DATEN_VORHERSAGE, name)


def test_drei_bereiche_haben_unabhaengige_zustaende():
    testdatei = _seite_vorhersage("_test_bereiche.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        fehler = []
        page.on("pageerror", lambda exc: fehler.append(str(exc)))
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(250)
        assert not fehler, f"JS-Laufzeitfehler: {fehler}"

        ergebnis = page.evaluate("""() => {
            const t = window.__TEST__;
            return {
                bereiche: t.BEREICHE.map(b => b.id),
                dom_reihenfolge: Array.from(document.querySelectorAll('#seite-vorhersage > section'))
                    .map(s => s.id),
                // Zustaende muessen getrennte Objekte sein, nicht dasselbe
                getrennt: t.ZUSTAND.temp2m !== t.ZUSTAND.niederschlag
                          && t.ZUSTAND.niederschlag !== t.ZUSTAND.temp850,
                // je Bereich existieren eigene Bedienelemente
                eigene_elemente: t.BEREICHE.every(b =>
                    document.querySelector(`#modellwahl-${b.id}`)
                    && document.querySelector(`#laufwahl-${b.id}`)
                    && document.querySelector(`#mitgliederEin-${b.id}`)
                    && document.querySelector(`#chart-${b.id}`)
                    && document.querySelector(`#leg-${b.id}`)
                    && document.querySelector(`#tab-${b.id}`)
                    && document.querySelector(`#laufinfoZeile-${b.id}`)
                    && document.querySelector(`#laufwarnung-${b.id}`)),
            };
        }""")
        browser.close()
    testdatei.unlink()
    assert ergebnis["bereiche"] == ["temp2m", "temp850", "niederschlag"]  # geforderte Reihenfolge
    assert ergebnis["dom_reihenfolge"] == ["s-temp2m", "s-temp850", "s-niederschlag"]
    assert ergebnis["getrennt"] is True
    assert ergebnis["eigene_elemente"] is True


def test_laufauswahl_und_mitgliederschalter_wirken_nur_im_eigenen_bereich():
    testdatei = _seite_vorhersage("_test_bereiche_unabhaengig.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        fehler = []
        page.on("pageerror", lambda exc: fehler.append(str(exc)))
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(250)

        # im Niederschlagsbereich den zweiten Lauf waehlen, Mitglieder ausschalten
        page.locator("#laufwahl-niederschlag button").nth(1).click()
        page.locator("#mitgliederEin-niederschlag").click()
        page.wait_for_timeout(150)

        z = page.evaluate("""() => {
            const Z = window.__TEST__.ZUSTAND;
            return {
                t2_lauf: Z.temp2m.laufIndex, regen_lauf: Z.niederschlag.laufIndex, t850_lauf: Z.temp850.laufIndex,
                t2_mit: Z.temp2m.mitglieder, regen_mit: Z.niederschlag.mitglieder, t850_mit: Z.temp850.mitglieder,
            };
        }""")
        browser.close()
        assert not fehler, f"JS-Laufzeitfehler: {fehler}"
    testdatei.unlink()
    assert z["regen_lauf"] == 1 and z["t2_lauf"] == 0 and z["t850_lauf"] == 0
    assert z["regen_mit"] is False and z["t2_mit"] is True and z["t850_mit"] is True


def test_alter_lauf_ohne_modellraster_zeigt_meldung_statt_fehler():
    testdatei = _seite_vorhersage("_test_alter_lauf.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        fehler = []
        page.on("pageerror", lambda exc: fehler.append(str(exc)))
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(250)

        # dritter Lauf (Index 2) ist der alte ohne Temperaturdaten
        page.locator("#laufwahl-temp2m button").nth(2).click()
        page.wait_for_timeout(200)
        text = page.locator("#laufwarnung-temp2m").inner_text()
        # Auch Niederschlag darf nicht mehr aus dem alten Tagesformat stammen.
        page.locator("#laufwahl-niederschlag button").nth(2).click()
        page.wait_for_timeout(200)
        regen_hat_pfade = page.evaluate("() => document.querySelectorAll('#chart-niederschlag path').length > 0")
        browser.close()
        assert not fehler, f"JS-Laufzeitfehler bei altem Lauf ohne Temperatur: {fehler}"
    testdatei.unlink()
    assert "modellnahen 3-/6-Stunden-Raster" in text
    assert regen_hat_pfade is False


def test_negative_temperaturen_werden_dargestellt():
    testdatei = _seite_vorhersage("_test_negativ.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        fehler = []
        page.on("pageerror", lambda exc: fehler.append(str(exc)))
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(250)
        # Achsenbeschriftungen des 2m-Diagramms einsammeln
        labels = page.evaluate("""() => Array.from(document.querySelectorAll('#chart-temp2m text.ax'))
            .map(t => t.textContent).filter(s => /^-?\\d/.test(s.replace(',', '.')))""")
        pfade = page.evaluate("() => document.querySelectorAll('#chart-temp2m path').length")
        referenzen = page.evaluate("() => document.querySelectorAll('#chart-temp2m [data-serie=\"temperatur-referenz\"]').length")
        browser.close()
        assert not fehler, f"JS-Laufzeitfehler: {fehler}"
    testdatei.unlink()
    # Fixture enthaelt Werte bis -7 (min) -> mindestens eine negative Achsenbeschriftung
    assert any(s.strip().startswith("-") or s.strip().startswith("−") for s in labels), f"keine negative Achse gefunden: {labels}"
    assert all("," not in s and "." not in s for s in labels), f"Temperaturachse ist nicht ganzzahlig: {labels}"
    assert referenzen == 1
    assert pfade > 0


def test_fester_statusraum_verhindert_springen_beim_modellwechsel():
    gfs = _lauf("2026-02-02T00:00Z")
    gfs["ensemble_vollstaendig"] = True
    gfs["hauptlauf_vollstaendig"] = False
    gfs["vollstaendig"] = False
    ecmwf = json.loads(json.dumps(gfs))
    ecmwf.update({"modell": "ecmwf", "modellname": "ECMWF-IFS", "vollstaendig": True,
                  "hauptlauf_vollstaendig": True})
    for feld in ("temperatur_2m", "temperatur_850hpa", "niederschlag"):
        ecmwf[feld]["kontrolllauf"] = None
        ecmwf[feld]["hauptlauf"] = ecmwf[feld]["mittel"][:]
    daten = {"messungen": {}, "history": {}, "forecasts": {},
             "vorhersage": {"gfs": [gfs], "ecmwf": [ecmwf]}, "gebaut": "2026-09-19T00:00Z"}
    testdatei = _seite_vorhersage("_test_fester_statusraum.html", daten)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(200)
        ecmwf_top = page.locator("#chart-temp2m").bounding_box()["y"]
        statushoehe = page.locator("#laufwarnung-temp2m").bounding_box()["height"]
        page.locator('#modellwahl-temp2m button', has_text="GFS").click()
        page.wait_for_timeout(100)
        gfs_top = page.locator("#chart-temp2m").bounding_box()["y"]
        meldung = page.locator("#laufwarnung-temp2m").inner_text()
        browser.close()
    testdatei.unlink()
    assert statushoehe == 48
    assert gfs_top == ecmwf_top
    assert "Hauptlauf wird automatisch nachgetragen" in meldung


def test_laufbeschriftung_zeigt_datum_und_uhrzeit():
    testdatei = _seite_vorhersage("_test_labels.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(250)
        labels = page.evaluate("() => Array.from(document.querySelectorAll('#laufwahl-temp2m button')).map(b => b.textContent)")
        via_funktion = page.evaluate("""() => {
            const t = window.__TEST__;
            return [
                t.laufLabel({ init: '2026-02-02T00:00Z' }, 0),
                t.laufLabel({ init: '2026-02-01T18:00Z' }, 1),
            ];
        }""")
        browser.close()
    testdatei.unlink()
    # kein "vorheriger Lauf"/"davorliegender Lauf" mehr, stattdessen echtes Datum
    assert not any("vorheriger" in s or "davorliegender" in s for s in labels), labels
    assert via_funktion[0] == "aktuell · 02.02., 00 UTC"
    assert via_funktion[1] == "01.02., 18 UTC"
    assert all(("UTC" in s and "." in s) for s in labels), labels


def test_laeufe_sind_chronologisch_absteigend_ueber_tagesgrenze():
    """Die Reihenfolge der Buttons muss der Reihenfolge der Laeufe im Datenpaket
    entsprechen, und die ist (von bauen.py) streng absteigend nach voller
    Initialisierung sortiert -- auch ueber eine Tagesgrenze hinweg."""
    testdatei = _seite_vorhersage("_test_sortierung.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(250)
        inits = page.evaluate("() => (window.DATEN ? null : null) || Array.from(document.querySelectorAll('#laufwahl-temp2m button')).map(b => b.textContent)")
        browser.close()
    testdatei.unlink()
    # Fixture: 02.02. 00 UTC, dann 01.02. 18 UTC, dann 01.02. 12 UTC
    assert "02.02., 00 UTC" in inits[0]
    assert "01.02., 18 UTC" in inits[1]
    assert "01.02., 12 UTC" in inits[2]


def test_temperatur_wird_nicht_akkumuliert_dargestellt():
    """datenAusLauf() muss fuer Temperatur die rohen (nicht aufsummierten)
    Reihen liefern, fuer Niederschlag dagegen die kumulierten Felder."""
    testdatei = _seite_vorhersage("_test_nicht_akkumuliert.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(250)
        ergebnis = page.evaluate("""() => {
            const t = window.__TEST__;
            const lauf = {
                zeitauflosung: 'modellnativ-v1',
                temperatur_2m: { zeiten: ['2026-02-02T01:00', '2026-02-02T02:00', '2026-02-02T08:00'],
                                 zeitpunkte_unix: [0, 3600, 25200],
                                 kontrolllauf: [-5, 0, 4], mitglieder: [[-5, 0, 4]], hauptlauf: null,
                                 mittel: [-5, 0, 4], p10: [-6, -1, 3], p90: [-4, 1, 5], n: [1, 1, 1] },
                temperatur_850hpa: { kontrolllauf: [-5, 0, 4], mitglieder: [[-5, 0, 4]], hauptlauf: null,
                                     mittel: [-5, 0, 4], p10: [-6, -1, 3], p90: [-4, 1, 5], n: [1, 1, 1] },
                niederschlag: { zeiten: ['2026-02-02T01:00', '2026-02-02T04:00', '2026-02-02T07:00'],
                                 zeitpunkte_unix: [0, 10800, 21600],
                                 kontrolllauf: [0, 3, 6], mitglieder: [[0, 3, 6]], hauptlauf: null,
                                 mittel: [0, 3, 6], p10: [0, 3, 6], p90: [0, 3, 6], n: [1, 1, 1] },
            };
            const bTemp = t.BEREICHE.find(b => b.id === 'temp2m');
            const bRegen = t.BEREICHE.find(b => b.id === 'niederschlag');
            const b850 = t.BEREICHE.find(b => b.id === 'temp850');
            return {
                temp: t.datenAusLauf(bTemp, lauf),
                regen: t.datenAusLauf(bRegen, lauf),
                fehlend: t.datenAusLauf(b850, lauf),
                zeitachse: t.zeitachsenWerte(t.datenAusLauf(bTemp, lauf), 3),
                temp_akkumuliert_flag: bTemp.akkumuliert,
                regen_akkumuliert_flag: bRegen.akkumuliert,
            };
        }""")
        browser.close()
    testdatei.unlink()
    assert ergebnis["temp"]["mittel"] == [-5, 0, 4]        # roh, nicht aufsummiert
    assert ergebnis["regen"]["mittel"] == [0, 3, 6]        # zeitaufgeloest kumulierte Felder
    assert ergebnis["zeitachse"] == [0, 3600, 25200]        # 1h, danach 6h: nicht indexbasiert gestaucht
    assert ergebnis["temp_akkumuliert_flag"] is False
    assert ergebnis["regen_akkumuliert_flag"] is True
    assert ergebnis["fehlend"]["verfuegbar"] is False      # altes Tagesformat ohne Zeitachse -> nicht verfuegbar


def test_modellfarben_und_haupt_kontrolllauf_linien():
    gfs = _lauf("2026-02-02T00:00Z")
    ecmwf = json.loads(json.dumps(gfs))
    ecmwf.update({"modell": "ecmwf", "modellname": "ECMWF-IFS", "ensemble_datensatz": "ecmwf_ifs025"})
    for lauf in (gfs, ecmwf):
        for feld in ("temperatur_2m", "temperatur_850hpa", "niederschlag"):
            lauf[feld]["hauptlauf"] = lauf[feld]["mittel"][:]
    # Selbst wenn ein Altbestand noch eine Basisreihe traegt, darf sie beim
    # ECMWF nicht als zusaetzlicher Kontrolllauf erscheinen.
    for feld in ("temperatur_2m", "temperatur_850hpa", "niederschlag"):
        ecmwf[feld]["kontrolllauf"] = ecmwf[feld]["hauptlauf"][:]

    daten = {
        "messungen": {}, "history": {}, "forecasts": {},
        "vorhersage": {"gfs": [gfs], "ecmwf": [ecmwf]},
        "gebaut": "2026-09-19T00:00Z",
    }
    testdatei = _seite_vorhersage("_test_linienfarben.html", daten)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{testdatei}")
        page.wait_for_timeout(250)

        ecmwf_stand = page.evaluate("""() => ({
            temp: document.querySelector('#chart-temp2m [data-serie="ensemble-mittel"]')?.getAttribute('stroke'),
            regen: document.querySelector('#chart-niederschlag [data-serie="ensemble-mittel"]')?.getAttribute('stroke'),
            kontrolle: !!document.querySelector('#chart-temp2m [data-serie="kontrolllauf"]'),
            hauptFarbe: document.querySelector('#chart-temp2m [data-serie="hauptlauf"]')?.getAttribute('stroke'),
            hauptGestrichelt: document.querySelector('#chart-temp2m [data-serie="hauptlauf"]')?.hasAttribute('stroke-dasharray'),
            legende: document.querySelector('#leg-temp2m').textContent,
        })""")
        page.locator('#modellwahl-temp2m button', has_text="GFS").click()
        gfs_stand = page.evaluate("""() => ({
            temp: document.querySelector('#chart-temp2m [data-serie="ensemble-mittel"]')?.getAttribute('stroke'),
            kontrolleFarbe: document.querySelector('#chart-temp2m [data-serie="kontrolllauf"]')?.getAttribute('stroke'),
            kontrolleGestrichelt: document.querySelector('#chart-temp2m [data-serie="kontrolllauf"]')?.getAttribute('stroke-dasharray'),
            hauptFarbe: document.querySelector('#chart-temp2m [data-serie="hauptlauf"]')?.getAttribute('stroke'),
            hauptGestrichelt: document.querySelector('#chart-temp2m [data-serie="hauptlauf"]')?.hasAttribute('stroke-dasharray'),
        })""")
        browser.close()
    testdatei.unlink()

    assert ecmwf_stand["temp"] == "#b77900"
    assert ecmwf_stand["regen"] == "#63a9dd"
    assert ecmwf_stand["kontrolle"] is False
    assert "Kontrolllauf" not in ecmwf_stand["legende"]
    assert ecmwf_stand["hauptFarbe"] == "var(--ink)"
    assert ecmwf_stand["hauptGestrichelt"] is False
    assert gfs_stand["temp"] == "#c1500f"
    assert gfs_stand["kontrolleFarbe"] == "var(--ink)"
    assert gfs_stand["kontrolleGestrichelt"] == "7 3.5"
    assert gfs_stand["hauptFarbe"] == "var(--ink)"
    assert gfs_stand["hauptGestrichelt"] is False
