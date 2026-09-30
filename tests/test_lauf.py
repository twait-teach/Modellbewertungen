"""Pruefungen fuer den Serverbetrieb auf dem eigenen Webspace:
das Laufskript (skripte/lauf.sh) und den Cron-Startknopf (docs/cron.php).

Beides laesst sich hier nicht ausfuehren -- es gibt keinen Webserver und keine
Schnittstellen. Geprueft wird deshalb, was ohne Ausfuehrung pruefbar ist:
Syntax, Reihenfolge der Schritte und die Schutzmassnahmen des Startknopfes.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
LAUF = WURZEL / "skripte" / "lauf.sh"
CRON = WURZEL / "docs" / "cron.php"


def test_laufskript_ist_syntaktisch_gueltig():
    assert LAUF.exists(), "skripte/lauf.sh fehlt"
    ergebnis = subprocess.run(["sh", "-n", str(LAUF)], capture_output=True, text=True)
    assert ergebnis.returncode == 0, ergebnis.stderr


def test_laufskript_haelt_die_reihenfolge_des_workflows_ein():
    """Erst Daten holen, dann bauen, dann sichern -- nie umgekehrt."""
    text = LAUF.read_text(encoding="utf-8")
    reihenfolge = ["sammeln_vorhersage.py", "sammeln_48h.py", "sammeln.py",
                   "historie.py", "bauen.py", "git add", "git commit", "git push"]
    stellen = [text.index(s) for s in reihenfolge if s in text]
    assert len(stellen) == len(reihenfolge), "ein Schritt fehlt im Laufskript"
    assert stellen == sorted(stellen), "die Schritte stehen in falscher Reihenfolge"


def test_laufskript_baut_nur_bei_geaenderten_daten():
    text = LAUF.read_text(encoding="utf-8")
    assert "git status --porcelain -- daten" in text
    # Der Bau steht hinter der Pruefung, nicht davor.
    assert text.index("git status --porcelain -- daten") < text.index("bauen.py")


def test_laufskript_sperrt_gegen_gleichzeitige_laeufe():
    """Zwei gleichzeitige Laeufe wuerden sich beim Schreiben in die Quere kommen."""
    text = LAUF.read_text(encoding="utf-8")
    assert "mkdir" in text and "sperre" in text.lower()
    assert "trap" in text, "die Sperre muss auch bei Abbruch wieder verschwinden"


@pytest.mark.skipif(shutil.which("php") is None, reason="PHP hier nicht vorhanden")
def test_cron_php_ist_syntaktisch_gueltig():
    ergebnis = subprocess.run(["php", "-l", str(CRON)], capture_output=True, text=True)
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr


def test_cron_php_verlangt_ein_geheimwort_und_enthaelt_keines():
    text = CRON.read_text(encoding="utf-8")
    assert "hash_equals" in text, "Vergleich muss zeitunabhaengig sein"
    assert "403" in text, "ohne Geheimwort muss der Aufruf abgelehnt werden"
    # Das Geheimwort steht ausserhalb des Webverzeichnisses, nie in der Datei.
    assert "cron-schluessel.txt" in text
    assert not re.search(r"\$erwartet\s*=\s*['\"]", text), "kein fest eingetragenes Geheimwort"


def test_cron_php_startet_im_hintergrund():
    """Sonst schneidet die Zeitgrenze des Webservers den Lauf mittendrin ab."""
    text = CRON.read_text(encoding="utf-8")
    assert "nohup" in text and text.rstrip().count("&") >= 1
    assert "skripte/lauf.sh" in text


# --------------------------------------------------------------- Stationslauf

STATION = WURZEL / "skripte" / "lauf_station.sh"


def test_stationsskript_ist_syntaktisch_gueltig():
    assert STATION.exists(), "skripte/lauf_station.sh fehlt"
    ergebnis = subprocess.run(["sh", "-n", str(STATION)], capture_output=True, text=True)
    assert ergebnis.returncode == 0, ergebnis.stderr


def test_stationsskript_haelt_die_reihenfolge_ein():
    text = STATION.read_text(encoding="utf-8")
    reihenfolge = ["station_netatmo.py", "bauen_station.py", "git add", "git commit", "git push"]
    stellen = [text.index(s) for s in reihenfolge if s in text]
    assert len(stellen) == len(reihenfolge)
    assert stellen == sorted(stellen)


def test_stationsskript_bricht_bei_netatmo_fehler_ab_ohne_zu_bauen():
    """Ein gescheiterter Abruf darf den letzten gueltigen Datenstand nicht ueberschreiben."""
    text = STATION.read_text(encoding="utf-8")
    assert "if ! python3 skripte/station_netatmo.py" in text
    assert text.index("exit 1") < text.index("bauen_station.py")


def test_beide_laeufe_nutzen_dieselbe_sperre():
    """Zwei gleichzeitige Laeufe wuerden sich beim Commit in die Quere kommen --
    bei GitHub war das die gemeinsame concurrency-Gruppe 'daten'."""
    a = re.search(r'SPERRE="([^"]+)"', LAUF.read_text(encoding="utf-8")).group(1)
    b = re.search(r'SPERRE="([^"]+)"', STATION.read_text(encoding="utf-8")).group(1)
    assert a == b


def test_cron_php_kennt_beide_laeufe():
    text = CRON.read_text(encoding="utf-8")
    assert "skripte/lauf_station.sh" in text and "teil" in text
