import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skripte"))
from gemeinsam import atomar_schreiben, atomar_schreiben_json, mittel, perzentil


def test_perzentil_median_ungerade():
    assert perzentil([1, 2, 3], 0.5) == 2


def test_perzentil_lineare_interpolation():
    # numpy-"linear"-Konvention: p90 von [1..10] (0-indiziert, 10 Werte)
    w = list(range(1, 11))  # 1..10
    # pos = 0.9 * 9 = 8.1 -> zwischen Index 8 (=9) und 9 (=10), 0.1 gewichtet
    assert abs(perzentil(w, 0.9) - 9.1) < 1e-9


def test_perzentil_einzelwert():
    assert perzentil([5.0], 0.1) == 5.0
    assert perzentil([5.0], 0.9) == 5.0


def test_perzentil_leer():
    assert perzentil([], 0.5) is None


def test_mittel_ignoriert_none():
    assert mittel([1.0, None, 3.0]) == 2.0


def test_atomar_schreiben_erstellt_datei(tmp_path):
    ziel = tmp_path / "unterordner" / "datei.txt"
    atomar_schreiben(ziel, "hallo")
    assert ziel.read_text(encoding="utf-8") == "hallo"
    # keine liegen gebliebene Temp-Datei
    assert list(tmp_path.rglob("*.tmp*")) == []


def test_atomar_schreiben_ueberschreibt_nicht_bei_absturz(tmp_path, monkeypatch):
    """Simuliert einen Absturz waehrend des Schreibens (write_text wirft) --
    die Zieldatei muss dann unveraendert (den alten Inhalt) behalten."""
    ziel = tmp_path / "datei.json"
    atomar_schreiben_json(ziel, {"alt": True})

    import gemeinsam

    orig_replace = gemeinsam.os.replace

    def kaputt(*a, **kw):
        raise RuntimeError("simulierter Absturz")

    monkeypatch.setattr(gemeinsam.os, "replace", kaputt)
    try:
        atomar_schreiben_json(ziel, {"alt": False, "neu": True})
    except RuntimeError:
        pass
    monkeypatch.setattr(gemeinsam.os, "replace", orig_replace)

    # alte, gueltige Datei ist noch da und unveraendert
    assert json.loads(ziel.read_text(encoding="utf-8")) == {"alt": True}
