"""Sommerzeitrobuste Zeitverarbeitung in sammeln_vorhersage.py.

Interne Zeitpunkte sind eindeutige Unixsekunden (UTC). Lokale Zeit
(Europe/Berlin) entsteht ausschliesslich fuer die Anzeige; lokale Zeitstrings
ohne Offset dienen nie als Schluessel. Getestet wird an beiden Umstellungen:
  * 25.10.2026: Winterzeit -- die Stunde 02:00-03:00 kommt lokal doppelt vor,
    der Tag hat 25 Stunden;
  * 28.03.2027: Sommerzeit -- die Stunde 02:00-03:00 fehlt lokal, 23 Stunden.
"""
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skripte"))
import sammeln_vorhersage as sv  # noqa: E402

UTC = dt.timezone.utc
BERLIN = ZoneInfo("Europe/Berlin")
H = 3600


def _stunden(init, stunden_vor=24, stunden_nach=24 * 16 + 24):
    """Lueckenlose UTC-Stundenachse als Unixsekunden."""
    start = int(init.timestamp()) - stunden_vor * H
    return [start + i * H for i in range(stunden_vor + stunden_nach + 1)]


def _lokal(unix):
    return dt.datetime.fromtimestamp(unix, BERLIN).strftime("%Y-%m-%dT%H:%M")


# ------------------------------------------------------------ Zeitachse aus der API-Antwort
def test_zeitachse_akzeptiert_unixzeit_und_utc_strings_und_lehnt_anderes_ab():
    assert sv.zeitachse({"hourly": {"time": [1789855200, 1789858800]}}) == [1789855200, 1789858800]
    # timezone=UTC angefordert: Strings ohne Offset sind eindeutig UTC
    assert sv.zeitachse({"hourly": {"time": ["2026-09-20T00:00"]}}) == [1789862400]
    for kaputt in (["2026-10-25T02:00+01:00"], ["kein Datum"], [None], [1.5]):
        with pytest.raises(ValueError):
            sv.zeitachse({"hourly": {"time": kaputt}})


# ------------------------------------------------------------ Winterzeit (doppelte Stunde)
@pytest.mark.parametrize("modell, init, horizont", [
    ("ecmwf", dt.datetime(2026, 10, 24, 12, tzinfo=UTC), 3),
    ("gfs", dt.datetime(2026, 10, 24, 18, tzinfo=UTC), 3),
    ("gfs", dt.datetime(2026, 10, 25, 0, tzinfo=UTC), 2),     # Lauf genau in der doppelten Stunde
    ("ecmwf", dt.datetime(2026, 10, 15, 0, tzinfo=UTC), 15),  # Umstellung mitten im 15-Tage-Horizont
])
def test_winterzeitumstellung_zeitraster_bleibt_regelmaessig_und_horizont_unveraendert(modell, init, horizont):
    zeiten, unix = sv.modell_zeitfenster(_stunden(init), init, horizont, modell)
    assert unix == sorted(set(unix)), "Zeitpunkte muessen streng aufsteigend und eindeutig sein"
    assert unix[0] == int(init.timestamp())
    assert unix[-1] == int((init + dt.timedelta(days=horizont)).timestamp())   # exakt Horizont, egal wie lang der Ortstag ist
    schritte = {b - a for a, b in zip(unix, unix[1:])}
    erlaubt = {3 * H, 6 * H} if modell == "gfs" else {3 * H}
    assert schritte <= erlaubt, f"unregelmaessige Intervalle: {sorted(schritte)}"
    assert zeiten == [_lokal(u) for u in unix]      # Anzeigestrings folgen der Unixzeit, nicht umgekehrt
    assert len(unix) == len(set(unix)) == len(zeiten)


