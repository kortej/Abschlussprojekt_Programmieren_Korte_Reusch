"""Erzeugen eines LaTeX-Reports ueber die Fahrt.

Erweiterung "Generieren eines Reports ueber die Fahrt mit den wichtigsten
Kenngroessen, Plots, etc. als LaTeX-Dokument".

Die Klasse `LatexReport` baut den Quelltext einer .tex-Datei zusammen und
versucht anschliessend, sie mit `pdflatex` zu uebersetzen. Ist keine
LaTeX-Installation vorhanden, bleibt die .tex-Datei erhalten und es wird
lediglich ein Hinweis ausgegeben.
"""

import logging
import os
import shutil
import subprocess
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

KOPF = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=2.5cm]{geometry}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{tabularx}
\usepackage{pdflscape}
\usepackage{float}
\usepackage[hidelinks]{hyperref}

% Deutsche Bezeichnungen ohne das Paket babel, damit der Bericht auf jeder
% LaTeX-Installation uebersetzt werden kann
\renewcommand{\contentsname}{Inhaltsverzeichnis}
\renewcommand{\figurename}{Abbildung}
\renewcommand{\tablename}{Tabelle}

\title{Simulationsbericht E-Bike-Auslegung}
\author{Abschlussprojekt Programmieren 1 -- MCI}
\date{DATUM}

\begin{document}
\maketitle
\tableofcontents
\newpage
"""

FUSS = r"""
\end{document}
"""


def latex_escape(text) -> str:
    """Ersetzt Zeichen, die LaTeX als Steuerzeichen interpretiert."""
    ersetzungen = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    text = str(text)
    for zeichen, ersatz in ersetzungen.items():
        text = text.replace(zeichen, ersatz)
    return text


class LatexReport:
    """Baut den Bericht Abschnitt fuer Abschnitt zusammen."""

    def __init__(self, ausgabeordner: str = "output",
                 dateiname: str = "fahrtbericht.tex"):
        self.ordner = ausgabeordner
        self.dateiname = dateiname
        os.makedirs(self.ordner, exist_ok=True)
        self.abschnitte: list[str] = []

    # -- Bausteine ---------------------------------------------------------
    def abschnitt(self, titel: str, text: str = "") -> "LatexReport":
        """Fuegt eine neue Ueberschrift mit optionalem Text ein."""
        self.abschnitte.append(f"\\section{{{latex_escape(titel)}}}\n{text}\n")
        return self

    def text(self, inhalt: str) -> "LatexReport":
        self.abschnitte.append(inhalt + "\n")
        return self

    def kennzahlentabelle(self, kennzahlen: dict, ueberschrift: str) -> "LatexReport":
        """Wandelt ein Dictionary in eine zweispaltige Tabelle."""
        zeilen = "\n".join(
            f"{latex_escape(k)} & {latex_escape(v)} \\\\"
            for k, v in kennzahlen.items() if v is not None)
        self.abschnitte.append(rf"""
\begin{{table}}[H]
\centering
\caption{{{latex_escape(ueberschrift)}}}
\begin{{tabular}}{{ll}}
\toprule
\textbf{{Groesse}} & \textbf{{Wert}} \\
\midrule
{zeilen}
\bottomrule
\end{{tabular}}
\end{{table}}
""")
        return self

    def dataframe(self, tabelle: pd.DataFrame, ueberschrift: str,
                  max_zeilen: int = 25,
                  max_spalten_hochformat: int = 6) -> "LatexReport":
        """Fuegt einen DataFrame als LaTeX-Tabelle ein.

        Breite Tabellen (z.B. aus den Parameterstudien) sind im Hochformat
        ueber den Seitenrand hinausgelaufen ("Overfull hbox"), die rechten
        Spalten waren im PDF nicht mehr lesbar. Deshalb wird die Tabelle
        jetzt mit `\resizebox` auf die Textbreite skaliert und bei sehr
        vielen Spalten zusaetzlich ins Querformat gestellt.

        Args:
            tabelle: darzustellender DataFrame.
            ueberschrift: Beschriftung der Tabelle.
            max_zeilen: mehr Zeilen werden abgeschnitten.
            max_spalten_hochformat: ab dieser Spaltenzahl Querformat.
        """
        auszug = tabelle.head(max_zeilen)
        spalten = " & ".join(self._kopfzeile(s) for s in auszug.columns)
        zeilen = "\n".join(
            " & ".join(latex_escape(w) for w in zeile) + r" \\"
            for zeile in auszug.itertuples(index=False))
        ausrichtung = "l" * len(auszug.columns)

        tabellenblock = rf"""\resizebox{{\textwidth}}{{!}}{{%
\begin{{tabular}}{{{ausrichtung}}}
\toprule
{spalten} \\
\midrule
{zeilen}
\bottomrule
\end{{tabular}}}}"""

        inhalt = rf"""
