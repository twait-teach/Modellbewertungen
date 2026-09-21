# Vorhersage und Analyse Mühldorf

Ensemble-Meteogramm und Modellvergleich für die DWD-Station Mühldorf am Inn sowie die Messwerte der
eigenen Wetterstation Stefanskirchen. Die Seite hat vier Reiter: **Vorhersage Mühldorf**, **Station
heute**, **Station Verlauf** und **Niederschlagsanalyse** (Adressen `#vorhersage`, `#station-heute`,
`#station-verlauf`, `#analyse`). Die beiden Stationsreiter sind unten unter „Wetterstation
Stefanskirchen" beschrieben. Zu den beiden Mühldorf-Bereichen:

- **Vorhersage** — drei Ensemble-Meteogramme untereinander: **2-m-Temperatur**,
  **850-hPa-Temperatur** und **aufsummierter Niederschlag**, jeweils für **GFS** und **ECMWF-IFS** (das klassische
  physikalische Modell, nicht die KI-Variante AIFS). Jeder Bereich hat eine eigene, voneinander
  unabhängige Bedienleiste: Modellumschaltung, Auswahl eines gespeicherten Laufs (mit echtem Datum
  und Uhrzeit, z. B. „aktuell · 18.09., 12 UTC"), eigener Schalter für die Einzelmitglieder, eigene
  Legende, eigenes Diagramm und eigene Zahlentabelle. Unter jeder Überschrift steht ein Satz Kurzhinweis;
  die ausführliche Erklärung (Mitglieder, Mittel, Perzentilband, Kontroll-/Hauptlauf, Aufsummierung,
  Skala und Bezugslinie) liegt einklappbar unter dem Diagramm („Erklärung und Darstellung").
  Wichtig zur Methodik: Der **Niederschlag** wird zuerst je Mitglied über die Zeit aufsummiert, erst
  danach werden Mittel und Perzentile aus den akkumulierten Kurven gebildet. **Temperaturen werden
  nicht akkumuliert** — dort werden die von der API gelieferten Zeitschritte vom tatsächlichen
  Modellstart bis zum Vorhersagehorizont als durchgehendes Meteogramm gezeigt. Mittel und Perzentile
  werden für jeden einzelnen Zeitpunkt direkt aus den vorhandenen Mitgliedswerten berechnet;
  fehlende Mitgliedswerte werden ausgeschlossen, nie als 0 °C gewertet.
- **48h Wetter** — ein Diagramm für die nächsten 48 Stunden: Temperaturkurve (Mittel aus Hauptlauf und
  Ensemble-Mittel, leicht geglättet) mit dem 10.–90.-Perzentil-Band, stündlicher Niederschlag als Balken
  mit eigener Skala rechts, Wettersymbole im 3-Stunden-Abstand (6 auf schmalen Bildschirmen) und grau
  hinterlegte Nachtstunden. Umschaltbar zwischen GFS und ECMWF-IFS.
- **Niederschlagsanalyse** (früher „Analyse") — wie genau frühere Vorhersagen waren: tagesgenaue Güte (Tag 1–5), Bias, 5-mm-Schwelle,
  Rückblick, Ensemble-Spannweite, und ein Witterungs-/Summenvergleich über die Zeitfenster Tag 1–3,
  4–7 und 8–14 gegen die tatsächlich gemessenen Tagessummen der DWD-Station.

Die Seite läuft ohne eigenen Server und ohne Datenbank. `docs/index.html` ist ein sehr kleiner
Loader, der bei jedem Aufruf die eigentliche Oberfläche aus `docs/app.html` und die aktuellen
Wetterdaten aus `docs/daten.js` mit einem Cache-Buster lädt. Dadurch zeigt auch die normale
Pages-Adresse zuverlässig den aktuellen Stand, ohne dass veraltete Wetterdaten aus dem
Browser-Cache verwendet werden. Ein Hash in der Adresse bleibt dabei erhalten:
`…/Modellbewertungen/#analyse` öffnet direkt die Analyse-Seite. Öffnet man `docs/app.html` lokal
(`file://`), funktioniert die Seite ebenfalls, solange `docs/daten.js` daneben liegt. Fehlt diese
Datei oder lässt sie sich nicht laden, zeigt die Seite eine ausdrückliche Fehlermeldung, statt so
zu tun, als gäbe es nur noch keine Läufe.

---

## Einrichten (einmalig, etwa zehn Minuten)

**1. Repo anlegen.** Auf github.com ein neues Repository erstellen, zum Beispiel
`regen-muehldorf`. Öffentlich, sonst funktioniert GitHub Pages im kostenlosen Tarif nicht.
Kein README, keine .gitignore ankreuzen — die sind hier schon dabei.

**2. Dateien hochladen.** Im leeren Repo auf *uploading an existing file* klicken und den
kompletten Inhalt dieses Ordners hineinziehen. Wichtig: Der Ordner `.github` muss mit —
Browser blenden Ordner mit Punkt am Anfang manchmal aus. Falls er beim Ziehen fehlt, die Datei
`.github/workflows/aktualisieren.yml` (und, für die Browsertests, `.github/workflows/tests.yml`)
einzeln über *Create new file* anlegen und den Inhalt
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
mit einem älteren Ensemble vermischt werden. Solange Open-Meteo noch genau diesen Lauf ausgibt, wird sein
Ensemble bei jedem Durchlauf erneut abgerufen und der Slot nur bei fachlich geänderten Werten ersetzt (der
Langfristteil eines GFS-Laufs ab +240 h wird dort nachweislich später fertig; der Hauptlauf bleibt dabei
erhalten). Haben sich keine Daten geändert, entstehen weder
ein neuer Seitenbau noch ein unnötiger Commit:

- `sammeln.py` schreibt `daten/forecasts_<Tag>.json` nur bei einer **fachlichen** Änderung. Der
  Abrufzeitpunkt (`abgerufen`) zählt dafür nicht; bleibt sonst alles gleich, bleibt auch der
  bisherige Abrufzeitpunkt stehen.
- `bauen.py` leitet den angezeigten „Datenstand" aus den Quelldaten ab, nicht aus der Uhr. Gleiche
  Wetterdaten ergeben deshalb bytegleich dieselbe `docs/daten.js`; `docs/index.html` und
  `docs/app.html` bleiben bei reinen Datenläufen unverändert.
- `historie.py` entscheidet selbst, ob etwas zu tun ist: erst ab 12:00 UTC und nur für Modelle, deren
  Feld `stand` in `daten/history_*.json` älter als der heutige Tag ist. Das gilt auch beim manuellen
  Start; `--erzwingen` hebt die Prüfung bewusst auf.
- Beim Anlegen eines Ensemble-Slots werden die Metadaten vor dem Abruf gelesen und unmittelbar vor dem
  Speichern noch einmal geprüft. Hat Open-Meteo währenddessen auf den nächsten Lauf umgeschaltet,
  wird nichts gespeichert; der nächste halbstündliche Durchlauf versucht es erneut.
- Wird der abschließende Push abgelehnt, weil inzwischen jemand anders nach `main` gepusht hat,
  schlägt der Lauf sichtbar fehl. Es gibt bewusst weder ein automatisches Rebase noch einen
  Force-Push; der nächste geplante Lauf beginnt auf dem neuen Stand.

Erfasst werden:

| Modell | Datensatz (Ensemble) | erlaubte Läufe | Horizont |
|---|---|---|---|
| GFS | `gfs_seamless` (GEFS, 31 Mitglieder inkl. Kontrolllauf) | 00, 06, 12, 18 UTC | 16 Tage |
| ECMWF-IFS | `ecmwf_ifs025` (51 Mitglieder inkl. Kontrolllauf) | **nur** 00 und 12 UTC | 15 Tage |

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
`skripte/historie.py` schließt damit auch Lücken. Jeder Abruf wird mit dem Bestand **zusammengeführt**:
Tage, die aus dem 90-Tage-Fenster der API fallen, bleiben dauerhaft erhalten (bis 09/2026 wurde die Datei
jedes Mal ersetzt; die dabei verlorenen Tage 14.–19.06.2026 stehen in `history_*_nachtrag.json` und werden
beim nächsten Lauf übernommen).

**Tägliche Ensemble-Kennzahlen** (`daten/forecasts_*.json`, eine Datei je Tag mit Hauptlauf, Ensemble-Mittel
und Perzentilen für 14 Vorlaufzeiten) werden nie gelöscht. Die Seite bettet Messwerte der letzten 14 Monate
ein (`MONATE_RUECKWAERTS` in `bauen.py`), also genug für eine volle Jahresauswertung.

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
docs/index.html               kleiner, dauerhaft stabiler Loader für die normale Pages-Adresse;
                                 leitet auf app.html?v=<Zeit> weiter und reicht einen Hash durch
docs/app.html                 Oberfläche und Auswertungslogik — ändert sich nur bei Code-/Designänderungen
docs/daten.js                 aktuelle Wetterdaten — ändert sich nur bei Datenänderungen
docs/handy.html               Loader der Handy-Fassung „WoazeWeather" (Start mit „Station heute")
docs/handy-app.html           Handy-Fassung: dieselbe Seite plus handy.css/handy.js (siehe Abschnitt „Handy-Fassung")
docs/handy-sw.js              winziger Dienst, der nichts zwischenspeichert (nötig für „App installieren")
docs/handy/                   manifest.webmanifest und die Symbole (Sonne mit WW)
skripte/
  gemeinsam.py                 geteilte Hilfsfunktionen: Abruf mit Wiederholung, atomares
                                 Schreiben, Perzentil und die eine Formatprüfung für Laufdateien
                                 (`ist_aktuelles_format`, gilt für Sammler, Builder und – als
                                 Spiegel in JavaScript – die Seite)
  sammeln.py                    holt die tagesgenauen Hauptlauf-/Ensemble-Kennzahlen und die
                                 Stationsmesswerte (Analyse-Seite)
  sammeln_vorhersage.py         holt die vollen Ensemblemitglieder je Modelllauf (Meteogramm
                                 auf der Vorhersage-Seite)
  historie.py                   lädt vergangene Hauptläufe nach (idempotent, siehe oben)
  bauen.py                      baut aus daten/ + vorlage.html die Seite
  vorlage.html                  Gestaltung und Auswertungslogik (beide Seiten)
  handy.css, handy.js           nur für die Handy-Fassung (werden von bauen.py in handy-app.html eingebaut)
  handy_symbol.py               zeichnet das Symbol neu (nur bei Bedarf, braucht Pillow)
tests/                        automatisierte Tests (pytest)
  test_js_analyse.py            Browsertests: Auswertung, Seitenaufbau, Loader, Ladefehler
  test_vorhersage_darstellung.py  Browsertests: Breite, Erklärungen, Achsen, Bezugslinie, Layoutsprung,
                                 Tageslinien (beide brauchen Playwright + Chromium)
  test_zeitverarbeitung.py      Sommerzeit-Tests der Zeitverarbeitung (ohne Browser)
  test_handy.py                 Handy-Fassung: Bau, Trennung von app.html, Manifest, Symbole (ohne Browser)
  test_handy_browser.py         Handy-Fassung im Browser: Start, schlanke Ansicht, Zwei-Finger-Zoom (Playwright)
  die übrigen Dateien           schnelle Tests ohne Browser
.github/workflows/
  aktualisieren.yml             halbstündlicher Daten-Workflow (nur schnelle Tests, kein Chromium)
  tests.yml                     vollständige Tests inkl. Browsertests bei Änderungen an
                                 Programm, Vorlage, Tests oder Workflows
```

Von Hand laufen lassen:

```bash
pip install requests pytest
python3 -m pytest tests/ -q --ignore=tests/test_js_analyse.py --ignore=tests/test_vorhersage_darstellung.py   # schnelle Tests ohne Browser
# Browsertests: pip install playwright && python3 -m playwright install chromium
python3 -m pytest tests/test_js_analyse.py tests/test_vorhersage_darstellung.py -q
python3 skripte/sammeln.py --alles              # tagesgenaue Daten + Messwerte
python3 skripte/sammeln_vorhersage.py --modell beide  # Ensemble-Meteogrammdaten
python3 skripte/historie.py                     # Vorgeschichte der Hauptläufe (nur ab 12 UTC und bei
                                                # veraltetem Stand; --erzwingen überspringt die Prüfung)
python3 skripte/bauen.py                        # docs/index.html, app.html und daten.js neu bauen
```

Änderungen am Aussehen gehören in `skripte/vorlage.html`; die Dateien unter `docs/` werden vom
Bau-Skript erzeugt und nicht von Hand geändert. Bei reinen Datenaktualisierungen ändert sich nur
`docs/daten.js`. Das vermeidet Konflikte zwischen automatisch aktualisierten Daten und manuellen
Änderungen an der Oberfläche.

**Aufgabenteilung der drei Veröffentlichungsdateien:** `index.html` ist der winzige, stabile Einstieg
(fest, ändert sich praktisch nie), `app.html` ist die Oberfläche samt Auswertungslogik (ändert sich nur
bei Code- oder Designänderungen), `daten.js` enthält ausschließlich die laufenden Wetterdaten (wird vom
Workflow bei Datenänderungen neu erzeugt).

**Entwicklungs-Bundles** (Git-Bundles oder Patches für Programmänderungen) enthalten deshalb weder
`docs/daten.js` noch etwas unter `daten/` (Ausnahme: ausdrücklich freigegebene Aufräumarbeiten). Sonst
könnte ein älterer Entwicklungsstand automatisch eingegangene, neuere Wetterdaten überschreiben oder
mit ihnen kollidieren. Wer lokal testet und `bauen.py` laufen lässt, verwirft die dabei veränderte
`docs/daten.js` vor dem Commit (`git checkout docs/daten.js`).

**Vorhersage-Ansicht.** Der Inhalt ist auf 1400 px Breite begrenzt und nutzt diese Breite voll aus; die
Diagramme werden auf die tatsächliche Breite gezeichnet (Schrift und Linien bleiben unskaliert) und beim
Ändern der Fenstergröße neu gezeichnet. Auf dem Handy werden sie ebenfalls auf die Bildschirmbreite gezeichnet
(mindestens 320 px, dann kürzere Achsentitel und Niveautafel); erst darunter scrollt der Diagrammrahmen, nie
die Seite. Die Analyse-Seite bleibt bei höchstens 980 px Breite; ihre Diagramme werden ebenfalls auf die
tatsächliche Breite (höchstens 900 px, Streudiagramm 620 px) gezeichnet und beim Einblenden neu vermessen.

**Niederschlagsachse.** Auch die aufsummierte Niederschlagsmenge verwendet für GFS und ECMWF-IFS
dieselbe Achse: Sie endet 20 % über dem höchsten Wert des 90.-Perzentil-Bands **beider** Modelle
(mindestens 5 mm). Ohne das änderte sich beim Modellwechsel die Skala, und beide Modelle sähen gleich
nass aus. Einzelne Mitglieder darüber laufen bewusst aus dem Bild.

**Kopf je Reiter.** Jeder Reiter hat eine eigene, stets einzeilige Überschrift („Vorhersage Mühldorf",
„48 Stunden Mühldorf", „Niederschlagsanalyse", „Wetterstation Stefanskirchen") und eine eigene, kurze
Einleitungszeile; gesteuert über `[data-fuer]` und `body[data-seite]`. Die Schriftgröße skaliert mit der
Breite (`clamp`), die Zeilen sind auf `nowrap` gesetzt — auch bei 320 px bleibt es eine Zeile.

**Kein Sprung beim Reiterwechsel.** `kopfzoneMessen()` schaltet die Reiter einmal unsichtbar durch, liest
die Höhen von Kopf und Einleitungszeile und reserviert jeweils die größte; Hinweise (Datenfehler,
veraltete Stationsdaten) stehen unter der Reiterleiste. Damit die Messung vor und nach dem Füllen der
Zeitangaben gleich ausfällt, reservieren die Standangaben ihre Breite (`min-width` in `ch`), und die
Wetterstation misst nach dem Laden noch einmal nach. Rechts im Kopf steht auf den Mühldorf-Reitern ein
gemeinsamer **Datenstand** (neuester Abruf aller Quelldaten, Ortszeit) — nicht der Lauf eines einzelnen
Diagramms. Der Kopf ist bewusst knapp gehalten (Standangabe
zweizeilig inklusive „406 m ü. NN", weniger Abstände), damit die Diagramme möglichst weit oben stehen.

Die beiden Temperaturdiagramme verwenden je Bereich und ausgewähltem Laufindex dieselbe
Y-Achse für GFS und ECMWF. Die Grenzen folgen den kleinsten und größten dargestellten Werten beider
Modelle (alle Mitglieder, Mittel, Perzentilband, Kontroll- und Hauptlauf) mit einem Rand von 5 % der
Spannweite (mindestens 1, höchstens 1,5 °C) und sind ganzzahlig, aber keine Vielfachen von 5.
Die Gitterlinien werden getrennt davon berechnet: alle 5 °C, bei einer Spannweite bis 9 °C alle 1 °C.
Beispiel: Werte von 1,7 bis 28,8 °C ergeben die Achse 0 bis 31 °C mit Linien bei 0, 5, …, 30.

**Bezugslinie.** Die früher feste 10-°C-/0-°C-Linie ist durch eine dynamische, bewusst neutral benannte
Bezugslinie ersetzt. Das „Temperaturniveau" ist der zeitgewichtete Mittelwert (Trapezregel, dadurch 3-
und 6-Stunden-Schritte richtig gewichtet) der beiden Ensemble-Mittelkurven über den gemeinsamen
Zeitraum beider Modelle, GFS und ECMWF gleich gewichtet. Die „Bezugslinie" ist die nächstgelegene
5-°C-Gitterlinie zu diesem Niveau (bei Gleichstand die höhere); enthält die Achse keine 5-°C-Linie,
wird nur das Niveau genannt. Sie ist kein Grenzwert und enthält keine Bewertung wie „mild" oder „kalt".
Sie ist grau gezeichnet, damit sie nicht mit dem schwarzen Hauptlauf verwechselt wird.

**Verspätete Läufe.** Ist der neueste gespeicherte Lauf eines Modells älter als 36 Stunden (Konstante
`LAUF_VERALTET_H`), nennt die Statuszeile über dem Diagramm sein Alter.

**Kein Layoutsprung.** Höhe von Bedienleiste, Laufinfo, Statusmeldung und Legende werden beim Start und bei
jeder Breitenänderung für alle Varianten (beide Modelle, alle Läufe, Mitglieder ein/aus) unsichtbar
gemessen; die größte Höhe wird reserviert. Die Diagrammhöhe hängt nur von der Breite ab. Dadurch bleibt
die Oberkante des Diagramms beim Modell-, Lauf- und Schalterwechsel unverändert.

**Zeitachse und Sommerzeit.** Intern zählen ausschließlich eindeutige Unixsekunden (UTC).
`sammeln_vorhersage.py` fragt Open-Meteo mit `timezone=UTC` und `timeformat=unixtime` ab; lokale
Zeitstrings (Europe/Berlin) entstehen nur zur Anzeige und dienen nie als Schlüssel. Deshalb stimmen
Zeitraster (3/6 h), Horizont (`init + Tage · 24 h`) und Niederschlagssummen auch am 25.10.2026 (25-Stunden-Tag,
doppelte Ortsstunde 02:00) und am 28.03.2027 (23-Stunden-Tag, fehlende Stunde). Liefert die Schnittstelle
ein unerwartetes Zeitformat (etwa Zeitstrings mit Offset), wird nichts gespeichert und ein Hinweis
„Zeitformat" ausgegeben — es wird nicht geraten. Tagessummen (Historie, Stationswerte) gelten als
vollständig, wenn alle Stunden des Ortstags vorliegen (23, 24 oder 25). Im Diagramm liegen die senkrechten
Tageslinien bei echter Ortsmitternacht (Europe/Berlin), Tooltips und Tabellen zeigen die Ortszeit aus der
Unixzeit.

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
Tagessummen von 0 bis 24 Uhr Ortszeit verdichtet. Nur Tage mit allen Stundenwerten des Ortstags
zählen (24; am Umstelltag 23 bzw. 25).

Bewusst **nicht** der fertige DWD-Tageswert (RSK): der läuft von 06 bis 06 UTC und ist gegen das
Tagesraster der Vorhersagen um Stunden versetzt. Am 10./11. September 2026 hätte das 5,6 mm
komplett auf den falschen Tag geschoben.

**Speicherung der Messwerte:** Das DWD-„akt"-Archiv liefert nur ein rollierendes Zeitfenster von
rund 500 Tagen. `skripte/sammeln.py` führt neu abgerufene Tage deshalb mit der vorhandenen
Monatsdatei zusammen, statt sie zu überschreiben — ältere Tage, die inzwischen außerhalb dieses
Fensters liegen, bleiben dadurch erhalten; nur Tage, die der aktuelle Abruf tatsächlich liefert,
werden aktualisiert (etwa bei nachträglichen DWD-Korrekturen).

**Vorhersagen:** [open-meteo.com](https://open-meteo.com) — Hauptläufe `ecmwf_ifs025` und
`gfs_seamless`, Ensembles `ecmwf_ifs025` (51 Mitglieder) und `gfs_seamless` (31 Mitglieder — `gfs025` allein
liefert Mitgliederdaten nur bis Tag 10). Open-Meteo interpoliert Ensemblewerte auf ein
Stundenraster. Für die Meteogramme werden daraus wieder modellnahe Zeitpunkte gewählt: GFS
3-stündlich bis +240 Stunden und danach 6-stündlich, ECMWF durchgehend 3-stündlich. Die
Diagrammachse verwendet echte Zeitstempel und bleibt maßstabstreu.
Beim **GFS** erscheinen der deterministische Hauptlauf als schwarze durchgezogene Linie und der
Kontrolllauf schwarz gestrichelt. Beim **ECMWF** wird nur der operationelle Hauptlauf schwarz
durchgezogen gezeigt; eine zweite Kontrolllinie wird bewusst nicht dargestellt. Die
Ensemblekurven sind bei den Temperaturen rötlich (GFS) bzw. gelblich (ECMWF), beim Niederschlag
dunkelblau (GFS) bzw. hellblau (ECMWF).
Die Bereiche über dem Diagramm reservieren ihre Höhe (siehe „Kein Layoutsprung"), damit die Diagramme beim
Umschalten nicht nach oben oder unten springen. Temperaturachsen tragen nur ganzzahlige Werte; die
Bezugslinie (siehe oben) ist bei GFS und ECMWF identisch.
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

## Reiter „48h Wetter"

**Datenquelle.** `skripte/sammeln_48h.py` holt je Modell **einen** Abruf der Open-Meteo-Vorhersage
(`api.open-meteo.com/v1/forecast`, Datensatz `gfs_seamless` bzw. `ecmwf_ifs025`) mit den Stundenwerten
des Hauptlaufs: Temperatur, Niederschlag, **WMO-Wettercode** und Tag/Nacht-Kennzeichen. Der Wettercode
ist die Quelle der Symbole und stammt damit immer aus demselben Modell wie die Kurve — eine zweite
Wetterquelle braucht es nicht. Ergebnis: `daten/48h/<modell>.json`, eingebettet von `bauen.py` als
`wetter48`. Geschrieben wird nur bei fachlicher Änderung.

**Ensemble-Band.** Mittel, 10. und 90. Perzentil kommen **nicht** aus einem zusätzlichen Abruf, sondern
aus dem jüngsten gespeicherten Ensemble-Lauf (`daten/vorhersage/*.json`, 3-stündlich). Die Werte werden
linear auf das Stundenraster gebracht. Fehlt für ein Modell ein Ensemble-Lauf, zeigt der Reiter den
Hauptlauf allein und weist darauf hin.

**Kurve.** Angezeigt wird der Mittelwert aus Hauptlauf und Ensemble-Mittel, anschließend mit der
Gewichtung 1-2-1 über benachbarte Stunden geglättet. Messlücken bleiben Lücken. Farben wie bei der
Wetterstation: Temperatur rötlich, Niederschlag blau.

**Kennzahlen und veraltete Daten.** „Jetzt" ist der vorhergesagte Wert der laufenden Stunde (nicht die erste
Stunde der Datei); Höchst- und Tiefstwert gelten für die 24 Stunden ab jetzt. Ein Ensemble-Lauf, der mehr als
36 Stunden vor der ersten Stunde begann, wird nicht als Band verwendet. Sind die Stundenwerte älter als
12 Stunden, erscheint ein Hinweis.

**Zwei Skalen in einem Diagramm.** Temperatur links, Niederschlag rechts — bewusst gegen die sonstige
Regel dieses Projekts, weil der Reiter den schnellen Gesamtüberblick liefern soll. Die Balken bleiben
deshalb zurückhaltend gezeichnet, nehmen höchstens 42 % der Höhe ein und stehen immer unten. Für den
genauen Mengenvergleich zwischen den Modellen ist der Reiter „Vorhersage Mühldorf" gedacht.

---

## Wetterstation Stefanskirchen

Eigene Netatmo-Station, nur Außenwerte: Temperatur, Luftfeuchte, Niederschlag. Zu sehen in den Reitern
**Station heute** (`#station-heute`) und **Station Verlauf** (`#station-verlauf`) der Hauptseite; dort
wechselt die Überschrift auf „Wetterstation Stefanskirchen". Die frühere Testadresse
`…/Modellbewertungen/station.html` leitet dorthin weiter.

**Dateien.** `skripte/station_netatmo.py` (Zugang und Abruf), `skripte/bauen_station.py` (Daten für die
Seite), Oberfläche als eigener, abgeschlossener Skriptblock am Ende von `skripte/vorlage.html`,
`.github/workflows/station.yml` (halbstündlich, Minute 2 und 32 UTC), `tests/test_station.py`.
Messwerte: `daten/station/station_JJJJ-MM.json` (Rohwerte etwa alle 5 Minuten, Monat nach UTC) und
`daten/station/stand.json`. Für die Seite erzeugt: `docs/station/heute.js` (letzte 48 Stunden),
`docs/station/verlauf_JJJJ-MM.js` (Stundenwerte je Ortsmonat), `docs/station.html` (Weiterleitung).

**Langjähriges Mittel.** In der Jahresansicht liegt über den Messwerten das amtliche Klimamittel
1991–2020 des DWD (Station Mühldorf am Inn, 3366): bei der Temperatur eine weiche Jahreskurve aus den
zwölf Monatsmitteln, beim Niederschlag eine waagrechte Marke je Monat. Die Werte stehen in
`daten/klima/normalwerte.json` und kommen über `skripte/klima_normalwerte.py` von opendata.dwd.de.
Das Skript läuft **nicht** im Workflow — die Normalwerte ändern sich erst mit der nächsten
Normalperiode. Andere Station: `python3 skripte/klima_normalwerte.py --station 4261`. Fehlt die Datei,
entfällt der Vergleich ohne Fehler. Einordnung: Die Normalwerte stammen von einer amtlichen Station in
Mühldorf, nicht vom eigenen Garten; Höhenlage und Aufstellung des Netatmo-Sensors erklären einen Teil
jeder Abweichung.

**Unabhängigkeit.** Die Stationsdaten liegen in eigenen Dateien und werden erst geladen, wenn ein
Stationsreiter geöffnet wird. Der Stationsteil der Oberfläche läuft in einer eigenen Funktionsklammer
und wird von der Navigation nur über das Ereignis `seitewechsel` angestoßen. Fehlen die Stationsdaten,
erscheint nur in den Stationsreitern ein Hinweis; Vorhersage und Analyse bleiben unberührt, und
umgekehrt. Der Regenmesser kann jünger sein als das Außenmodul: Deckt er einen Zeitraum nur teilweise
ab, nennt die Kachel „Niederschlag" das Anfangsdatum („Summe ab …").

**Secrets** (*Settings → Secrets and variables → Actions*):

| Secret | Inhalt | ändert |
|---|---|---|
| `NETATMO_CLIENT_ID` | Client ID der Netatmo-App | nur von Hand |
| `NETATMO_CLIENT_SECRET` | Client Secret | nur von Hand |
| `NETATMO_REFRESH_TOKEN` | aktueller Refresh Token | der Workflow bei jedem Lauf |
| `SECRETS_PAT` | Fine-grained Token, nur dieses Repository, *Secrets: Read and write* | nur von Hand, vor Ablauf |

**Ablauf eines Laufs (verbindliche Reihenfolge).**

1. Selbsttests der Station (`tests/test_station.py`). Schlagen sie fehl, wird Netatmo nicht angefragt.
2. Vorabprüfung von `SECRETS_PAT`. Ist er abgelaufen oder ohne Recht, endet der Lauf **vor** der
   Token-Erneuerung; der Netatmo-Token bleibt gültig (Fall B unten).
3. Token-Erneuerung bei Netatmo. Beide neuen Tokens werden sofort maskiert (`::add-mask::`).
4. Der neue Refresh Token wird **sofort** per `gh secret set` gespeichert (Wert über die
   Standardeingabe, nie als Befehlsteil). Schlägt das fehl, endet der Lauf mit Fehler, ohne
   Datenabruf, Dateien oder Commit.
5. Erst dann: Messwerte per `getmeasure` ab dem jüngsten gespeicherten Wert (Lücken werden dadurch
   automatisch nachgeholt) und schrittweise Rückfüllung der Vergangenheit bis zur Einrichtung der
   Module (höchstens vier Drei-Tages-Fenster je Reihe und Lauf). Alle Werte werden erst im Speicher
   gesammelt und zuletzt atomar geschrieben; jeder Abruffehler lässt den bisherigen Stand unverändert.
   Fällt nur der Regenmesser aus, werden die Außenwerte trotzdem gespeichert.
6. Seitenbau und Commit. Kein Rebase, kein Force-Push; ein abgelehnter Push wird im nächsten Lauf
   durch erneuten Abruf ausgeglichen.

**Sperre.** `station.yml` und `aktualisieren.yml` teilen die Concurrency-Gruppe `daten` mit
`cancel-in-progress: false`: Nie laufen zwei dieser Läufe gleichzeitig, also erneuern nie zwei Läufe
zugleich den Token, und die Pushes beider Workflows kommen sich nicht in die Quere. Nur `station.yml`
greift auf Netatmo zu. Einen **laufenden** Stationslauf nicht von Hand abbrechen.

**Datenschutz.** Gespeichert und veröffentlicht werden nur Zeitpunkt, Außentemperatur,
Außenluftfeuchte, Niederschlag und die Ortsangabe „Stefanskirchen". Nie gespeichert oder ausgegeben:
Koordinaten, Adresse, Geräte- und Modulkennungen (MAC-Adressen), Seriennummern, Raum- und Modulnamen,
Innen-, CO₂-, Lärm- und Luftdruckwerte, rohe API-Antworten, Zugangsdaten. Ein Test prüft das.

**Anzeige.** Die Seite zeigt Zeitpunkt der letzten Messung und der letzten erfolgreichen
Aktualisierung. Ist eines davon älter als 90 Minuten, erscheint „Wetterstationsdaten derzeit nicht
aktuell".

### Wiederherstellung im Fehlerfall

GitHub meldet einen fehlgeschlagenen Lauf per E-Mail. Die Fehlermeldung im Protokoll des Schritts
„Netatmo-Zugang erneuern …" sagt, welcher Fall vorliegt.

**Fall A: Netatmo-Zugang verloren** (Meldung „invalid_grant" oder „konnte nicht gespeichert werden").

1. dev.netatmo.com → *My Apps* → App „Wetterhomepage" → *Token generator* → nur `read_station`
   anhaken → *Generate Token* → bestätigen.
2. Den **Refresh Token** kopieren (nirgends sonst ablegen).
3. GitHub → Repository → *Settings → Secrets and variables → Actions* → `NETATMO_REFRESH_TOKEN` →
   Stift → neuen Wert einfügen → *Update secret*.
4. *Actions → Wetterstation Stefanskirchen → Run workflow*.
5. Kontrolle: Lauf grün, auf `station.html` zeigt „Letzte Aktualisierung" die neue Uhrzeit.

**Fall B: GitHub-Schlüssel abgelaufen** (Meldung „Vorabprüfung fehlgeschlagen"). Der Netatmo-Token ist
dabei **nicht** verloren.

1. GitHub → Profilbild → *Settings → Developer settings → Personal access tokens → Fine-grained
   tokens → Generate new token*: nur Repository `Modellbewertungen`, *Secrets: Read and write*,
   Ablaufdatum so spät wie erlaubt. Alten Schlüssel löschen.
2. Secret `SECRETS_PAT` mit dem neuen Schlüssel ersetzen.
3. Workflow manuell starten und kontrollieren wie in Fall A, Schritte 4 und 5.

Der aktuelle Schlüssel läuft am **20.06.2027** ab; Anfang Juni 2027 erneuern.

**Noch zu prüfen beim ersten echten Lauf.** Die Messgröße `rain` für den Regenmesser bei
`scale=max` und die Abrufgrenzen von Netatmo sind nicht offiziell bestätigt. Schlägt nur der
Regenabruf fehl, erscheint eine Warnung, und die Außenwerte laufen weiter.

---

## Handy-Fassung „WoazeWeather"

Eine Fassung nur fürs Handy, die sich wie eine App auf den Startbildschirm legen lässt. Die
normale Seite bleibt davon unberührt: `docs/app.html` und `docs/index.html` enthalten kein einziges
Byte der Handy-Fassung (ein Test prüft das).

**Aufrufen und anheften.** `…/Modellbewertungen/handy.html` im Handy-Browser (Chrome) öffnen und im
Menü „App installieren" oder „Zum Startbildschirm hinzufügen" wählen. Ohne Hash startet sie mit
„Station heute". Das Symbol ist eine Sonne mit „WW" (WoazeWeather).

**So entsteht sie.** `skripte/bauen.py` nimmt die fertige normale Seite und setzt an fünf Stellen
Handy-Teile ein (Kopfzeile mit Manifest, Stylesheet `skripte/handy.css`, Skript `skripte/handy.js`,
und eine Verbindung in `diagramm()` der Wetterstation). Passt eine dieser Stellen nicht genau einmal,
bricht der Bau mit einer Meldung ab. Ohne die eingesetzten Teile ist `handy-app.html` Wort für Wort
`app.html` (Test `test_handy_fassung_ist_sonst_die_normale_seite`). Änderungen am Handy-Aussehen gehören
in `handy.css`/`handy.js`, nicht in `vorlage.html`.

**Was anders ist.** Untere Leiste statt Reiter oben (Heute, Verlauf, 48 Std., Vorhersage, Analyse);
Untertitel, Erklärungen, Fußtexte, Koordinaten und „Letzte Aktualisierung" sind ausgeblendet;
Kennzahlen in drei Spalten; Diagramme randlos, die der Wetterstation etwas höher und mit größerer Schrift.

**Zoom mit zwei Fingern.**
- *Station heute und Verlauf:* Die Zeitachse wird gezoomt. Beide Diagramme des Reiters laufen im
  Gleichschritt, die Beschriftung passt sich an, die Höhenachse richtet sich nach dem sichtbaren
  Ausschnitt. Ein Finger schiebt den Ausschnitt. Doppeltippen oder der Knopf „Ganzer Zeitraum" setzt
  zurück; ein anderer Zeitraum (Gestern, Monat, blättern) auch. Dafür ruft `diagramm()` vor dem Zeichnen
  `window.WW_ZOOM.anwenden(ziel, o)` auf, und `window.WW_NEU()` lässt neu zeichnen.
- *48 Std., Vorhersage, Analyse:* Das Diagramm wird beim Pinch bis zu viermal breiter und lässt sich im
  Rahmen seitlich wischen. Doppeltippen setzt zurück.
- Ein kleiner Hinweis unter den Diagrammen verschwindet, sobald einmal gezoomt wurde.

**Analyse auf dem Handy.** Die Diagramme der Analyse-Seite werden auf die Bildschirmbreite gezeichnet;
Namen am Linienende entfallen dort (sie stehen in der Legende), im Rückblick steht nur jedes zweite Datum.

**Dienst.** `docs/handy-sw.js` leitet jede Anfrage direkt ins Netz und speichert nichts zwischen —
die App zeigt also immer den aktuellen Stand. Er ist nur da, weil Chrome eine Seite erst dann als App
anbietet, wenn ein Dienst angemeldet ist. Er ist nur für `handy.html` und `handy-app.html` zuständig.

**Symbol ändern.** `python3 skripte/handy_symbol.py` (braucht `pip install pillow`) schreibt die drei
Bilder in `docs/handy/` neu. Die Manifest-Datei bleibt, wie sie ist, solange die Dateinamen gleich bleiben.

---

## Rechtliches

Wer eine Seite rein privat und ohne kommerziellen Zweck betreibt, braucht in Deutschland
üblicherweise kein Impressum — die Pflicht nach § 5 DDG gilt für geschäftsmäßige Angebote. Die
Abgrenzung ist im Einzelfall aber nicht immer eindeutig, und das hier ist keine Rechtsberatung. Im
Zweifel ist ein kurzes Impressum die einfachere Lösung. Die Nutzung von open-meteo ist für
nichtkommerzielle Zwecke frei.
