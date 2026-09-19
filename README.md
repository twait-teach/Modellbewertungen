# Regenprognose Mühldorf

Ensemble-Meteogramm und Modellvergleich für die DWD-Station Mühldorf am Inn. Die Seite hat zwei
Bereiche:

- **Vorhersage** — drei Ensemble-Meteogramme untereinander: **2-m-Temperatur**,
  **850-hPa-Temperatur** und **aufsummierter Niederschlag**, jeweils für **GFS** und **ECMWF-IFS** (das klassische
  physikalische Modell, nicht die KI-Variante AIFS). Jeder Bereich hat eine eigene, voneinander
  unabhängige Bedienleiste: Modellumschaltung, Auswahl eines gespeicherten Laufs (mit echtem Datum
  und Uhrzeit, z. B. „aktuell · 18.09., 12 UTC"), eigener Schalter für die Einzelmitglieder, eigene
  Legende, eigenes Diagramm und eigene Zahlentabelle.
  Wichtig zur Methodik: Der **Niederschlag** wird zuerst je Mitglied über die Zeit aufsummiert, erst
  danach werden Mittel und Perzentile aus den akkumulierten Kurven gebildet. **Temperaturen werden
  nicht akkumuliert** — dort werden die von der API gelieferten Zeitschritte vom tatsächlichen
  Modellstart bis zum Vorhersagehorizont als durchgehendes Meteogramm gezeigt. Mittel und Perzentile
  werden für jeden einzelnen Zeitpunkt direkt aus den vorhandenen Mitgliedswerten berechnet;
  fehlende Mitgliedswerte werden ausgeschlossen, nie als 0 °C gewertet.
- **Analyse** — wie genau frühere Vorhersagen waren: tagesgenaue Güte (Tag 1–5), Bias, 5-mm-Schwelle,
  Rückblick, Ensemble-Spannweite, und ein Witterungs-/Summenvergleich über die Zeitfenster Tag 1–3,
  4–7 und 8–14 gegen die tatsächlich gemessenen Tagessummen der DWD-Station.

Die Seite läuft ohne eigenen Server und ohne Datenbank. `docs/index.html` ist ein sehr kleiner
Loader, der bei jedem Aufruf die eigentliche Oberfläche aus `docs/app.html` und die aktuellen
Wetterdaten aus `docs/daten.js` mit einem Cache-Buster lädt. Dadurch zeigt auch die normale
Pages-Adresse zuverlässig den aktuellen Stand, ohne dass veraltete Wetterdaten aus dem
Browser-Cache verwendet werden.

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

Der Workflow läuft **halbstündlich** (Minute 17 und 47, UTC). Jeder Durchlauf prüft zuerst nur
kleine Metadaten- bzw. Verfügbarkeitsantworten. Sobald ein Ensemble vollständig vorliegt, wird
sein Lauf-Slot gespeichert und die Seite sofort damit gebaut. Der exakt passende Hauptlauf wird
später über seine feste Initialisierungszeit aus der Open-Meteo-Single-Runs-Schnittstelle in
denselben Slot nachgetragen. Ein inzwischen neuerer Hauptlauf kann dadurch nicht versehentlich
mit einem älteren Ensemble vermischt werden. Haben sich keine Daten geändert, entstehen weder
ein neuer Seitenbau noch ein unnötiger Commit.

Erfasst werden:

| Modell | Datensatz (Ensemble) | erlaubte Läufe | Horizont |
|---|---|---|---|
| GFS | `gfs_seamless` (GEFS, 31 Läufe) | 00, 06, 12, 18 UTC | 16 Tage |
| ECMWF-IFS | `ecmwf_ifs025` (51 Läufe) | **nur** 00 und 12 UTC | 15 Tage |

Die 06- und 18-UTC-Ensembleläufe von ECMWF-IFS reichen offiziell nur rund sechs Tage weit und
werden deshalb absichtlich **nicht** als 15-Tage-Lauf erfasst — ein Live-Test während der
Entwicklung hat das bestätigt: ein solcher Lauf bricht nach wenigen Tagen tatsächlich ab.

Für die tagesgenaue Analyse (Seite „Analyse") gilt weiterhin: erfasst wird nur der **00-UTC-Lauf**,
damit die Kalendertag-Einträge in `daten/forecasts_*.json` aus einem Guss stammen. Auch hier prüft
das Skript vor jedem Abruf per Metadaten, welcher Lauf tatsächlich veröffentlicht ist — open-meteo
liefert bei einem noch nicht fertigen 00-UTC-Lauf klaglos den vorherigen, ohne Fehlermeldung. Ist
der 00-UTC-Lauf für ein Modell schon vollständig eingetragen, überspringt auch dieses Skript den
erneuten Abruf für den Rest des Tages; die laufenden Metadaten-Prüfungen zeigen bei Bedarf
(`modelllaeufe`, `lauf_wie_erwartet`, `laufhinweise`) an, was tatsächlich ankam.

Fällt ein Abruf ganz aus, wiederholt das Skript viermal mit wachsendem Abstand. Danach bleibt das
Feld leer — **nie ein geschätzter Wert**.

---

## Was nachholbar ist und was nicht

Vergangene **Hauptläufe** (für die tagesgenaue Analyse) lassen sich bei open-meteo rückwirkend
abrufen, rund 90 Tage weit. Genau daher stammt die Vorgeschichte in `daten/history_*.json`, und
`skripte/historie.py` schließt damit auch Lücken.

**Ensembles gibt es nur live** — sowohl für die tagesgenaue Analyse als auch für das
Meteogramm auf der Vorhersage-Seite. Ein Lauf, der ausfällt oder falsch erkannt wird, fehlt in der
Ensemble-Statistik für immer; für das Meteogramm bedeutet das schlicht, dass für diesen Lauf kein
Dokument entsteht. Messwerte sind unkritisch: das DWD-Archiv reicht rund 500 Tage zurück, ältere
Monatsdateien bleiben unabhängig davon erhalten (siehe unten, „Speicherung der Messwerte").

**Für das Meteogramm** werden zudem nur die letzten 12 Läufe je Modell mit vollen
Ensemblemitgliedern aufbewahrt (`skripte/sammeln_vorhersage.py`, Konstante `AUFBEWAHREN`) — ältere
Laufdateien werden automatisch gelöscht. Das ist beabsichtigt: die Rohdaten mit 30–50 Mitgliedern
pro Lauf müssen für den Laufvergleich nicht unbegrenzt archiviert werden.

---

## Aufbau

```
daten/                       der Datenbestand, in git versioniert
  forecasts_JJJJ-MM-TT.json     ein Eintrag je Kalendertag: 14 Vorlaufzeiten × 2 Modelle
                                 (für die tagesgenaue Analyse und den Witterungsvergleich)
  messungen_JJJJ-MM.json        Tagessummen der Station, ein Dokument je Monat
  history_gfs.json              rückwirkend abgerufene Hauptläufe, Vorlauf 1–7
  history_ecmwf.json
  vorhersage/                   Ensemble-Meteogrammdaten, ein Dokument je erkanntem Modelllauf
    gfs_JJJJ-MM-TTThh.json         (nur die letzten 12 Läufe je Modell, siehe oben)
    ecmwf_JJJJ-MM-TTThh.json
docs/index.html               kleiner, dauerhaft stabiler Loader für die normale Pages-Adresse
docs/app.html                 Oberfläche und Auswertungslogik — wird gebaut
docs/daten.js                 aktuelle Wetterdaten — wird bei Datenänderungen neu gebaut
skripte/
  gemeinsam.py                 geteilte Hilfsfunktionen: Abruf mit Wiederholung, atomares
                                 Schreiben, Perzentil
  sammeln.py                    holt die tagesgenauen Hauptlauf-/Ensemble-Kennzahlen und die
                                 Stationsmesswerte (Analyse-Seite)
  sammeln_vorhersage.py         holt die vollen Ensemblemitglieder je Modelllauf (Meteogramm
                                 auf der Vorhersage-Seite)
  historie.py                   lädt vergangene Hauptläufe nach
  bauen.py                      baut aus daten/ + vorlage.html die Seite
  vorlage.html                  Gestaltung und Auswertungslogik (beide Seiten)
tests/                        automatisierte Tests (pytest; einige nutzen Playwright und
                                 brauchen dafür `playwright install chromium`)
```

Von Hand laufen lassen:

```bash
pip install requests pytest
python3 -m pytest tests/ -q --ignore=tests/test_js_analyse.py   # Selbsttests ohne Browser
python3 skripte/sammeln.py --alles              # tagesgenaue Daten + Messwerte
python3 skripte/sammeln_vorhersage.py --modell beide  # Ensemble-Meteogrammdaten
python3 skripte/historie.py                     # Vorgeschichte der Hauptläufe
python3 skripte/bauen.py                        # docs/index.html, app.html und daten.js neu bauen
```

Änderungen am Aussehen gehören in `skripte/vorlage.html`; die Dateien unter `docs/` werden vom
Bau-Skript erzeugt und nicht von Hand geändert. Bei reinen Datenaktualisierungen ändert sich nur
`docs/daten.js`. Das vermeidet Konflikte zwischen automatisch aktualisierten Daten und manuellen
Änderungen an der Oberfläche.

Die beiden Temperaturdiagramme verwenden je Bereich und ausgewähltem Laufindex dieselbe
dynamische Y-Achse für GFS und ECMWF. Sie umfasst die Extremwerte beider Modelle mit zusätzlichem
Rand; die ganzzahligen Teilstriche liegen je nach Spannweite 1, 2 oder höchstens 5 °C auseinander.

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

**Speicherung der Messwerte:** Das DWD-„akt"-Archiv liefert nur ein rollierendes Zeitfenster von
rund 500 Tagen. `skripte/sammeln.py` führt neu abgerufene Tage deshalb mit der vorhandenen
Monatsdatei zusammen, statt sie zu überschreiben — ältere Tage, die inzwischen außerhalb dieses
Fensters liegen, bleiben dadurch erhalten; nur Tage, die der aktuelle Abruf tatsächlich liefert,
werden aktualisiert (etwa bei nachträglichen DWD-Korrekturen).

**Vorhersagen:** [open-meteo.com](https://open-meteo.com) — Hauptläufe `ecmwf_ifs025` und
`gfs_seamless`, Ensembles `ecmwf_ifs025` (51 Läufe) und `gfs_seamless` (31 Läufe — `gfs025` allein
liefert Mitgliederdaten nur bis Tag 10). Open-Meteo interpoliert Ensemblewerte auf ein
Stundenraster. Für die Meteogramme werden daraus wieder modellnahe Zeitpunkte gewählt: GFS
3-stündlich bis +240 Stunden und danach 6-stündlich, ECMWF durchgehend 3-stündlich. Die
Diagrammachse verwendet echte Zeitstempel und bleibt maßstabstreu.
Beim **GFS** erscheinen der deterministische Hauptlauf als schwarze durchgezogene Linie und der
Kontrolllauf schwarz gestrichelt. Beim **ECMWF** wird nur der operationelle Hauptlauf schwarz
durchgezogen gezeigt; eine zweite Kontrolllinie wird bewusst nicht dargestellt. Die
Ensemblekurven sind bei den Temperaturen rötlich (GFS) bzw. gelblich (ECMWF), beim Niederschlag
dunkelblau (GFS) bzw. hellblau (ECMWF).
Die Statuszeile reserviert immer dieselbe Höhe, damit die Diagramme beim Umschalten nicht nach
oben oder unten springen. Temperaturachsen tragen nur ganzzahlige Werte. Zur Orientierung wird
bei 2 m die 10-°C-Linie und bei 850 hPa die 0-°C-Linie kräftiger eingezeichnet; diese Referenz ist
bei GFS und ECMWF jeweils identisch.
Eine fertige Ensemble-Mittelwert-Reihe liefert die
Schnittstelle nicht; Mittel, Perzentile und der Anteil der Läufe über 5 mm werden aus den
Einzelläufen selbst gebildet — für das Meteogramm ausdrücklich **aus den bereits je Mitglied
akkumulierten Kurven**, nicht aus aufsummierten Intervall-Perzentilen (die beiden Wege liefern bei
Perzentilen unterschiedliche, und nur der erste methodisch korrekte, Ergebnisse).

**Abgerufene Variablen:** `precipitation`, `temperature_2m` und `temperature_850hPa`, jeweils im
von Open-Meteo bereitgestellten Stundenraster. Beide Temperaturvariablen werden ohne Aggregation
an den modellnahen 3-/6-Stunden-Zeitpunkten dargestellt. Beim Niederschlag werden die Stundenmengen
zunächst zu jedem 3-/6-Stunden-Modellintervall addiert und dann je Ensemblemitglied fortlaufend
aufsummiert; erst danach entstehen Mittel und Perzentile. Es werden weder Tagesmittel noch
Tagessummen als Kurvenstützstellen verwendet. Der Abruf schließt den Vortag ein, damit bei einem erst
nach Mitternacht vollständig verfügbaren 18-UTC-Lauf auch dessen erste Stunden erhalten bleiben.
Niederschlag und beide Temperaturreihen kommen je Quelle gebündelt aus **einem** Abruf: einmal
für das Ensemble und einmal für den passenden Hauptlauf. Beide Teile dürfen zeitversetzt
eintreffen und werden über die Initialisierungszeit sicher demselben Lauf-Slot zugeordnet.

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
