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