def test_winterzeitumstellung_niederschlagssumme_ist_korrekt():
    init = dt.datetime(2026, 10, 24, 12, tzinfo=UTC)
    alle = _stunden(init)
    # jede Stunde ein eigener Wert -> Verwechslungen der doppelten Ortsstunde faellt auf
    # Ganze Hundertstel: Summen liegen nie auf einer Rundungsgrenze, daher
    # kommt es nicht auf die Summierreihenfolge oder die Python-Version an
    # (sum() rechnet ab Python 3.12 genauer als davor).
    serie = {u: round(0.01 * (i % 37 + 1), 2) for i, u in enumerate(alle)}
    zeiten, unix = sv.modell_zeitfenster(alle, init, 3, "ecmwf")
    kum = sv.niederschlag_kumulieren(serie, alle, unix, init)
    erwartet = [round(sum(v for u, v in serie.items() if int(init.timestamp()) < u <= ziel), 2) for ziel in unix]
    assert kum == erwartet
    assert kum[0] == 0.0
    assert all(b >= a for a, b in zip(kum, kum[1:]))       # monoton


def test_doppelte_ortsstunde_erzeugt_keine_doppelten_zeitpunkte():
    init = dt.datetime(2026, 10, 24, 22, tzinfo=UTC)
    alle = _stunden(init)
    lokal = [_lokal(u) for u in alle]
    assert lokal.count("2026-10-25T02:00") == 2, "Testvoraussetzung: lokal kommt 02:00 zweimal vor"
    _, unix = sv.modell_zeitfenster(alle, init, 1, "gfs")
    assert len(unix) == len(set(unix))
    assert sv.niederschlag_kumulieren({u: 1.0 for u in alle}, alle, unix, init)[-1] == 24.0   # 24 h Horizont, 1 mm/h


# ------------------------------------------------------------ Sommerzeit (fehlende Stunde)
@pytest.mark.parametrize("modell, init, horizont", [
    ("ecmwf", dt.datetime(2027, 3, 27, 12, tzinfo=UTC), 3),
    ("gfs", dt.datetime(2027, 3, 27, 18, tzinfo=UTC), 3),
    ("gfs", dt.datetime(2027, 3, 20, 0, tzinfo=UTC), 16),
])
def test_sommerzeitumstellung_zeitraster_und_horizont(modell, init, horizont):
    alle = _stunden(init)
    lokal = [_lokal(u) for u in alle]
    assert "2027-03-28T02:00" not in lokal, "Testvoraussetzung: die Ortsstunde 02:00 existiert nicht"
    zeiten, unix = sv.modell_zeitfenster(alle, init, horizont, modell)
    assert unix[-1] == int((init + dt.timedelta(days=horizont)).timestamp())
    schritte = {b - a for a, b in zip(unix, unix[1:])}
    assert schritte <= ({3 * H, 6 * H} if modell == "gfs" else {3 * H})
    assert unix == sorted(unix)
    assert zeiten == [_lokal(u) for u in unix]


def test_sommerzeitumstellung_niederschlag_summiert_23_stundentag_richtig():
    init = dt.datetime(2027, 3, 27, 12, tzinfo=UTC)
    alle = _stunden(init)
    _, unix = sv.modell_zeitfenster(alle, init, 3, "ecmwf")
    kum = sv.niederschlag_kumulieren({u: 1.0 for u in alle}, alle, unix, init)
    assert kum == [round(3.0 * i, 2) for i in range(len(unix))]   # 3 mm je 3-h-Intervall, ohne Luecke und Doppelung
    assert kum[-1] == 72.0                                         # 3 * 24 UTC-Stunden, unabhaengig von 23/25 Ortsstunden


# ------------------------------------------------------------ Ende-zu-Ende mit Unixzeit-API
def _ensemble_unix(init, horizont, mitglieder=30, mit_kontrolle=True):
    alle = _stunden(init, stunden_vor=24, stunden_nach=horizont * 24 + 24)
    hourly = {"time": alle}
    def temp(u, m):
        return round(10.0 + (u - int(init.timestamp())) / H * 0.01 + m * 0.1, 3)
    if mit_kontrolle:
        hourly["temperature_2m"] = [temp(u, 0) for u in alle]
        hourly["temperature_850hPa"] = [temp(u, 0) - 5 for u in alle]
        hourly["precipitation"] = [0.05 for _ in alle]
    for m in range(1, mitglieder + 1):
        hourly[f"temperature_2m_member{m:02d}"] = [temp(u, m) for u in alle]
        hourly[f"temperature_850hPa_member{m:02d}"] = [temp(u, m) - 5 for u in alle]
        hourly[f"precipitation_member{m:02d}"] = [0.1 for _ in alle]
    return {"hourly": hourly}


