"""Wetterstation: Token-Reihenfolge, Fehlerverhalten, Datenschutz, Seitenbau.

Ohne Netz: Netatmo, GitHub (gh) und die Uhr werden vollstaendig ersetzt.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skripte"))
import bauen_station  # noqa: E402
import station_netatmo as sn  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
T0 = 1789900000 - 1789900000 % 300          # fester Zeitpunkt (Sept. 2026)
GERAET, AUSSEN, REGEN = "70:ee:50:aa:bb:cc", "02:00:00:aa:bb:cc", "05:00:00:aa:bb:cc"
UMGEBUNG = {"NETATMO_CLIENT_ID": "cid-123", "NETATMO_CLIENT_SECRET": "csecret-456",
            "NETATMO_REFRESH_TOKEN": "alt-refresh-789", "SECRETS_PAT": "github_pat_TEST",
            "GITHUB_REPOSITORY": "twait-teach/Modellbewertungen"}


@pytest.fixture(autouse=True)
def ohne_pausen(monkeypatch):
    monkeypatch.setattr(sn, "PAUSE_S", 0)
    monkeypatch.setattr(sn.time, "time", lambda: T0)


class Antwort:
    def __init__(self, status, daten):
        self.status_code, self._daten = status, daten

    def json(self):
        if isinstance(self._daten, Exception):
            raise self._daten
        return self._daten


def stationsdaten():
    return {"body": {"devices": [{
        "_id": GERAET, "station_name": "Haus Mustermann", "date_setup": T0 - 10 * 86400,
        "place": {"location": [12.1234567, 47.8765432], "city": "Stephanskirchen", "altitude": 470},
        "dashboard_data": {"Temperature": 21.5, "CO2": 800, "Noise": 40, "Pressure": 1015.2},
        "modules": [
            {"_id": AUSSEN, "type": "NAModule1", "module_name": "Garten Nord", "date_setup": T0 - 10 * 86400},
            {"_id": REGEN, "type": "NAModule3", "module_name": "Regen Dach", "date_setup": T0 - 10 * 86400},
        ]}]}, "status": "ok"}


class Welt:
    """Protokolliert jeden Aufruf in Reihenfolge und simuliert Netatmo und gh."""

    def __init__(self, vorab_ok=True, token_status=200, secret_ok=True, messung_status=200,
                 regen_status=200):
        self.log, self.vorab_ok, self.token_status = [], vorab_ok, token_status
        self.secret_ok, self.messung_status, self.regen_status = secret_ok, messung_status, regen_status
        self.gespeichert = None

    def run(self, befehl, input=None, **kwargs):
        assert befehl[0] == "gh"
        assert kwargs["env"]["GH_TOKEN"] == UMGEBUNG["SECRETS_PAT"]
        assert "GITHUB_TOKEN" not in kwargs["env"]
        if befehl[1] == "api":
            self.log.append("vorab")
            return subprocess.CompletedProcess(befehl, 0 if self.vorab_ok else 1, "", "")
        assert befehl[1:4] == ["secret", "set", "NETATMO_REFRESH_TOKEN"]
        assert all("neu-refresh" not in teil for teil in befehl), "Token nie als Befehlsteil"
        self.log.append("secret")
        self.gespeichert = input
        return subprocess.CompletedProcess(befehl, 0 if self.secret_ok else 1, "", "Fehler")

    def post(self, url, data=None, **kwargs):
        self.log.append("token")
        assert data["refresh_token"] == UMGEBUNG["NETATMO_REFRESH_TOKEN"]
        if self.token_status != 200:
            return Antwort(self.token_status, {"error": "invalid_grant"})
        return Antwort(200, {"access_token": "neu-access", "refresh_token": "neu-refresh", "expires_in": 10800})

    def get(self, url, headers=None, params=None, **kwargs):
        assert headers["Authorization"] == "Bearer neu-access"
        if url.endswith("getstationsdata"):
            self.log.append("stationsdata")
            return Antwort(200, stationsdaten())
        self.log.append(f"measure:{params['module_id']}")
        if params["module_id"] == REGEN and self.regen_status != 200:
            return Antwort(self.regen_status, {"error": {"code": 21, "message": "Invalid type"}})
        if self.messung_status != 200:
            return Antwort(self.messung_status, {"error": {"code": 26, "message": "User usage reached"}})
        beginn, ende = int(params["date_begin"]), int(params.get("date_end", T0))
        werte = {}
        for ts in range(beginn - beginn % 300 + 300, min(ende, T0) + 1, 300):
            if ts < T0 - 3 * 86400:
                continue
            werte[str(ts)] = [12.34, 81] if params["module_id"] == AUSSEN else [0.101]
            if len(werte) >= int(params["limit"]):
                break
        return Antwort(200, {"body": werte, "status": "ok"})


def starten(tmp_path, welt, umgebung=UMGEBUNG):
    return sn.main([], umgebung=umgebung, post=welt.post, get=welt.get, run=welt.run,
                   verzeichnis=tmp_path / "station")


# ------------------------------------------------------------------ Reihenfolge

def test_reihenfolge_token_wird_vor_jeder_datenabfrage_gespeichert(tmp_path):
    welt = Welt()
    assert starten(tmp_path, welt) == 0
    assert welt.log[:3] == ["vorab", "token", "secret"]
    assert welt.log[3] == "stationsdata"
    assert welt.gespeichert == "neu-refresh"


def test_fehlende_einrichtung_fragt_nichts_an(tmp_path):
    welt = Welt()
    umgebung = dict(UMGEBUNG, SECRETS_PAT="")
    assert starten(tmp_path, welt, umgebung) == 2
    assert welt.log == []


def test_abgelaufener_github_schluessel_laesst_netatmo_token_unberuehrt(tmp_path):
    welt = Welt(vorab_ok=False)
    assert starten(tmp_path, welt) == 1
    assert welt.log == ["vorab"]
    assert not (tmp_path / "station").exists()


def test_speicherfehler_bricht_vor_datenabruf_ab(tmp_path):
    welt = Welt(secret_ok=False)
    assert starten(tmp_path, welt) == 1
    assert welt.log == ["vorab", "token", "secret"]
    assert not (tmp_path / "station").exists()


def test_abgelehnter_token_meldet_keinen_tokenwert(tmp_path, capsys):
    welt = Welt(token_status=400)
    assert starten(tmp_path, welt) == 1
    assert welt.log == ["vorab", "token"]
    ausgabe = capsys.readouterr().out
    assert "invalid_grant" in ausgabe
    for geheim in UMGEBUNG.values():
        if geheim != UMGEBUNG["GITHUB_REPOSITORY"]:
            assert geheim not in ausgabe


def test_neue_tokens_werden_in_actions_maskiert(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert starten(tmp_path, Welt()) == 0
    zeilen = capsys.readouterr().out.splitlines()
    assert "::add-mask::neu-access" in zeilen and "::add-mask::neu-refresh" in zeilen
    # Maskierung kommt vor jeder anderen Zeile, in der ein Token stehen koennte
    assert zeilen.index("::add-mask::neu-refresh") < zeilen.index(
        "Netatmo-Zugang erneuert und neuer Refresh Token gespeichert.")


def test_abruffehler_laesst_bisherigen_datenstand_unveraendert(tmp_path):
    assert starten(tmp_path, Welt()) == 0
    vorher = {p.name: p.read_bytes() for p in (tmp_path / "station").iterdir()}
    assert starten(tmp_path, Welt(messung_status=500)) == 1
    nachher = {p.name: p.read_bytes() for p in (tmp_path / "station").iterdir()}
    assert vorher == nachher


def test_voruebergehende_stoerung_wird_wiederholt(tmp_path):
    welt = Welt()
    echt, zaehler = welt.get, {"n": 0}

    def wackelig(url, **kwargs):
        if url.endswith("getstationsdata") and zaehler["n"] < 2:
            zaehler["n"] += 1
            return Antwort(503, {"error": {"code": 27, "message": "Service temporarily unavailable"}})
        return echt(url, **kwargs)
    welt.get = wackelig
    assert starten(tmp_path, welt) == 0
    assert zaehler["n"] == 2 and sn.laden(tmp_path / "station")["aussen"]


def test_dauerhafte_stoerung_endet_mit_fehler_ohne_dateien(tmp_path, capsys):
    welt = Welt()
    welt.get = lambda url, **kw: Antwort(503, {"error": {"code": 27, "message": "Service temporarily unavailable"}})
    assert starten(tmp_path, welt) == 1
    assert "nach 4 Versuchen" in capsys.readouterr().out
    assert not (tmp_path / "station").exists()


def test_vorabpruefung_nennt_grund_von_github(tmp_path, capsys):
    welt = Welt(vorab_ok=False)
    echt = welt.run
    welt.run = lambda befehl, **kw: subprocess.CompletedProcess(befehl, 1, "", "HTTP 401: Bad credentials (https://api.github.com/...)\n") if befehl[1] == "api" else echt(befehl, **kw)
    assert starten(tmp_path, welt) == 1
    assert "GitHub meldet: HTTP 401: Bad credentials" in capsys.readouterr().out


def test_ausfall_des_regenmessers_verhindert_aussenwerte_nicht(tmp_path):
    assert starten(tmp_path, Welt(regen_status=400)) == 0
    reihen = sn.laden(tmp_path / "station")
    assert reihen["aussen"] and not reihen["regen"]


# ------------------------------------------------------------------ Datenschutz

def test_gespeichert_werden_nur_zeit_und_aussenwerte(tmp_path):
    assert starten(tmp_path, Welt()) == 0
    for pfad in (tmp_path / "station").iterdir():
        text = pfad.read_text(encoding="utf-8")
        for verboten in (GERAET, AUSSEN, REGEN, "Mustermann", "Garten", "Dach", "12.123", "47.876",
                         "CO2", "Noise", "Pressure", "neu-refresh", "neu-access", "csecret"):
            assert verboten not in text, (pfad.name, verboten)
    monat = json.loads(next((tmp_path / "station").glob("station_*.json")).read_text(encoding="utf-8"))
    assert set(monat) == {"monat", "ort", "felder", "aussen", "regen"}
    assert all(len(z) == 3 for z in monat["aussen"]) and all(len(z) == 2 for z in monat["regen"])


# ------------------------------------------------------------------ Abrufplanung

def test_rueckfuellung_endet_an_der_einrichtung_und_luecken_werden_nachgeholt(tmp_path):
    for _ in range(4):
        assert starten(tmp_path, Welt()) == 0
    stand = json.loads((tmp_path / "station" / "stand.json").read_text(encoding="utf-8"))
    assert stand["rueckfuellung_fertig"] == {"aussen": True, "regen": True}
    assert stand["letzte_aktualisierung"].endswith("Z")
    reihen = sn.laden(tmp_path / "station")
    assert max(reihen["aussen"]) == T0
    # Werte liegen lueckenlos im 5-Minuten-Raster der Testwelt
    zeiten = sorted(reihen["aussen"])
    assert all(b - a == 300 for a, b in zip(zeiten, zeiten[1:]))


def test_werte_aus_body_versteht_beide_antwortformen():
    assert sn.werte_aus_body({"100": [1.0, 50], "400": [None, None]}, 2) == {100: [1.0, 50.0]}
    kompakt = [{"beg_time": 100, "step_time": 300, "value": [[1.0, 50], [2.0, 55]]}]
    assert sn.werte_aus_body(kompakt, 2) == {100: [1.0, 50.0], 400: [2.0, 55.0]}


def test_modulsuche_ohne_aussenmodul_ist_ein_fehler():
    body = stationsdaten()["body"]
    body["devices"][0]["modules"] = [m for m in body["devices"][0]["modules"] if m["type"] != "NAModule1"]
    with pytest.raises(sn.AbrufFehler):
        sn.module_finden(body)


# ------------------------------------------------------------------ Seitenbau

def _utc(j, m, t, h):
    import datetime as dt
    return int(dt.datetime(j, m, t, h, tzinfo=dt.timezone.utc).timestamp())


@pytest.fixture
def gebaut(tmp_path, monkeypatch):
    daten, docs = tmp_path / "station", tmp_path / "docs"
    # 31.10. 21:00 bis 1.11.2026 09:00 Ortszeit (MEZ): ueber die Monatsgrenze
    von, bis = _utc(2026, 10, 31, 20), _utc(2026, 11, 1, 8)
    aussen = {ts: [10.0 + (ts % 3600) / 3600, 80] for ts in range(von, bis, 300)}
    regen = {ts + 20: [0.2] for ts in range(von, bis, 300)}
    sn.speichern({"aussen": aussen, "regen": regen},
                 {"rueckfuellung_fertig": {"aussen": True, "regen": True},
                  "letzte_aktualisierung": "2026-11-01T07:00:00Z"}, daten)
    monkeypatch.setattr(bauen_station, "DATEN", daten)
    monkeypatch.setattr(bauen_station, "DOCS", docs)
    bauen_station.main()
    return docs


def _js_objekt(pfad, name):
    text = pfad.read_text(encoding="utf-8")
    return json.loads(text.split("]=", 1)[1].rstrip(";\n") if "||" in text else text.split("=", 1)[1].rstrip(";\n"))


def test_seitenbau_monatsdateien_nach_ortszeit(gebaut):
    namen = sorted(p.name for p in (gebaut / "station").iterdir())
    assert namen == ["heute.js", "verlauf_2026-10.js", "verlauf_2026-11.js"]
    heute = _js_objekt(gebaut / "station" / "heute.js", "STATION_HEUTE")
    assert heute["monate"] == ["2026-10", "2026-11"] and heute["ort"] == "Stephanskirchen"
    assert heute["letzte_messung"] == max(z[0] for z in heute["aussen"])
    nov = _js_objekt(gebaut / "station" / "verlauf_2026-11.js", "STATION_VERLAUF")
    # erste Novemberstunde Ortszeit (00:00 MEZ) = 31.10. 23:00 UTC
    assert nov["stunden"][0][0] == _utc(2026, 10, 31, 23)
    okt = _js_objekt(gebaut / "station" / "verlauf_2026-10.js", "STATION_VERLAUF")
    assert okt["stunden"][-1][0] == _utc(2026, 10, 31, 22)
    stunde = nov["stunden"][1]
    assert stunde[6] == 12 and abs(stunde[5] - 2.4) < 1e-9 and stunde[2] <= stunde[1] <= stunde[3]


def test_seitenbau_ist_deterministisch(gebaut):
    vorher = {p: p.read_bytes() for p in gebaut.rglob("*") if p.is_file()}
    bauen_station.main()
    assert vorher == {p: p.read_bytes() for p in gebaut.rglob("*") if p.is_file()}


def test_stationsseite_ist_versteckt_und_laedt_ohne_fremde_daten():
    seite = (WURZEL / "skripte" / "station_vorlage.html").read_text(encoding="utf-8")
    assert '<meta name="robots" content="noindex,nofollow">' in seite
    assert "Wetterstationsdaten derzeit nicht aktuell" in seite
    assert "station/heute.js?v=" in seite
    hauptseite = (WURZEL / "skripte" / "vorlage.html").read_text(encoding="utf-8")
    assert "station.html" not in hauptseite, "Testseite noch nicht verlinken"


# ------------------------------------------------------------------ Workflow

def test_workflow_regeln():
    wf = (WURZEL / ".github" / "workflows" / "station.yml").read_text(encoding="utf-8")
    code = "\n".join(z for z in wf.splitlines() if not z.strip().startswith("#"))
    assert "pull_request" not in code and "workflow_run" not in code
    assert "cancel-in-progress: false" in wf and "group: daten" in wf
    haupt = (WURZEL / ".github" / "workflows" / "aktualisieren.yml").read_text(encoding="utf-8")
    assert "group: daten" in haupt, "beide Workflows muessen dieselbe Sperre teilen"
    assert "timeout-minutes" in wf
    assert "echo ${{ secrets" not in wf
    # Nur ein Workflow greift auf Netatmo zu
    netatmo = [p.name for p in (WURZEL / ".github" / "workflows").glob("*.yml")
               if "NETATMO_REFRESH_TOKEN" in p.read_text(encoding="utf-8")]
    assert netatmo == ["station.yml"]