\begin{{table}}[H]
\centering
\small
\caption{{{latex_escape(ueberschrift)}}}
{tabellenblock}
\end{{table}}
"""
        if len(auszug.columns) > max_spalten_hochformat:
            inhalt = "\n\\begin{landscape}\n" + inhalt + "\\end{landscape}\n"
        self.abschnitte.append(inhalt)
        return self

    @staticmethod
    def _kopfzeile(spaltenname: str, max_laenge: int = 22) -> str:
        """Kuerzt sehr lange Spaltenueberschriften und setzt sie fett."""
        text = str(spaltenname)
        if len(text) > max_laenge:
            text = text[:max_laenge - 1] + "."
        return r"\textbf{" + latex_escape(text) + "}"

    def bild(self, pfad: str, beschriftung: str, breite: float = 0.95) -> "LatexReport":
        """Bindet eine Grafik ein (Pfad relativ zum Ausgabeordner)."""
        if not os.path.exists(pfad):
            logger.warning("Bild %s existiert nicht und wird uebersprungen.", pfad)
            return self
        relativ = os.path.basename(pfad).replace("\\", "/")
        self.abschnitte.append(rf"""
\begin{{figure}}[H]
\centering
\includegraphics[width={breite}\textwidth]{{{relativ}}}
\caption{{{latex_escape(beschriftung)}}}
\end{{figure}}
""")
        return self

    # -- Ausgabe -----------------------------------------------------------
    def speichere(self) -> str:
        """Schreibt die .tex-Datei und gibt ihren Pfad zurueck."""
        inhalt = (KOPF.replace("DATUM", datetime.now().strftime("%d.%m.%Y, %H:%M Uhr"))
                  + "\n".join(self.abschnitte) + FUSS)
        pfad = os.path.join(self.ordner, self.dateiname)
        with open(pfad, "w", encoding="utf-8") as datei:
            datei.write(inhalt)
        logger.info("LaTeX-Quelltext geschrieben: %s", pfad)
        return pfad

    def kompiliere(self) -> str | None:
        """Uebersetzt die .tex-Datei mit pdflatex, falls verfuegbar.

        Returns:
            Pfad zur PDF-Datei oder None, wenn pdflatex nicht installiert ist
            bzw. die Uebersetzung fehlgeschlagen ist.
        """
        tex_pfad = self.speichere()
        if shutil.which("pdflatex") is None:
            logger.warning("pdflatex ist nicht installiert - es wurde nur die "
                           ".tex-Datei erzeugt (%s).", tex_pfad)
            return None

        for durchlauf in range(2):  # zweimal wegen Inhaltsverzeichnis
            try:
                ergebnis = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode",
                     "-halt-on-error", os.path.basename(tex_pfad)],
                    cwd=self.ordner, capture_output=True, text=True, timeout=120)
            except (subprocess.TimeoutExpired, OSError) as fehler:
                logger.error("pdflatex konnte nicht ausgefuehrt werden: %s", fehler)
                return None
            if ergebnis.returncode != 0 and durchlauf == 1:
                logger.error("pdflatex meldet einen Fehler. Siehe %s",
                             tex_pfad.replace(".tex", ".log"))
                return None

        self.pruefe_log(tex_pfad.replace(".tex", ".log"))

        pdf_pfad = tex_pfad.replace(".tex", ".pdf")
        if os.path.exists(pdf_pfad):
            logger.info("Bericht erstellt: %s", pdf_pfad)
            return pdf_pfad
        return None

    @staticmethod
    def pruefe_log(log_pfad: str) -> int:
        """Prueft das LaTeX-Log auf ueber den Rand laufende Boxen.

        Frueher sind die Tabellen der Parameterstudien rechts aus der Seite
        gelaufen, ohne dass das aufgefallen waere. Diese Pruefung meldet
        solche Faelle jetzt automatisch.

        Returns:
            Anzahl der gefundenen Overfull-hbox-Meldungen.
        """
        if not os.path.exists(log_pfad):
            return 0
        try:
            with open(log_pfad, "r", encoding="utf-8", errors="ignore") as f:
                inhalt = f.read()
        except OSError:
            return 0
        anzahl = inhalt.count("Overfull \\hbox")
        if anzahl:
            logger.warning("Der Bericht enthaelt %d ueberbreite Zeilen "
                           "(Overfull hbox) - siehe %s", anzahl, log_pfad)
        else:
            logger.info("LaTeX-Log geprueft: keine ueberbreiten Boxen.")
        return anzahl


def erstelle_fahrtbericht(track, ergebnisse: dict, plots: list[str],
                          studien: dict, studienplot: str | None,
                          wetter: dict, wegpunkte: list,
                          kartenpfad: str | None,
                          ausgabeordner: str = "output",
                          kapazitaet: dict | None = None) -> str | None:
    """Baut den kompletten Bericht aus allen Ergebnissen zusammen.

    Args:
        track: der ausgewertete `Track`.
        ergebnisse: Dictionary {Akkuname: SimulationsErgebnis}.
        plots: Liste der Pfade zu den erzeugten Grafiken.
        studien: Ergebnisse der Parameterstudien.
        studienplot: Pfad zur Grafik der Parameterstudie.
        wetter: Kennzahlen des Wetters.
        wegpunkte: geocodierte Orte.
        kartenpfad: Pfad zur HTML-Karte.
        kapazitaet: Ergebnis der Akkuauslegung (notwendige Kapazitaet,
            kleinste ausreichende Konfiguration).

    Returns:
        Pfad zur erzeugten PDF-Datei oder None.
    """
    report = LatexReport(ausgabeordner)

    report.abschnitt(
        "Einleitung",
        "Dieser Bericht wurde automatisch aus den aufgezeichneten GPS-Daten "
        "einer Fahrt erzeugt. Ziel des Projekts ist die Auslegung eines "
        "E-Bikes: Aus den Positions-, Hoehen- und Zeitdaten werden "
        "Geschwindigkeit, Beschleunigung, Steigung und die daraus "
        "resultierenden Fahrwiderstaende bestimmt. Daraus ergeben sich "
        "Motorleistung, Drehmoment und Motorstrom sowie der Ladezustand "
        "zweier unterschiedlicher Akkutypen.")

    report.abschnitt("Kenngroessen der Fahrt")
    report.kennzahlentabelle(track.zusammenfassung(), "Auswertung der GPS-Daten")
    if wetter:
        report.kennzahlentabelle(wetter, "Wetterdaten waehrend der Fahrt")
        if wetter.get("Echte API-Daten") != "ja":
            report.text(
                r"\textbf{Hinweis:} Die Wetter-API war bei diesem Lauf nicht "
                r"erreichbar. Die Simulation rechnet daher mit Windstille "
                r"(Offline-Fallback); die oben genannten Windwerte stammen "
                r"nicht aus einer echten Messung." + "\n")

    if wegpunkte:
        orte = " -- ".join(latex_escape(p["ort"]) for p in wegpunkte)
        report.text(f"\\textbf{{Streckenverlauf:}} {orte}.\n")
    if kartenpfad:
        report.text("Eine interaktive Karte der Strecke liegt als "
                    f"\\texttt{{{latex_escape(os.path.basename(kartenpfad))}}} "
                    "im Ausgabeordner.\n")

    report.abschnitt("Ergebnisse der Simulation")
    for name, ergebnis in ergebnisse.items():
        report.text(f"\\subsection{{Akkutyp {latex_escape(name)}}}")
        report.kennzahlentabelle(ergebnis.kennzahlen(),
                                 f"Simulationsergebnisse {name}-Akku")
        if not ergebnis.vollstaendig:
            report.text(r"\textbf{Hinweis:} "
                        + latex_escape(ergebnis.abbruchgrund) + "\n")

    if kapazitaet:
        report.abschnitt(
            "Auslegung der Akkukapazitaet",
            "Fuer die Auslegung wurde die gesamte Strecke einmal mit einem "
            "absichtlich ueberdimensionierten virtuellen Akku simuliert. Aus "
            "dem Maximum des kumulierten Ladungsbedarfs ergibt sich die "
            "tatsaechlich notwendige Kapazitaet - eine lineare Hochrechnung "
            "einer abgebrochenen Fahrt waere bei ungleichmaessigen Strecken "
            "irrefuehrend.")
        report.kennzahlentabelle(kapazitaet, "Notwendige Akkukapazitaet")

    report.abschnitt("Grafische Auswertung")
    beschriftungen = {
        "01_uebersicht.png": "Geschwindigkeit, Leistung, Ladezustand und Spannung",
        "02_hoehenprofil.png": "Hoehenprofil und Steigung",
        "03_kraefte.png": "Fahrwiderstaende und deren Energieanteile",
        "04_akkutemperatur.png": "Akkutemperatur und Akkustrom",
        "05_kennlinien.png": "OCV-Kennlinien von LiPo- und NMC-Akku",
        "06_himmelsrichtungen.png": "Verteilung der Fahrtrichtungen",
        "07_orte.png": "Orte entlang der Strecke",
        "08_akkuvergleich.png": "Vergleich der beiden Akkutypen",
    }
    for pfad in plots:
        name = os.path.basename(pfad)
        report.bild(pfad, beschriftungen.get(name, name))

    if studien:
        report.abschnitt(
            "Parameterstudien",
            "Fuer jede Studie wurde jeweils ein Parameter variiert und die "
            "gesamte Fahrt neu simuliert.")
        if studienplot:
            report.bild(studienplot, "Ergebnisse der Parameterstudien")
        for name, tabelle in studien.items():
            report.dataframe(tabelle.round(2), f"Parameterstudie: {name}")

    report.abschnitt(
        "Zusammenfassung",
        "Die Simulation zeigt, welche Akkukapazitaet fuer die gefahrene "
        "Strecke noetig ist und wie stark einzelne Parameter den Verbrauch "
        "beeinflussen. Die Ergebnisse sind ein vereinfachtes Modell: "
        "Wirkungsgrade, Rollwiderstand und die Akkuparameter sind Annahmen "
        "und muessten fuer eine reale Auslegung messtechnisch abgesichert werden.")

    return report.kompiliere()
