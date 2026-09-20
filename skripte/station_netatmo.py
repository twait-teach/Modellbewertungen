#!/usr/bin/env python3
"""
Netatmo-Wetterstation Stefanskirchen: Zugang erneuern, Aussenwerte holen, speichern.

Ablauf eines Laufs (Reihenfolge ist verbindlich, siehe README "Wetterstation"):

  1. Pflicht-Umgebungsvariablen pruefen. Fehlt etwas, wird NICHTS angefragt.
  2. Vorabpruefung des GitHub-Schluessels (SECRETS_PAT): Darf er das Secret
     ueberhaupt schreiben? Wenn nicht, Abbruch VOR der Token-Erneuerung -- der
     bisherige Netatmo-Refresh-Token bleibt dann gueltig.
  3. Token-Erneuerung bei Netatmo. Beide neuen Tokens werden sofort maskiert.
  4. Der neue Refresh Token wird SOFORT als GitHub-Secret gespeichert -- noch
     bevor irgendeine Wetterabfrage, Datei oder Commit entsteht. Schlaegt das
     fehl, bricht der Lauf ab (Rueckgabecode != 0) und schreibt nichts.
  5. Erst danach: Messwerte abrufen, filtern, im Speicher zusammenfuehren und
     zuletzt atomar schreiben. Jeder Fehler vorher laesst den letzten
     gueltigen Datenstand unveraendert.

Datenschutz: Gespeichert werden ausschliesslich Zeitpunkt (Unixsekunden),
Aussentemperatur, Aussenluftfeuchte und Niederschlag. Geraete- und Modul-
kennungen, Koordinaten, Namen, Innenwerte und die rohen API-Antworten werden
nur im Arbeitsspeicher gehalten und weder gespeichert noch ausgegeben.
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemeinsam import atomar_schreiben_json  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
DATEN = WURZEL / "daten" / "station"
STAND = DATEN / "stand.json"

API = "https://api.netatmo.com"
SECRET_NAME = "NETATMO_REFRESH_TOKEN"
PFLICHT = ("NETATMO_CLIENT_ID", "NETATMO_CLIENT_SECRET", "NETATMO_REFRESH_TOKEN",
           "SECRETS_PAT", "GITHUB_REPOSITORY")

# getmeasure liefert hoechstens 1024 Werte je Abfrage. Aussen- und Regenmodul
# messen etwa alle 5 Minuten; 3 Tage sind rund 864 Werte und passen sicher.
FENSTER_S = 3 * 86400
LIMIT = 1024
# Wie viele zusaetzliche Abfragen je Lauf und Reihe hoechstens nach vorn
# (Luecken nachholen) bzw. nach hinten (Vergangenheit nachladen) gehen.
MAX_VORWAERTS = 6
MAX_RUECKWAERTS = 4
# Ohne vorhandene Daten beginnt die Vorwaertsabfrage so weit in der
# Vergangenheit; aelteres holt die Rueckfuellung nach.
START_OHNE_DATEN_S = 2 * 86400
PAUSE_S = 1.0
# Untergrenze, falls Netatmo kein Einrichtungsdatum liefert (Netatmo-Stationen
# gibt es erst seit 2012) -- verhindert eine endlose Rueckfuellung.
FRUEHESTENS = 1325376000  # 2012-01-01 UTC

REIHEN = {
    # Name: (Netatmo-Modultyp, Messgroessen fuer getmeasure, Anzahl Werte)
    "aussen": ("NAModule1", ("temperature", "humidity"), 2),
    "regen": ("NAModule3", ("rain",), 1),
}


class TokenFehler(Exception):
    """Token-Erneuerung gescheitert. Enthaelt nie einen Tokenwert."""


class SecretFehler(Exception):
    """GitHub-Secret konnte nicht geprueft oder gespeichert werden."""


class AbrufFehler(Exception):
    """Netatmo-Datenabfrage gescheitert."""


class GrenzeErreicht(AbrufFehler):
    """Netatmo meldet: Abrufgrenze erreicht."""


# ------------------------------------------------------------------ Hilfen

def maskieren(wert):
    """Wert in allen weiteren GitHub-Protokollzeilen unkenntlich machen.

    Der Befehl ``::add-mask::`` erscheint selbst nicht im Protokoll. Ausserhalb
    von GitHub Actions (Tests, lokal) wird nichts ausgegeben."""
    if wert and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{wert}", flush=True)


def fehlercode(antwort):
    """Nur den kurzen Fehlercode einer Netatmo-Antwort, nie die ganze Antwort."""
    try:
        d = antwort.json()
    except ValueError:
        return "keine JSON-Antwort"
    fehler = d.get("error") if isinstance(d, dict) else None
    if isinstance(fehler, str):
        return fehler[:60]
    if isinstance(fehler, dict):
        return f"Code {fehler.get('code')}: {str(fehler.get('message', ''))[:80]}"
    return "unbekannt"


def utc_jetzt():
    return dt.datetime.now(dt.timezone.utc)


# ------------------------------------------------------------ GitHub-Secret

def _gh(argumente, pat, eingabe=None, run=subprocess.run):
    umgebung = dict(os.environ, GH_TOKEN=pat)
    umgebung.pop("GITHUB_TOKEN", None)
    return run(["gh", *argumente], input=eingabe, text=True, capture_output=True,
               env=umgebung, timeout=60)


def vorab_pruefen(repo, pat, run=subprocess.run):
    """Kann der Schluessel das Secret schreiben? Abfrage des oeffentlichen
    Verschluesselungsschluessels braucht dasselbe Recht (Secrets) und ist harmlos."""
    erg = _gh(["api", f"repos/{repo}/actions/secrets/public-key", "--silent"], pat, run=run)
    if erg.returncode != 0:
        raise SecretFehler(
            "Vorabpruefung fehlgeschlagen: Der GitHub-Schluessel SECRETS_PAT ist abgelaufen, "
            "falsch oder hat nicht das Recht 'Secrets: Read and write'"
            f"{gh_grund(erg)}. Die Netatmo-Anmeldung wurde NICHT angefasst; der bisherige "
            "Netatmo-Token bleibt gueltig. Siehe README, Wiederherstellung Fall B.")


def gh_grund(erg):
    """Erste Zeile der gh-Fehlermeldung (z. B. 'HTTP 401: Bad credentials'). Enthaelt
    keine Schluesselwerte; zur Sicherheit auf 120 Zeichen gekuerzt."""
    zeile = next((z.strip() for z in (erg.stderr or "").splitlines() if z.strip()), "")
    return f" (GitHub meldet: {zeile[:120]})" if zeile else ""


def secret_speichern(repo, pat, wert, run=subprocess.run):
    """Neuen Refresh Token als Secret speichern. Der Wert geht ueber die
    Standardeingabe an gh (nie als sichtbarer Befehlsteil); gh verschluesselt ihn."""
    erg = _gh(["secret", "set", SECRET_NAME, "--repo", repo], pat, eingabe=wert, run=run)
    if erg.returncode != 0:
        raise SecretFehler(
            f"Der neue Netatmo-Refresh-Token konnte nicht gespeichert werden "
            f"(gh Rueckgabecode {erg.returncode}{gh_grund(erg)}). Der alte Token ist bei Netatmo bereits "
            f"ungueltig: Netatmo-Zugang neu herstellen, siehe README, Wiederherstellung Fall A.")


# ------------------------------------------------------------- Netatmo-Token

def token_erneuern(client_id, client_secret, refresh_token, post=requests.post):
    """Tauscht den Refresh Token gegen neuen Access- und Refresh Token.

    Wiederholt nur, wenn Netatmo gar nicht geantwortet hat oder einen
    Serverfehler meldet. Eine inhaltliche Ablehnung (z. B. invalid_grant) wird
    nicht wiederholt."""
    daten = {"grant_type": "refresh_token", "refresh_token": refresh_token,
             "client_id": client_id, "client_secret": client_secret}
    letzter = None
    for versuch in range(3):
        try:
            r = post(f"{API}/oauth2/token", data=daten, timeout=30)
        except requests.RequestException as e:
            letzter = f"keine Verbindung ({type(e).__name__})"
            time.sleep(2 ** versuch * PAUSE_S)
            continue
        if r.status_code >= 500:
            letzter = f"HTTP {r.status_code}"
            time.sleep(2 ** versuch * PAUSE_S)
            continue
        if r.status_code != 200:
            raise TokenFehler(
                f"Netatmo lehnt die Token-Erneuerung ab (HTTP {r.status_code}, {fehlercode(r)}). "
                f"Bei 'invalid_grant' ist der gespeicherte Refresh Token ungueltig: "
                f"README, Wiederherstellung Fall A.")
        try:
            d = r.json()
        except ValueError:
            raise TokenFehler("Netatmo-Antwort auf die Token-Erneuerung ist kein JSON.") from None
        access = d.get("access_token") if isinstance(d, dict) else None
        neu = d.get("refresh_token") if isinstance(d, dict) else None
        maskieren(access)
        maskieren(neu)
        if not access or not neu:
            raise TokenFehler("Netatmo-Antwort enthaelt keinen vollstaendigen Tokensatz.")
        return access, neu
    raise TokenFehler(f"Netatmo nicht erreichbar ({letzter}). Der bisherige Refresh Token "
                      f"wurde vermutlich nicht verbraucht; der naechste Lauf versucht es erneut.")


def zugang_herstellen(umgebung, post=requests.post, run=subprocess.run):
    """Schritte 2 bis 4. Liefert den Access Token -- erst NACHDEM der neue
    Refresh Token sicher gespeichert ist."""
    repo, pat = umgebung["GITHUB_REPOSITORY"], umgebung["SECRETS_PAT"]
    vorab_pruefen(repo, pat, run=run)
    access, neu = token_erneuern(umgebung["NETATMO_CLIENT_ID"], umgebung["NETATMO_CLIENT_SECRET"],
                                 umgebung["NETATMO_REFRESH_TOKEN"], post=post)
    secret_speichern(repo, pat, neu, run=run)
    print("Netatmo-Zugang erneuert und neuer Refresh Token gespeichert.", flush=True)
    return access


# ------------------------------------------------------------- Netatmo-Daten

def api_get(pfad, access, params=None, get=requests.get, versuche=4):
    """GET an die Netatmo-API. Voruebergehende Stoerungen (keine Verbindung,
    HTTP 5xx, z. B. Code 27 "Service temporarily unavailable") werden mit
    wachsendem Abstand wiederholt; Abrufgrenze und inhaltliche Fehler nicht."""
    letzter = None
    for versuch in range(versuche):
        if versuch:
            time.sleep(PAUSE_S * 5 * 2 ** (versuch - 1))      # 5 s, 10 s, 20 s
        try:
            r = get(f"{API}/api/{pfad}", headers={"Authorization": f"Bearer {access}"},
                    params=params or {}, timeout=60)
        except requests.RequestException as e:
            letzter = f"{pfad}: keine Verbindung ({type(e).__name__})"
            continue
        code = fehlercode(r) if r.status_code != 200 else ""
        if r.status_code == 429 or "Code 26" in code:
            raise GrenzeErreicht(f"{pfad}: Netatmo-Abrufgrenze erreicht ({code or 'HTTP 429'})")
        if r.status_code >= 500:
            letzter = f"{pfad}: HTTP {r.status_code} ({code})"
            continue
        if r.status_code != 200:
            raise AbrufFehler(f"{pfad}: HTTP {r.status_code} ({code})")
        try:
            d = r.json()
        except ValueError:
            raise AbrufFehler(f"{pfad}: Antwort ist kein JSON") from None
        if not isinstance(d, dict) or "body" not in d:
            raise AbrufFehler(f"{pfad}: Antwort ohne Datenteil")
        return d["body"]
    raise AbrufFehler(f"{letzter}, auch nach {versuche} Versuchen. Netatmo ist voruebergehend "
                      f"gestoert; der naechste Lauf versucht es erneut")


def module_finden(body):
    """Ermittelt zur Laufzeit Station, Aussen- und Regenmodul.

    Rueckgabe nur im Speicher; Kennungen werden maskiert und nie gespeichert."""
    geraete = body.get("devices") if isinstance(body, dict) else None
    if not geraete:
        raise AbrufFehler("getstationsdata: keine Wetterstation im Konto gefunden")
    if len(geraete) > 1:
        print(f"Hinweis: {len(geraete)} Stationen im Konto, verwendet wird die erste.", flush=True)
    g = geraete[0]
    maskieren(g.get("_id"))
    gefunden = {"geraet": g.get("_id"), "einrichtung": {}}
    for name, (typ, _groessen, _n) in REIHEN.items():
        modul = next((m for m in g.get("modules", []) if m.get("type") == typ), None)
        gefunden[name] = modul.get("_id") if modul else None
        maskieren(gefunden[name])
        if modul:
            gefunden["einrichtung"][name] = int(modul.get("date_setup") or g.get("date_setup") or 0)
    if not gefunden["geraet"] or not gefunden["aussen"]:
        raise AbrufFehler("getstationsdata: kein Aussenmodul gefunden")
    return gefunden


def werte_aus_body(body, anzahl):
    """getmeasure-Antwort -> {unix: [werte]}. Versteht beide Antwortformen
    (optimize=false: {"<unix>": [..]}; optimize=true: [{beg_time, step_time, value}])."""
    ergebnis = {}
    if isinstance(body, dict):
        for ts, werte in body.items():
            ergebnis[int(ts)] = list(werte)
    elif isinstance(body, list):
        for block in body:
            t, schritt = int(block.get("beg_time", 0)), int(block.get("step_time") or 0)
            for i, werte in enumerate(block.get("value", [])):
                ergebnis[t + i * schritt] = list(werte)
    sauber = {}
    for ts, werte in ergebnis.items():
        if len(werte) != anzahl:
            continue
        zahlen = [None if w is None else round(float(w), 2) for w in werte]
        if all(z is None for z in zahlen):
            continue
        sauber[ts] = zahlen
    return sauber


def messreihe(access, geraet, modul, groessen, beginn, ende=None, get=requests.get):
    params = {"device_id": geraet, "module_id": modul, "scale": "max",
              "type": ",".join(groessen), "date_begin": int(beginn), "limit": LIMIT,
              "optimize": "false", "real_time": "false"}
    if ende is not None:
        params["date_end"] = int(ende)
    body = api_get("getmeasure", access, params, get=get)
    return werte_aus_body(body, len(groessen))


# ------------------------------------------------------------- Speicher

def monat_von(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m")


def laden(verzeichnis=None):
    """Alle gespeicherten Reihen: {"aussen": {unix: [t, h]}, "regen": {unix: [mm]}}."""
    verzeichnis = Path(verzeichnis or DATEN)
    reihen = {name: {} for name in REIHEN}
    for pfad in sorted(verzeichnis.glob("station_*.json")):
        d = json.loads(pfad.read_text(encoding="utf-8"))
        for name in REIHEN:
            for zeile in d.get(name, []):
                reihen[name][int(zeile[0])] = list(zeile[1:])
    return reihen


def stand_laden(pfad=None):
    pfad = Path(pfad or STAND)
    if pfad.exists():
        return json.loads(pfad.read_text(encoding="utf-8"))
    return {"rueckfuellung_fertig": {name: False for name in REIHEN}}


def speichern(reihen, stand, verzeichnis=None):
    """Monatsdateien atomar schreiben (nur Zeit und Aussenwerte), dann den Stand."""
    verzeichnis = Path(verzeichnis or DATEN)
    monate = {}
    for name, werte in reihen.items():
        for ts, zeile in werte.items():
            monate.setdefault(monat_von(ts), {n: [] for n in REIHEN})[name].append([ts, *zeile])
    for monat, inhalt in sorted(monate.items()):
        for name in inhalt:
            inhalt[name].sort(key=lambda z: z[0])
        atomar_schreiben_json(verzeichnis / f"station_{monat}.json",
                              {"monat": monat, "ort": "Stefanskirchen",
                               "felder": {"aussen": ["unix", "temperatur_c", "luftfeuchte_pct"],
                                          "regen": ["unix", "niederschlag_mm"]},
                               **inhalt},
                              indent=None, separators=(",", ":"))
    atomar_schreiben_json(verzeichnis / "stand.json", stand)


# ------------------------------------------------------------- Abrufplanung

def vorwaerts(access, ids, name, vorhanden, jetzt, get=requests.get):
    """Neue Werte seit dem juengsten gespeicherten Zeitpunkt (holt Luecken nach)."""
    _typ, groessen, _n = REIHEN[name]
    beginn = (max(vorhanden) + 1) if vorhanden else int(jetzt) - START_OHNE_DATEN_S
    neu = {}
    for _ in range(MAX_VORWAERTS):
        stueck = messreihe(access, ids["geraet"], ids[name], groessen, beginn, get=get)
        neu.update(stueck)
        if len(stueck) < LIMIT - 10:
            break
        beginn = max(stueck) + 1
        time.sleep(PAUSE_S)
    return neu


def rueckwaerts(access, ids, name, vorhanden, get=requests.get):
    """Vergangenheit fensterweise nachladen, bis zur Einrichtung des Moduls.

    Gibt (neue Werte, fertig) zurueck. Eine erreichte Abrufgrenze beendet nur die
    Rueckfuellung dieses Laufs, nicht den ganzen Lauf."""
    _typ, groessen, _n = REIHEN[name]
    einrichtung = max(int(ids["einrichtung"].get(name) or 0), FRUEHESTENS)
    if not vorhanden:
        return {}, False
    ende = min(vorhanden) - 1
    neu = {}
    for _ in range(MAX_RUECKWAERTS):
        if ende <= einrichtung:
            return neu, True
        beginn = max(ende - FENSTER_S, einrichtung)
        try:
            neu.update(messreihe(access, ids["geraet"], ids[name], groessen, beginn, ende, get=get))
        except GrenzeErreicht as e:
            print(f"::warning title=Rueckfuellung pausiert::{e}", flush=True)
            return neu, False
        ende = beginn - 1
        time.sleep(PAUSE_S)
    return neu, ende <= einrichtung


def abrufen(access, reihen, stand, jetzt, get=requests.get):
    """Alle Abfragen dieses Laufs; schreibt nichts, liefert neue Reihen und Stand."""
    ids = module_finden(api_get("getstationsdata", access, {}, get=get))
    reihen = {n: dict(w) for n, w in reihen.items()}
    stand = json.loads(json.dumps(stand))
    stand.setdefault("rueckfuellung_fertig", {})
    for name in REIHEN:
        if not ids.get(name):
            print(f"Hinweis: kein Modul fuer '{name}' gefunden, Reihe wird uebersprungen.", flush=True)
            continue
        vorher = len(reihen[name])
        try:
            reihen[name].update(vorwaerts(access, ids, name, reihen[name], jetzt, get=get))
            if not stand["rueckfuellung_fertig"].get(name):
                alt, fertig = rueckwaerts(access, ids, name, reihen[name], get=get)
                reihen[name].update(alt)
                stand["rueckfuellung_fertig"][name] = fertig
        except AbrufFehler as e:
            # Die Aussenwerte sind Pflicht. Faellt nur der Regenmesser aus
            # (z. B. leere Batterie), werden die Aussenwerte trotzdem gespeichert.
            if name == "aussen":
                raise
            print(f"::warning title=Regenmesser::{e} -- Regenwerte in diesem Lauf uebersprungen.", flush=True)
            continue
        print(f"{name}: {len(reihen[name]) - vorher} neue Werte, insgesamt {len(reihen[name])}"
              + ("" if stand["rueckfuellung_fertig"].get(name) else " (Vergangenheit wird noch nachgeladen)"),
              flush=True)
    stand["letzte_aktualisierung"] = dt.datetime.fromtimestamp(int(jetzt), dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    return reihen, stand


# ------------------------------------------------------------- Hauptprogramm

def main(argv=None, umgebung=None, post=requests.post, get=requests.get, run=subprocess.run,
         verzeichnis=None):
    argparse.ArgumentParser(description=__doc__.splitlines()[1]).parse_args(argv)
    umgebung = dict(os.environ if umgebung is None else umgebung)
    fehlend = [n for n in PFLICHT if not umgebung.get(n)]
    if fehlend:
        print(f"::error title=Einrichtung unvollstaendig::Es fehlen: {', '.join(fehlend)}", flush=True)
        return 2
    try:
        access = zugang_herstellen(umgebung, post=post, run=run)
    except (SecretFehler, TokenFehler) as e:
        print(f"::error title=Netatmo-Zugang::{e}", flush=True)
        return 1
    verzeichnis = Path(verzeichnis or DATEN)
    try:
        reihen, stand = abrufen(access, laden(verzeichnis), stand_laden(verzeichnis / "stand.json"),
                                time.time(), get=get)
    except AbrufFehler as e:
        print(f"::error title=Netatmo-Daten::{e}. Der bisherige Datenstand bleibt unveraendert.",
              flush=True)
        return 1
    speichern(reihen, stand, verzeichnis)
    return 0


if __name__ == "__main__":
    sys.exit(main())
