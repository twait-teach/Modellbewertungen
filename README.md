# Regenprognose Mühldorf

Vergleicht täglich die Niederschlagsvorhersagen von **ECMWF** und **GFS** — jeweils Hauptlauf und
Ensemble-Mittel — gegen die tatsächlich gemessenen Tagessummen der DWD-Station Mühldorf am Inn.
Die Auswertung steht als Webseite im Ordner `docs/` und wird zweimal täglich automatisch erneuert.

Die Seite läuft ohne Server und ohne Datenbank: `docs/index.html` ist eine einzige Datei mit allen
Daten darin.

---

## Einrichten (einmalig, etwa zehn Minuten)

**1. Repo anlegen.** Auf github.com ein neues Repository erstellen, zum Beispiel
`regen-muehldorf`. Öffentlich, sonst funktioniert GitHub Pages im kostenlosen Tarif nicht.
Kein README, keine .gitignore ankreuzen — die sind hier schon dabei.

**2. Dateien hochladen.** Im leeren Repo auf *uploading an existing file* klicken und den
kompletten Inhalt dieses Ordners hineinziehen. Wichtig: Der Ordner `.github` muss mit —
Browser blenden Ordner mit Punkt am Anfang manchmal aus. Falls er beim Ziehen fehlt, die Datei
`.github/workflows/aktualisieren.yml` einzeln über *Create new file* anlegen und den Inhalt
einfügen (der Pfad lässt sich im Dateinamen-Feld mit Schrägstrichen eintippen).

**3. Actions schreiben lassen.** *Settings → Actions → General → Workflow permissions* →
**Read and write permissions** auswählen und speichern. Ohne das darf der Automatik-Lauf die
aktualisierten Daten nicht zurückschreiben.

**4. Seite veröffentlichen.** *Settings → Pages* → Source: **Deploy from a branch**,
Branch: `main`, Ordner: **/docs** → Save. Nach ein bis zwei Minuten steht die Adresse dort:
`https://<dein-name>.github.io/regen-muehldorf/`

**5. Einmal von Hand starten.** *Actions → Daten holen und Seite bauen → Run workflow*.
Das prüft in einem Zug, ob Berechtigungen und Zeitplan stimmen.

---

## Wie es läuft

| Zeit (UTC) | Was passiert |
|---|---|
| 10:25 | GFS holen — Hauptlauf und Ensemble |
| 11:55 | ECMWF holen, Messwerte der Station nachtragen, Seite neu bauen |
| sonntags 11:55 | zusätzlich die Vorgeschichte der Hauptläufe auffrischen |

Die beiden Zeiten sind kein Zufall. Beide Modelle rechnen viermal täglich (00, 06, 12, 18 UTC),
und erfasst werden soll nur der **00-UTC-Lauf**, damit alle zehn Vorhersagetage aus einem Guss
stammen. Die Daten brauchen nach dem Lauf unterschiedlich lange, bis sie abrufbar sind:

| | Verzögerung | 00Z abrufbar ab | wird ersetzt ab |
|---|---|---|---|
| GFS-Ensemble | 5,8 h | ~05:50 | ~11:50 |
| GFS Hauptlauf | 5,9–7,0 h | ~07:00 | ~13:00 |
| ECMWF Hauptlauf | 7,2 h | ~07:15 | ~13:10 |
| ECMWF-Ensemble | 9,5 h | ~09:30 | ~15:30 |

Daraus ergeben sich die Fenster: GFS etwa 07:00–11:50 UTC, ECMWF etwa 09:30–13:10 UTC. Deshalb
zwei getrennte Läufe statt einem.

**Der Haken, den man kennen muss:** Ist der 00-UTC-Lauf noch nicht fertig, liefert open-meteo
klaglos den vorherigen — ohne Fehlermeldung. Man bekommt dann ältere Daten und merkt es nicht.
Das Sammelskript prüft deshalb vor jedem Abruf, welcher Lauf tatsächlich veröffentlicht ist, und
schreibt das in den Tageseintrag (`modelllaeufe`, `lauf_wie_erwartet`, `laufhinweise`). Wer wissen
will, ob die Uhrzeiten passen, schaut nach ein paar Tagen in `daten/forecasts_*.json` unter
`verfuegbar_seit` nach.

Fällt ein Abruf ganz aus, wiederholt das Skript viermal mit wachsendem Abstand. Danach bleibt das
Feld leer — **nie ein geschätzter Wert**.

---

## Was nachholbar ist und was nicht

Vergangene **Hauptläufe** lassen sich bei open-meteo rückwirkend abrufen, rund 90 Tage weit. Genau
daher stammt die Vorgeschichte in `daten/history_*.json`, und `skripte/historie.py` schließt damit
auch Lücken.

