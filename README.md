# Abschlussprojekt_Programmieren_Korte_Reusch
# E-Bike-Auslegung aus realen GPS-Daten

Abschlussprojekt **Programmieren 1 (MCI-MECH-B-2-PRO1-PRO1-ILV)**, SS 2026
Julius **Korte** und Tom **Reusch**

Das Programm liest eine GPS-Aufzeichnung (Breite, Länge, Höhe, Zeit,
Temperatur) ein, berechnet daraus die Fahrwiderstände eines E-Bikes und
simuliert damit zwei verschiedene Akkutypen. Beantwortet wird die Frage:
**Wie groß muss der Akku sein, damit diese Fahrt vollständig möglich ist?**

---

## Inhaltsverzeichnis

- [Installation](#installation)
- [Ausführung](#ausführung)
- [Erzeugte Dateien](#erzeugte-dateien)
- [Projektstruktur](#projektstruktur)
- [Physikalisches Modell](#physikalisches-modell)
- [Akkumodell](#akkumodell)
- [Umgesetzte Erweiterungen](#umgesetzte-erweiterungen)
- [Ergebnisse](#ergebnisse)
- [Tests](#tests)
- [Diagramme und Dokumentation](#diagramme-und-dokumentation)
- [Annahmen und Einschränkungen](#annahmen-und-einschränkungen)
- [Commit-Konvention](#commit-konvention)
- [Quellen](#quellen)

---

## Installation

Benötigt wird **Python 3.10 oder neuer** (wegen der Schreibweise `str | Path`
bei den Typannotationen). Geprüft mit Python 3.11 und 3.12 unter Windows 11
und Ubuntu 24.04.

```bash
# 1) Repository klonen
git clone https://github.com/kortej/Abschlussprojekt_Programmieren_Korte_Reusch
cd Abschlussprojekt_Programmieren_Korte_Reusch

# 2) virtuelle Umgebung anlegen
python -m venv .venv

# 3a) aktivieren unter Windows (PowerShell)
.venv\Scripts\Activate.ps1
# 3b) aktivieren unter Windows (cmd.exe)
.venv\Scripts\activate.bat
# 3c) aktivieren unter Linux / macOS
source .venv/bin/activate

# 4) Pakete installieren
pip install -r requirements.txt
```

Schlägt unter Windows PowerShell die Aktivierung mit
`... kann nicht geladen werden, da die Ausführung von Skripts ... deaktiviert ist`
fehl, hilft einmalig:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Was wird installiert?

| Paket | Wofür |
| --- | --- |
| `pandas`, `numpy` | Einlesen der CSV und alle Berechnungen auf den Messreihen |
| `matplotlib` | Diagramme (PNG) |
| `folium` | interaktive Streckenkarte (HTML) |
| `requests` | Abfrage der Wetter- und Geocoding-API |
| `pytest`, `pytest-cov` | Unit-Tests und Testabdeckung |
| `openmeteo-requests`, `requests-cache`, `retry-requests` | **optional**: offizielles Open-Meteo-SDK |

Die drei optionalen Pakete am Ende der `requirements.txt` sind *nicht*
zwingend nötig. Sind sie installiert, läuft die Wetterabfrage über das
offizielle SDK (FlatBuffers, HTTP-Cache, automatische Wiederholungsversuche);
fehlen sie, schaltet `weather.py` selbstständig auf den direkten Weg über
`requests` um. Das Projekt ist in beiden Fällen vollständig lauffähig.

### Optional: LaTeX für den PDF-Bericht

Für den Fahrtbericht als PDF wird `pdflatex` benötigt:

* **Windows:** [MiKTeX](https://miktex.org/download) (bei der Installation
  „Fehlende Pakete automatisch installieren: Ja“ wählen)
* **Linux:** `sudo apt install texlive-latex-recommended texlive-lang-german`
* **macOS:** [MacTeX](https://www.tug.org/mactex/)

Ist kein LaTeX installiert, bricht das Programm **nicht** ab: Es schreibt die
Datei `output/fahrtbericht.tex` und gibt einen entsprechenden Hinweis aus.
Wer den Bericht gar nicht braucht, startet mit `--no-report`.

---

## Ausführung

Der Standardaufruf aus dem Projektordner:

```bash
python main.py
```

Damit werden nacheinander ausgeführt: Daten einlesen und aufbereiten →
Wetterdaten abrufen → Reverse Geocoding → Simulation beider Akkutypen →
Auslegung der nötigen Kapazität → Diagramme → Karte → LaTeX-Bericht →
Export nach `output/ergebnisse.json` und Eintrag in dieses README.

### Alle Kommandozeilenoptionen

| Option | Standard | Bedeutung |
| --- | --- | --- |
| `--daten PFAD` | `data/final_project_input_data.csv` | Pfad zur CSV mit den GPS-Daten |
| `--ausgabe ORDNER` | `output/` | Zielordner für Plots, Bericht, Logdatei |
| `--akku {lipo,nmc,beide}` | `beide` | zu simulierender Akkutyp |
| `--zellen-parallel N` | `20` | parallel geschaltete Zellen (Kapazität = N · 3,5 Ah) |
| `--no-wetter` | aus | keine Wetterdaten abrufen, ohne Wind rechnen |
| `--no-geocoding` | aus | kein Reverse Geocoding (keine Ortsnamen) |
| `--no-thermik` | aus | thermisches Akkumodell deaktivieren |
| `--studie` | aus | automatische Parameterstudien durchführen |
| `--auslegung` | aus | kleinste ausreichende Akkukonfiguration suchen |
| `--no-report` | aus | keinen LaTeX-Bericht erzeugen |
| `--no-readme` | aus | Ergebnisblock in diesem README nicht aktualisieren |
| `--ausfuehrlich` | aus | Logging auf DEBUG-Stufe |
| `-h`, `--help` | – | Hilfetext anzeigen |

`--report` existiert weiterhin, hat aber keine Wirkung mehr: Der Bericht wird
seit der Umstellung auf `--no-report` standardmäßig erzeugt. Die Option bleibt
nur erhalten, damit ältere Aufrufe nicht fehlschlagen.

### Verhalten ohne Internet

Beide APIs sind so eingebunden, dass ein Ausfall den Lauf nicht abbricht:
Es wird eine Warnung ins Log geschrieben und ohne Wind bzw. ohne Ortsnamen
weitergerechnet. Antworten werden in `output/wetter_cache.json` und
`output/geocoding_cache.json` zwischengespeichert, sodass beim nächsten Start
keine erneute Anfrage nötig ist.

---

## Erzeugte Dateien

Alle Ergebnisse landen im Ordner `output/` (der Ordner selbst ist über
`.gitignore` von der Versionierung ausgenommen):

| Datei | Inhalt |
| --- | --- |
| `01_uebersicht.png` | Geschwindigkeit, Leistung, SoC und Strom über der Zeit |
| `02_hoehenprofil.png` | Höhenprofil mit Steigung über der Strecke |
| `03_kraefte.png` | Aufteilung der vier Fahrwiderstände |
| `04_akkutemperatur.png` | Verlauf der Akkutemperatur und des Innenwiderstands |
| `05_kennlinien.png` | OCV-SoC-Kennlinien von LiPo und NMC |
| `06_himmelsrichtungen.png` | Verteilung der Fahrtrichtungen (Windrose) |
| `07_orte.png` | Höhenprofil mit den per Geocoding bestimmten Ortsnamen |
| `08_akkuvergleich.png` | SoC-Verlauf beider Akkutypen im Vergleich |
| `09_parameterstudie.png` | Ergebnisse der Parameterstudien (nur mit `--studie`) |
| `parameterstudie.csv` | dieselben Studienergebnisse als Tabelle |
| `strecke.html` | interaktive Karte, im Browser zu öffnen |
| `fahrtbericht.tex` / `.pdf` | Bericht mit allen Kennzahlen, Tabellen und Plots |
| `ergebnisse.json` | alle Kennzahlen des Laufs maschinenlesbar |
| `simulation.log` | vollständiges Protokoll des Laufs |
| `wetter_cache.json`, `geocoding_cache.json` | zwischengespeicherte API-Antworten |

`07_orte.png` entsteht nur, wenn das Reverse Geocoding aktiv war,
`09_parameterstudie.png` und `parameterstudie.csv` nur mit `--studie`.

---

## Projektstruktur

```
Abschlussprojekt_Programmieren_Korte_Reusch/
├── main.py                     Hauptprogramm, Ablaufsteuerung, CLI
├── requirements.txt            benötigte Pakete
├── pytest.ini                  Testkonfiguration (pythonpath = src)
├── data/
│   └── final_project_input_data.csv    GPS-Rohdaten (2284 Punkte)
├── docs/
│   ├── uml_klassendiagramm.pdf         UML-Klassendiagramm der Softwarestruktur
│   └── aktivitaetsdiagramm.pdf         Aktivitätsdiagramm des Simulationsablaufs
├── output/                     alle erzeugten Dateien (nicht versioniert)
├── src/ebike/
│   ├── config.py               alle Parameter zentral als dataclasses
│   ├── geo.py                  Haversine, Bearing, Himmelsrichtung
│   ├── data_loader.py          CSV einlesen, Kinematik berechnen (Track)
│   ├── environment.py          Luftdichte (Atmosphaere) und Wind
│   ├── bike.py                 Fahrwiderstände, Leistung, Moment, Strom (EBike)
│   ├── battery.py              Akkumodell, Kennlinien, Thermik, Bremswiderstand
│   ├── simulation.py           Simulationsschleife und Kapazitätsauslegung
│   ├── weather.py              Open-Meteo-API (Wind, Temperatur, Luftfeuchte)
│   ├── geocoding.py            Nominatim-API (Reverse Geocoding)
│   ├── mapping.py              Streckenkarte mit folium
│   ├── plotting.py             alle Diagramme
│   ├── parameter_study.py      automatische Parameterstudien
│   ├── report.py               LaTeX-Bericht
│   └── results_export.py       JSON-Export und README-Aktualisierung
└── tests/
    ├── test_geo.py             Haversine, Bearing, Himmelsrichtung
    ├── test_battery.py         Referenzfall der OOP-Übung, Kennlinien, Thermik
    ├── test_physics.py         Atmosphäre, Wind, Fahrwiderstände
    ├── test_simulation.py      Datenaufbereitung und vollständiger Lauf
    ├── test_erweiterungen.py   Wetter, Geocoding, Karte, Parameterstudie
    └── test_korrekturen.py     Regressionstests für behobene Fehler
```

Die Aufteilung folgt dem Ablauf der Simulation: Jedes Modul ist für genau
einen Schritt zuständig und kennt nur die Module, die es wirklich braucht.
`config.py` wird von fast allen verwendet, kennt selbst aber keines.

---

## Physikalisches Modell

Umgesetzt ist das Freikörperdiagramm aus der Angabe. Für jeden Zeitschritt
werden die vier Fahrwiderstände berechnet (`bike.py`):

| Kraft | Formel | Bemerkung |
| --- | --- | --- |
| Beschleunigung | `F_a = m · a` | m = 80 kg (70 kg Fahrer + 10 kg Rad) |
| Steigung | `F_st = m · g · sin(φ)` | φ aus der geglätteten Höhenänderung |
| Rollwiderstand | `F_r = c_rr · m · g · cos(φ)` | c_rr = 0,006; im Stillstand 0 |
| Luftwiderstand | `F_L = ½ · ρ · c_w·A · v_rel · \|v_rel\|` | c_w·A = 0,5625 m² |

Die Betragsschreibweise beim Luftwiderstand ist nötig, weil bei Rückenwind
die Relativgeschwindigkeit negativ wird — dann *schiebt* der Wind und die
Kraft muss ihr Vorzeichen wechseln.

Daraus folgen:

```
F_ges  = F_a + F_st + F_r + F_L
P_mech = F_ges · v                     mechanische Leistung am Rad
T      = F_ges · r_Rad                 Drehmoment (r = 27" / 2 = 0,343 m)
I_Motor = T / K_m                      Motorstrom, K_m = 1,5 Nm/A
```

**Wichtiger Punkt zur Energiebilanz:** `I_Motor = T/K_m` beschreibt den Strom
im Motor und dient der Auslegung von Motor und Leistungselektronik. Er ist
*nicht* der Batteriestrom — sonst wäre die Energiebilanz nur bei genau einer
Geschwindigkeit konsistent. Der Batteriestrom wird stattdessen aus der
elektrischen Leistung berechnet:

```
P_bat = P_mech / η_Antrieb             beim Antreiben (η = 0,85)
P_bat = P_mech · η_Reku                beim Bremsen   (η = 0,50, negativ)
P_bat = (U_OC − R_i · I) · I     →     I  (quadratische Gleichung nach I)
```

Die **Luftdichte** ist keine Konstante, sondern wird in `environment.py` für
jeden Punkt aus der gemessenen Temperatur und der Seehöhe bestimmt
(barometrische Höhenformel, danach ideales Gasgesetz `ρ = p / (R_L · T)`).
Über die Strecke ändert sie sich um mehrere Prozent.

Die **Rohdaten sind verrauscht**, deshalb werden sie in `data_loader.py`
aufbereitet: gleitende Glättung über 9 Punkte, Geschwindigkeiten über
25 m/s, Beschleunigungen über 3 m/s² und Steigungen über ±30 % werden als
GPS-Ausreißer begrenzt (mit Warnung im Log). Die Steigung wird nicht zwischen
zwei Einzelpunkten, sondern über ein Streckenfenster von 30 m bestimmt, weil
das GPS-Höhensignal sonst unbrauchbar rauscht.

---

## Akkumodell

Grundlage ist das Modell aus der Übung *2. Einführung in die OOP*
(`battery.py`, Klasse `BatteryPack`): Der Akku ist eine ideale
Spannungsquelle mit Innenwiderstand.

```
SoC_(k+1) = SoC_k − I · Δt / C_nenn
SoC       = max(0, min(1, SoC))        harte Begrenzung, s. Fehlerbehandlung
U_OC      = U_min + SoC · (U_max − U_min)
U         = U_OC − R_i · I
```

Der Pack ist wie in der Angabe als **10S × P** aufgebaut:

```
C_Pack  = C_Zelle · P                 (3,5 Ah pro Zelle)
R_Pack  = R_Zelle · 10 / P
U_Pack  = 32 V (leer) … 42 V (voll)
```

Darauf setzen die Erweiterungen auf:

* **Zwei Akkutypen mit echten Kennlinien.** `LiPoAkku` (8 mΩ/Zelle) und
  `NmcAkku` (7 mΩ/Zelle) erben von `KennlinienAkku` und ersetzen die lineare
  OCV-Kurve durch die 14 Stützstellen aus der Angabe; dazwischen wird linear
  interpoliert (`numpy.interp`). Der LiPo hält seine Spannung im oberen
  SoC-Bereich deutlich besser, der NMC fällt gleichmäßiger ab.
* **Thermisches Modell.** Die Verlustleistung `I²·R_i` erwärmt den Pack,
  die Umgebungsluft kühlt ihn (`ThermischesModell`). Der Innenwiderstand
  steigt bei Kälte um 1,5 %/K gegenüber 25 °C — kalte Akkus liefern weniger
  Leistung.
* **Bremswiderstand.** Beim Rekuperieren wird der Ladestrom auf 15 A
  begrenzt. Was darüber hinausgeht oder bei SoC = 100 % nicht mehr
  hineinpasst, nimmt die Klasse `Bremswiderstand` auf und zählt die dort
  verheizte Energie mit.

**Warum unterscheiden sich die beiden Akkus nur wenig?** Bei gleicher
Leistungsanforderung ist die *entnommene Energie* praktisch identisch — es
wird ja dieselbe Fahrt gefahren. Unterschiedlich ist der *End-SoC*, weil sich
bei verschiedenen OCV-Kennlinien und Innenwiderständen bei gleicher Leistung
unterschiedliche Ströme und damit unterschiedliche Ladungsmengen (Ah)
ergeben. Nachvollziehbar ist das in der Zeile „Max. Ladungsbedarf [Ah]“ der
Ergebnistabellen weiter unten.

### Fehlerbehandlung und Logging

* Der SoC wird in jedem Schritt hart auf 0 … 100 % begrenzt; ein Unterschreiten
  beendet die Simulation kontrolliert mit einem Log-Eintrag statt mit einem
  Absturz.
* Fehlende Spalten, leere Dateien oder unlesbare Zeitstempel in der CSV
  führen zu einem `ValueError` mit verständlicher Meldung, den `main.py`
  abfängt (Rückgabewert 1).
* Unbekannte Akkutypen, Masse ≤ 0 und Motorkonstante ≤ 0 lösen ebenfalls
  `ValueError` aus.
* Division durch Null (Zeitschritt 0, Strecke 0) wird an allen Stellen
  abgefangen.
* API-Ausfälle werden als Warnung geloggt, der Lauf geht weiter.
* Jeder Lauf schreibt ein vollständiges Protokoll nach `output/simulation.log`.

---

## Umgesetzte Erweiterungen

Alle zehn zur Auswahl gestellten Erweiterungen sind umgesetzt:

| # | Erweiterung | Modul |
| --- | --- | --- |
| 1 | Strecke auf einer Karte plotten (`folium`) | `mapping.py` |
| 2 | Unit-Tests für sinnvolle Teile der Software | `tests/` |
| 3 | Automatische Parameterstudien | `parameter_study.py` |
| 4 | Luftdichte aus Temperatur und Seehöhe | `environment.py` |
| 5 | Simulation des Rollwiderstands | `bike.py` |
| 6 | Akkutemperatur und ihr Einfluss auf die Leistung | `battery.py` |
| 7 | Bremswiderstand für nicht speicherbare Energie | `battery.py` |
| 8 | Reverse Geocoding über eine API | `geocoding.py` |
| 9 | Wetterdaten und Windberücksichtigung | `weather.py`, `environment.py` |
| 10 | Himmelsrichtung aus den GPS-Daten | `geo.py`, `plotting.py` |
| 11 | Report über die Fahrt als LaTeX-Dokument | `report.py` |

**Zu den Parameterstudien:** Variiert werden Gesamtmasse (60–110 kg),
Luftwiderstandsbeiwert c_w·A (0,3–0,8 m²), Raddurchmesser (24–29 Zoll),
Rollwiderstandsbeiwert (0,002–0,012) und Akkukapazität. Für jeden Wert läuft
eine vollständige Simulation; ausgewertet werden Energieverbrauch, End-SoC
und der nötige Ladungsbedarf. Ergebnis in Kurzform: Der Luftwiderstand
dominiert bei dieser Fahrt, der Raddurchmesser ist bei konsistenter
Strommodellierung nahezu ohne Einfluss auf die Energie.

---

## Ergebnisse

<!-- ERGEBNISSE:START -->

_Dieser Abschnitt wird von `main.py` automatisch aus `output/ergebnisse.json` erzeugt. Bitte nicht von Hand ändern._

Letzter Lauf: noch nicht ausgeführt — bitte einmal `python main.py` starten.

**Kenngroessen der Fahrt** (Referenzlauf, `--no-wetter --no-geocoding`)

| Groesse | Wert |
| --- | --- |
| Anzahl Messpunkte | 2284 |
| Gesamtdistanz [km] | 94.27 |
| Fahrtdauer [h] | 4.55 |
| Durchschnittsgeschw. [km/h] | 20.73 |
| Maximalgeschw. [km/h] | 54.35 |
| Aufstieg [m] | 1033.5 |
| Abstieg [m] | 1034.6 |
| Min. Seehoehe [m] | 482.2 |
| Max. Seehoehe [m] | 855.5 |
| Mittlere Temperatur [C] | 27.6 |
| Haupt-Himmelsrichtung | WSW |

**Simulation mit LiPo-Akku (70 Ah)**

| Groesse | Wert |
| --- | --- |
| Fahrt vollstaendig | True |
| End-SoC [%] | 72.1 |
| Energieverbrauch [Wh] | 836.5 |
| Verbrauch [Wh/km] | 8.9 |
| Max. Ladungsbedarf [Ah] | 19.55 |

**Simulation mit NMC-Akku (70 Ah)**

| Groesse | Wert |
| --- | --- |
| Fahrt vollstaendig | True |
| End-SoC [%] | 71.6 |
| Energieverbrauch [Wh] | 836.5 |
| Verbrauch [Wh/km] | 8.9 |
| Rekuperierte Energie [Wh] | 24.8 |
| Mittlere Leistung [W] | 158.2 |
| Maximale Leistung [W] | 2093.8 |
| Maximaler Motorstrom [A] | 58.2 |
| Max. Akkutemperatur [C] | 28.8 |
| Bremswiderstand [Wh] | 2.7 |
| Max. Ladungsbedarf [Ah] | 19.86 |

**Notwendige Akkukapazitaet**

| Groesse | Wert |
| --- | --- |
| netto_ladung_ah | 19.34 |
| empfohlene_kapazitaet_ah | 22.75 |
| energie_wh | 836.5 |
| vollstaendig | True |

<!-- ERGEBNISSE:ENDE -->

**Interpretation.** Die aufgezeichnete Fahrt über 94,3 km mit 1034 Höhenmetern
benötigt rund **837 Wh** bzw. **19,3 Ah** netto. Mit 15 % Reserve ergibt das
eine empfohlene Kapazität von etwa **23 Ah**, also einen 7P-Pack
(7 · 3,5 Ah = 24,5 Ah, ca. 900 Wh). Ein handelsüblicher E-Bike-Akku mit
500–600 Wh reicht für diese Strecke also **nicht** aus — nachprüfbar mit
`python main.py --zellen-parallel 4`.

Der Standardwert von 20 parallelen Zellen (70 Ah) ist bewusst großzügig
gewählt, damit die Fahrt in jedem Fall vollständig simuliert werden kann.
Die tatsächlich nötige Größe ist ein *Ergebnis* der Simulation, nicht eine
Vorgabe; mit `--auslegung` sucht das Programm die kleinste ausreichende
Konfiguration automatisch.

---

## Tests

```bash
pytest                      # alle Tests
pytest -v                   # mit Namen jedes einzelnen Tests
pytest --cov=ebike          # mit Testabdeckung
pytest tests/test_battery.py    # nur eine Datei
```

Aktuell laufen **179 Tests** in etwa 6 Sekunden durch. Sie decken ab:

* **`test_geo.py`** — Haversine gegen bekannte Referenzstrecken, Bearing in
  alle vier Himmelsrichtungen, Grenzfälle am Nullmeridian.
* **`test_battery.py`** — der Referenzfall aus der OOP-Übung (damit das
  Grundmodell nachweislich der Angabe entspricht), Kennlinieninterpolation,
  SoC-Begrenzung bei 0 % und 100 %, Temperaturabhängigkeit des
  Innenwiderstands, Bremswiderstand.
* **`test_physics.py`** — Luftdichte gegen Tabellenwerte der Standard-
  atmosphäre, Windkomponenten bei Gegen-, Rücken- und Seitenwind, jede
  Fahrwiderstandskraft einzeln.
* **`test_simulation.py`** — Einlesen fehlerhafter CSV-Dateien, Kinematik-
  berechnung, ein vollständiger Simulationslauf auf synthetischen Daten,
  Kapazitätsabschätzung.
* **`test_erweiterungen.py`** — Wetter- und Geocoding-Service mit
  simulierten API-Antworten (inklusive Ausfall und Cache), Kartenerzeugung,
  Parameterstudie, LaTeX-Escaping.
* **`test_korrekturen.py`** — Regressionstests für bereits behobene Fehler,
  damit sie nicht erneut auftreten.

Die API-Tests verwenden `monkeypatch` und benötigen **keine**
Internetverbindung.

---

## Diagramme und Dokumentation

* **`docs/uml_klassendiagramm.pdf`** — UML-Klassendiagramm der
  Softwarestruktur mit allen Klassen, ihren wichtigsten Attributen und
  Methoden sowie den Beziehungen zwischen den Modulen.
* **`docs/aktivitaetsdiagramm.pdf`** — Aktivitätsdiagramm des gesamten
  Programmablaufs, wie ihn `main.py` steuert. Dargestellt sind:

  1. Start, Einlesen der Kommandozeilenoptionen, Einrichten des Loggings
  2. Laden der CSV mit Verzweigung bei fehlerhaften Daten (kontrollierter
     Abbruch mit Rückgabewert 1) und anschließender Kinematikberechnung
  3. die beiden optionalen API-Blöcke (Wetter, Reverse Geocoding), jeweils
     mit der Entscheidung „API erreichbar?" und dem Weiterrechnen ohne Wind
     bzw. ohne Ortsnamen im Fehlerfall
  4. die Schleife über die Akkutypen und darin die eigentliche
     **Simulationsschleife über alle GPS-Punkte** mit den Verzweigungen für
     Antreiben/Rekuperieren, die Ladestrombegrenzung mit Bremswiderstand und
     die SoC-Grenzen (Abbruch bei SoC ≤ 0 %)
  5. Auslegung der notwendigen Kapazität, Diagramme, Karte, optionale
     Parameterstudien, LaTeX-Bericht sowie der Export nach
     `ergebnisse.json` und in dieses README

  Die Verzweigungen im Diagramm entsprechen direkt den `if`-Zweigen in
  `main.py` und `simulation.FahrtSimulator.simuliere()`.
* **`output/fahrtbericht.pdf`** — automatisch erzeugter Bericht über die
  konkrete Fahrt mit allen Kennzahlen, Tabellen und Diagrammen.

Zusätzlich ist jedes Modul, jede Klasse und jede öffentliche Methode im
Quelltext mit einem Docstring versehen (Google-Stil), alle Funktionen haben
Typannotationen.

---

## Annahmen und Einschränkungen

* **Kein Pedalieren.** Der Motor leistet die gesamte Antriebsarbeit. In der
  Realität trägt der Fahrer 50–150 W bei, der reale Verbrauch läge also
  deutlich niedriger.
* **Zellkapazität 3,5 Ah** pro Zelle — in der Angabe nicht festgelegt,
  typischer Wert einer 18650-Zelle. Einstellbar in `config.py`.
* **Wirkungsgrade** von 85 % (Antriebsstrang) und 50 % (Rekuperation) sind
  plausible Annahmen, keine Messwerte.
* **Thermische Parameter** des Akkus (Wärmekapazität 45 kJ/K, Wärmeübergang
  3 W/K) sind abgeschätzt.
* **Rekuperation** wird bei jedem negativen Leistungsbedarf angenommen. Ein
  reales E-Bike ohne Rekuperationsfunktion würde stattdessen mechanisch
  bremsen — abschaltbar über `rekuperation_aktiv` in `config.py`.
* **GPS-Rauschen.** Höhen- und Geschwindigkeitsdaten sind verrauscht; die
  Glättung und die Plausibilitätsgrenzen dämpfen das, entfernen es aber
  nicht vollständig. Die Grenzen sind in `config.py` dokumentiert und
  einstellbar.
* **Wetterdaten** stammen aus dem Reanalyse-Archiv von Open-Meteo (Auflösung
  1 Stunde, ca. 11 km Raster) und werden für den Mittelpunkt der Strecke
  abgefragt — lokale Böen und Talwinde sind darin nicht enthalten.
* **Ein einzelner Fahrzyklus.** Alterung, Selbstentladung und Ladeverluste
  sind nicht modelliert.

---

## Commit-Konvention

Verwendet werden [Conventional Commits](https://www.conventionalcommits.org/de/v1.0.0/):

```
feat(battery): Kennlinienmodell fuer LiPo und NMC ergaenzt
fix(data): Division durch null bei Zeitschritt 0 abgefangen
test(geo): Tests fuer Haversine und Bearing
docs(readme): Installationsanleitung ergaenzt
refactor(sim): Simulationsschleife in eigene Methode ausgelagert
```

---

## Quellen

**Aufgabenstellung und Vorlesungsunterlagen**

* *Abschlussprojekt — Auslegung eines E-Bikes*, MCI/LFU, PRO1, SS 2026
  (Aufgabenstellung, Fahrzeugdaten und Akku-Kennlinien)
* *MCI-MECH-B-2-PRO1-PRO1-ILV — 2. Einführung in die OOP, Übungen*
  (Grundmodell des Akkus)
* *Vorlesungsunterlagen Programmieren 1*

**Physikalische Grundlagen**

* Haversine-Formel: R. W. Sinnott, „Virtues of the Haversine“, *Sky and
  Telescope* 68 (2), 1984, S. 159 — Zusammenfassung:
  <https://en.wikipedia.org/wiki/Haversine_formula>
* Berechnung des Bearings zwischen zwei Koordinaten:
  <https://www.movable-type.co.uk/scripts/latlong.html>
* Barometrische Höhenformel / Standardatmosphäre (ISO 2533):
  <https://en.wikipedia.org/wiki/Barometric_formula>
* Rollwiderstand und typische Beiwerte für Fahrradreifen:
  <https://en.wikipedia.org/wiki/Rolling_resistance> sowie Messwerte unter
  <https://www.bicyclerollingresistance.com/>
* Luftwiderstand und c_w·A-Werte von Radfahrern:
  <https://en.wikipedia.org/wiki/Drag_(physics)>

**Verwendete APIs**

* Open-Meteo, Historical Weather API (Wind, Temperatur, Luftfeuchte),
  Daten unter CC BY 4.0:
  <https://open-meteo.com/en/docs/historical-weather-api>
* Open-Meteo Python-SDK:
  <https://github.com/open-meteo/python-requests>
* Nominatim (Reverse Geocoding), Nutzungsbedingungen beachtet
  (max. 1 Anfrage/s, eigener User-Agent, lokaler Cache):
  <https://nominatim.org/release-docs/latest/api/Reverse/>
  · Nutzungsrichtlinie: <https://operations.osmfoundation.org/policies/nominatim/>
* Kartenmaterial: © OpenStreetMap-Mitwirkende, ODbL:
  <https://www.openstreetmap.org/copyright>

**Verwendete Bibliotheken (Dokumentation)**

* pandas: <https://pandas.pydata.org/docs/>
* NumPy: <https://numpy.org/doc/stable/>
* matplotlib: <https://matplotlib.org/stable/index.html>
* folium: <https://python-visualization.github.io/folium/latest/>
* requests: <https://requests.readthedocs.io/en/latest/>
* pytest: <https://docs.pytest.org/en/stable/>
* pytest-cov: <https://pytest-cov.readthedocs.io/en/latest/>

**Werkzeuge und Konventionen**

* Conventional Commits: <https://www.conventionalcommits.org/de/v1.0.0/>
* Google Python Style Guide (Docstrings):
  <https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings>
* PEP 8 — Style Guide for Python Code:
  <https://peps.python.org/pep-0008/>
* LaTeX-Distributionen: MiKTeX <https://miktex.org/> ·
  TeX Live <https://www.tug.org/texlive/>