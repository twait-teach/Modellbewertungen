"""historie.py: Idempotenz -- keine Abrufe vor 12 UTC, keine bei aktuellem Stand."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skripte"))
import historie  # noqa: E402

UTC = dt.timezone.utc


@pytest.fixture
def umgebung(monkeypatch, tmp_path):
    """Eigenes Ausgabeverzeichnis, gezaehlte (statt echte) Abrufe."""
    monkeypatch.setattr(historie, "OUT", tmp_path)
    abrufe = []

    def hole(params, versuche=5):
        abrufe.append(params["models"])
        zeiten = [f"2026-09-{tag:02d}T{h:02d}:00" for tag in (17, 18) for h in range(24)]
        h = {"time": zeiten}
        for lead in historie.LEADS:
            h[f"precipitation_previous_day{lead}"] = [0.1] * len(zeiten)
        return {"hourly": h}

    monkeypatch.setattr(historie, "hole", hole)
    return abrufe


def _stand_schreiben(tmp_path, kurz, stand):
    (tmp_path / f"history_{kurz}.json").write_text(
        json.dumps({"modell": kurz, "stand": stand, "tage": {}}), encoding="utf-8")


def _stand_lesen(tmp_path, kurz):
    return json.loads((tmp_path / f"history_{kurz}.json").read_text(encoding="utf-8"))["stand"]


def test_vor_12_utc_keine_automatische_aktualisierung(umgebung, tmp_path):
    _stand_schreiben(tmp_path, "gfs", "2026-09-18")
    _stand_schreiben(tmp_path, "ecmwf", "2026-09-18")
    historie.main([], jetzt=dt.datetime(2026, 9, 19, 11, 59, tzinfo=UTC))
    assert umgebung == []
    assert _stand_lesen(tmp_path, "gfs") == "2026-09-18"


def test_nach_12_utc_und_stand_von_gestern_wird_aktualisiert(umgebung, tmp_path):
    _stand_schreiben(tmp_path, "gfs", "2026-09-18")
    _stand_schreiben(tmp_path, "ecmwf", "2026-09-18")
    historie.main([], jetzt=dt.datetime(2026, 9, 19, 12, 26, tzinfo=UTC))  # verspaeteter Start
    assert sorted(umgebung) == ["ecmwf_ifs025", "gfs_seamless"]
    assert _stand_lesen(tmp_path, "gfs") == "2026-09-19"
    assert _stand_lesen(tmp_path, "ecmwf") == "2026-09-19"


def test_nach_12_utc_und_stand_von_heute_wird_uebersprungen(umgebung, tmp_path):
    _stand_schreiben(tmp_path, "gfs", "2026-09-19")
    _stand_schreiben(tmp_path, "ecmwf", "2026-09-19")
    historie.main([], jetzt=dt.datetime(2026, 9, 19, 18, 47, tzinfo=UTC))
    assert umgebung == []


def test_ist_nur_eine_datei_veraltet_wird_nur_diese_aktualisiert(umgebung, tmp_path):
    _stand_schreiben(tmp_path, "gfs", "2026-09-19")
    _stand_schreiben(tmp_path, "ecmwf", "2026-09-18")
    historie.main([], jetzt=dt.datetime(2026, 9, 19, 13, 0, tzinfo=UTC))
    assert umgebung == ["ecmwf_ifs025"]
    assert _stand_lesen(tmp_path, "ecmwf") == "2026-09-19"
    assert _stand_lesen(tmp_path, "gfs") == "2026-09-19"


def test_fehlende_oder_kaputte_datei_gilt_als_veraltet(umgebung, tmp_path):
    (tmp_path / "history_gfs.json").write_text("{kaputt", encoding="utf-8")
    # history_ecmwf.json fehlt ganz
    historie.main([], jetzt=dt.datetime(2026, 9, 19, 12, 0, tzinfo=UTC))
    assert sorted(umgebung) == ["ecmwf_ifs025", "gfs_seamless"]


def test_manueller_start_folgt_derselben_pruefung(umgebung, tmp_path):
    """Es gibt keinen Sonderweg fuer workflow_dispatch: ein zweiter Aufruf am
    selben Tag laedt die 90-Tage-Historie nicht noch einmal."""
    _stand_schreiben(tmp_path, "gfs", "2026-09-18")
    _stand_schreiben(tmp_path, "ecmwf", "2026-09-18")
    jetzt = dt.datetime(2026, 9, 19, 14, 0, tzinfo=UTC)
    historie.main([], jetzt=jetzt)
    assert len(umgebung) == 2
    historie.main([], jetzt=jetzt + dt.timedelta(minutes=30))
    assert len(umgebung) == 2


def test_erzwingen_hebt_uhrzeit_und_stand_auf(umgebung, tmp_path):
    _stand_schreiben(tmp_path, "gfs", "2026-09-19")
    _stand_schreiben(tmp_path, "ecmwf", "2026-09-19")
    historie.main(["--erzwingen"], jetzt=dt.datetime(2026, 9, 19, 6, 0, tzinfo=UTC))
    assert sorted(umgebung) == ["ecmwf_ifs025", "gfs_seamless"]


def test_aeltere_tage_bleiben_beim_neuen_abruf_erhalten(umgebung, tmp_path):
    """Die API liefert nur ~92 Tage; was herausfaellt, darf nicht verloren gehen."""
    (tmp_path / "history_gfs.json").write_text(json.dumps({"modell": "gfs", "stand": "2026-09-18",
        "tage": {"2025-01-05": {"1": 3.2, "5": 1.0}, "2026-09-17": {"1": 9.9}}}), encoding="utf-8")
    (tmp_path / "history_gfs_nachtrag.json").write_text(json.dumps({"tage": {"2024-12-31": {"1": 0.5}}}), encoding="utf-8")
    historie.main(["--erzwingen"], jetzt=dt.datetime(2026, 9, 19, 13, 0, tzinfo=UTC))
    tage = json.loads((tmp_path / "history_gfs.json").read_text(encoding="utf-8"))["tage"]
    assert tage["2025-01-05"] == {"1": 3.2, "5": 1.0}            # alter Tag bleibt
    assert tage["2024-12-31"] == {"1": 0.5}                       # Nachtrag uebernommen
    assert tage["2026-09-17"]["1"] == 2.4 and tage["2026-09-18"]["7"] == 2.4   # neu geliefert ersetzt/ergaenzt
    assert list(tage) == sorted(tage)