def test_ende_zu_ende_ueber_die_winterzeitumstellung(monkeypatch):
    init = dt.datetime(2026, 10, 24, 12, tzinfo=UTC)
    cfg = dict(sv.MODELLE["ecmwf"], horizont=3)
    cfg["meta_ensemble"] = "meta_ens"
    anfragen = []

    def hole(url, params=None, roh=False, versuche=4, fehlerliste=None, timeout=90):
        if "meta.json" in url:
            return {"last_run_initialisation_time": int(init.timestamp()),
                    "last_run_availability_time": int(init.timestamp()) + 6 * H}
        anfragen.append(params)
        return _ensemble_unix(init, 3, mitglieder=50, mit_kontrolle=True)

    monkeypatch.setattr(sv, "hole", hole)
    lauf, hinweise = sv.verarbeite_modell("ecmwf", cfg, [], init.date(),
                                          ens_info={"lauf": init, "verfuegbar": init})
    assert lauf is not None, hinweise
    assert lauf["ensemble_vollstaendig"] is True, hinweise
    # UTC-Abruf mit eindeutiger Unixzeit -- kein lokaler Zeitstring als Schluessel
    assert anfragen[0]["timeformat"] == "unixtime" and anfragen[0]["timezone"] == "UTC"
    for feld in ("temperatur_2m", "temperatur_850hpa", "niederschlag"):
        r = lauf[feld]
        assert len(r["zeitpunkte_unix"]) == 25                # 3 Tage / 3 h + Startpunkt
        assert r["zeitpunkte_unix"] == sorted(set(r["zeitpunkte_unix"]))
        assert r["zeitpunkte_unix"][-1] - r["zeitpunkte_unix"][0] == 3 * 24 * H
        assert r["zeiten"] == [_lokal(u) for u in r["zeitpunkte_unix"]]
    # 0,1 mm je Stunde und Mitglied -> nach 72 h genau 7,2 mm
    assert lauf["niederschlag"]["mittel"][-1] == pytest.approx(7.2, abs=0.01)
    assert lauf["niederschlag"]["mitglieder"][0][0] == 0.0
    assert lauf["kontrolllauf"] if False else lauf["temperatur_2m"]["kontrolllauf"] is None   # ECMWF: keiner


def test_hauptlauf_ueber_die_umstellung_wird_mit_unixzeit_und_utc_angefordert(monkeypatch):
    init = dt.datetime(2026, 10, 24, 12, tzinfo=UTC)
    cfg = dict(sv.MODELLE["ecmwf"], horizont=3)
    lauf, _ = None, None
    monkeypatch.setattr(sv, "hole", lambda url, params=None, **kw: (
        {"last_run_initialisation_time": int(init.timestamp()), "last_run_availability_time": int(init.timestamp())}
        if "meta.json" in url else _ensemble_unix(init, 3, mitglieder=50)))
    lauf, hinweise = sv.verarbeite_modell("ecmwf", cfg, [], init.date(), ens_info={"lauf": init, "verfuegbar": init})
    assert lauf and lauf["ensemble_vollstaendig"], hinweise

    anfragen = []
    def single(url, params=None, **kw):
        anfragen.append(params)
        antwort = _ensemble_unix(init, 3, mitglieder=0)
        return antwort
    monkeypatch.setattr(sv, "hole", single)
    geaendert, meldung = sv.ergaenze_hauptlauf(lauf, cfg, [])
    assert geaendert, meldung
    assert all(a["timezone"] == "UTC" and a["timeformat"] == "unixtime" for a in anfragen)
    assert all(a["run"] == "2026-10-24T12:00" for a in anfragen)
    assert lauf["niederschlag"]["hauptlauf"][-1] == pytest.approx(3.6, abs=0.01)    # 0,05 mm/h * 72 h


def test_unerwartetes_zeitformat_wird_nicht_geraten_und_nicht_gespeichert(monkeypatch):
    init = dt.datetime(2026, 10, 24, 12, tzinfo=UTC)
    cfg = dict(sv.MODELLE["ecmwf"], horizont=3)
    antwort = _ensemble_unix(init, 3, mitglieder=50)
    antwort["hourly"]["time"] = [_lokal(u) + "+01:00" for u in antwort["hourly"]["time"]]   # z. B. Offset-Strings
    monkeypatch.setattr(sv, "hole", lambda url, params=None, **kw: antwort)
    lauf, hinweise = sv.verarbeite_modell("ecmwf", cfg, [], init.date(), ens_info={"lauf": init, "verfuegbar": init})
    assert lauf is None
    assert any("Zeitformat" in h for h in hinweise)


