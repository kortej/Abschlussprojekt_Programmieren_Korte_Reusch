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
... (493 Zeilen verbleibend)