**Ensembles gibt es nur live.** Ein Tag, an dem der Lauf ausfällt, fehlt in der Ensemble-Statistik
für immer. Messwerte sind unkritisch: das DWD-Archiv reicht rund 500 Tage zurück.

---

## Aufbau

```
daten/                     der Datenbestand, in git versioniert
  forecasts_JJJJ-MM-TT.json   ein Eintrag je Tag: 10 Vorlaufzeiten × 2 Modelle
  messungen_JJJJ-MM.json      Tagessummen der Station, ein Dokument je Monat
  history_gfs.json            rückwirkend abgerufene Hauptläufe, Vorlauf 1–7
  history_ecmwf.json
docs/index.html            die fertige Seite — wird gebaut, nicht von Hand geändert
skripte/
  sammeln.py               holt Vorhersagen und Messwerte
  historie.py              lädt vergangene Hauptläufe nach
  bauen.py                 baut aus daten/ + vorlage.html die Seite
  vorlage.html             Gestaltung und Auswertungslogik
```

Von Hand laufen lassen:

```bash
pip install requests
python3 skripte/sammeln.py --alles     # beide Modelle und Messwerte
python3 skripte/historie.py            # Vorgeschichte der Hauptläufe
python3 skripte/bauen.py               # docs/index.html neu bauen
```

Änderungen am Aussehen gehören in `skripte/vorlage.html`; `docs/index.html` wird bei jedem Lauf
überschrieben.

---

## Zwei Fallstricke

**GitHub schaltet Zeitpläne ab.** In Repos ohne menschliche Aktivität werden geplante Abläufe nach
60 Tagen stillgelegt. Commits, die der Automatik-Lauf selbst macht, zählen dafür nicht. Einmal im
Monat irgendetwas im Repo tun — eine Datei bearbeiten, den Workflow von Hand starten — genügt.
GitHub schickt vorher eine Warnung per Mail.

**Der Zeitplan ist nicht auf die Minute genau.** Bei Last verschieben sich geplante Läufe bei
GitHub um einige Minuten. Die Fenster oben haben dafür Luft; sollte es doch einmal danebengehen,
steht es im Tageseintrag.

---

## Daten und Methode

**Messwerte:** DWD-Klimastation Mühldorf am Inn (ID 03366, 48,279° N / 12,502° E, 406 m),
stündliche Niederschlagswerte aus dem offenen Datenarchiv des Deutschen Wetterdienstes, zu
Tagessummen von 0 bis 24 Uhr Ortszeit verdichtet. Nur Tage mit vollständigen 24 Stundenwerten
zählen.

Bewusst **nicht** der fertige DWD-Tageswert (RSK): der läuft von 06 bis 06 UTC und ist gegen das
Tagesraster der Vorhersagen um Stunden versetzt. Am 10./11. September 2026 hätte das 5,6 mm
komplett auf den falschen Tag geschoben.

**Vorhersagen:** [open-meteo.com](https://open-meteo.com) — Hauptläufe `ecmwf_ifs025` und
`gfs_seamless`, Ensembles `ecmwf_ifs025` (51 Läufe) und `gfs025` (31 Läufe). Eine fertige
Ensemble-Mittelwert-Reihe liefert die Schnittstelle nicht; Mittel, Perzentile und der Anteil der
Läufe über 5 mm werden aus den Einzelläufen selbst gebildet.

**Was der Vergleich nicht kann:** Die Station liegt rund 4 km vom Modellgitterpunkt entfernt. Bei
Schauern und Gewittern können allein daraus mehrere Millimeter Unterschied entstehen — ein Teil des
ausgewiesenen Fehlers ist keine Fehlleistung des Modells. Und ein Ensemble-Mittel schneidet beim
mittleren Fehler fast zwangsläufig besser ab, weil Mittelung Spitzen glättet; ob es einen
Starkregentag als solchen erkennt, ist eine andere Frage. Dafür steht die 5-mm-Trefferquote auf
der Seite.

**Quellen:** Deutscher Wetterdienst, Climate Data Center (Datenlizenz Deutschland – Namensnennung,
siehe [GeoNutzV](https://www.dwd.de/DE/service/copyright/copyright_node.html)) ·
open-meteo.com (CC BY 4.0), Modelldaten von NOAA/NCEP und ECMWF.

---

## Rechtliches

Wer eine Seite rein privat und ohne kommerziellen Zweck betreibt, braucht in Deutschland
üblicherweise kein Impressum — die Pflicht nach § 5 DDG gilt für geschäftsmäßige Angebote. Die
Abgrenzung ist im Einzelfall aber nicht immer eindeutig, und das hier ist keine Rechtsberatung. Im
Zweifel ist ein kurzes Impressum die einfachere Lösung. Die Nutzung von open-meteo ist für
nichtkommerzielle Zwecke frei.