def test_hauptlauf_mit_unerwartetem_zeitformat_wird_nicht_uebernommen(monkeypatch):
    init = dt.datetime(2026, 10, 24, 12, tzinfo=UTC)
    cfg = dict(sv.MODELLE["ecmwf"], horizont=3)
    monkeypatch.setattr(sv, "hole", lambda url, params=None, **kw: _ensemble_unix(init, 3, mitglieder=50))
    lauf, hinweise = sv.verarbeite_modell("ecmwf", cfg, [], init.date(), ens_info={"lauf": init, "verfuegbar": init})
    assert lauf and lauf["ensemble_vollstaendig"], hinweise

    def single(url, params=None, **kw):
        antwort = _ensemble_unix(init, 3, mitglieder=0)
        antwort["hourly"]["time"] = [_lokal(u) + "+02:00" for u in antwort["hourly"]["time"]]
        return antwort
    monkeypatch.setattr(sv, "hole", single)
    geaendert, meldung = sv.ergaenze_hauptlauf(lauf, cfg, [])
    assert geaendert is False and "Zeitformat" in meldung
    assert lauf["niederschlag"]["hauptlauf"] is None


# ------------------------------------------------------------ Tagessummen (Historie, Stationswerte)
import io
import zipfile

import gemeinsam
import historie
import sammeln


def test_stunden_im_ortstag_kennt_23_24_und_25_stundentage():
    assert gemeinsam.stunden_im_ortstag("2026-10-24") == 24
    assert gemeinsam.stunden_im_ortstag("2026-10-25") == 25     # Winterzeit
    assert gemeinsam.stunden_im_ortstag("2027-03-28") == 23     # Sommerzeit
    assert gemeinsam.stunden_im_ortstag("2027-03-29") == 24


@pytest.mark.parametrize("tag, stunden", [("2026-10-25", 25), ("2027-03-28", 23), ("2026-10-24", 24)])
def test_historie_tagessumme_gilt_auch_am_umstelltag_als_vollstaendig(tag, stunden):
    """Am 28.03.2027 hat der Ortstag nur 23 Stundenwerte -- er darf nicht als
    unvollstaendig verworfen werden; am 25.10.2026 hat er 25."""
    start = int(dt.datetime.fromisoformat(tag).replace(tzinfo=BERLIN).timestamp())
    unix = [start + i * H for i in range(stunden)]
    lokal = [_lokal(u) for u in unix]
    assert all(t.startswith(tag) for t in lokal)
    assert historie.tagessummen(lokal, [1.0] * stunden) == {tag: float(stunden)}
    # ein wirklich fehlender Wert bleibt erkennbar
    assert historie.tagessummen(lokal[:-1], [1.0] * (stunden - 1)) == {}


def _dwd_zip(unix_stunden):
    zeilen = ["STATIONS_ID;MESS_DATUM;QN_8;R1;RS_IND;WRTR;eor"]
    for u in unix_stunden:
        t = dt.datetime.fromtimestamp(u, UTC).strftime("%Y%m%d%H")
        zeilen.append(f"3366;{t};3;1.0;1;6;eor")
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("produkt_rr_stunde_test.txt", "\n".join(zeilen))
    return puffer.getvalue()


@pytest.mark.parametrize("tag, stunden", [("2026-10-25", 25), ("2027-03-28", 23)])
def test_stationswerte_umstelltag_ist_vollstaendig_und_summiert_richtig(monkeypatch, tag, stunden):
    start = int(dt.datetime.fromisoformat(tag).replace(tzinfo=BERLIN).timestamp())
    roh = _dwd_zip([start + i * H for i in range(stunden)])
    monkeypatch.setattr(sammeln, "hole", lambda *a, **k: roh)
    tage, letzter = sammeln.stationswerte()
    assert tage == {tag: float(stunden)}
    assert letzter == tag
