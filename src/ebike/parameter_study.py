"""Automatische Parameterstudien.

Erweiterung "Durchfuehren von automatischen Parameterstudien". Die Klasse
`Parameterstudie` variiert einzelne Parameter (Masse, cw*A, Raddurchmesser,
Rollwiderstand, Akkukapazitaet, ...), fuehrt jeweils eine vollstaendige
Simulation durch und stellt die Ergebnisse tabellarisch und grafisch dar.
"""

import copy
import logging
import os

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .battery import erzeuge_akku  # noqa: E402
from .bike import EBike  # noqa: E402
from .config import ProjectConfig  # noqa: E402
from .simulation import (  # noqa: E402
    FahrtSimulator, kleinste_konfiguration_suchen, mindestkapazitaet_abschaetzen)

logger = logging.getLogger(__name__)


class Parameterstudie:
    """Fuehrt Simulationen mit systematisch variierten Parametern durch."""

    def __init__(self, track_daten: pd.DataFrame, basis_cfg: ProjectConfig,
                 wetterservice=None, ausgabeordner: str = "output"):
        self.track_daten = track_daten
        self.basis_cfg = basis_cfg
        self.wetterservice = wetterservice
        self.ordner = ausgabeordner
        os.makedirs(self.ordner, exist_ok=True)

    # -- Ein einzelner Lauf ------------------------------------------------
    def _einzellauf(self, cfg: ProjectConfig) -> dict:
        """Fuehrt eine Simulation mit der uebergebenen Konfiguration durch."""
        starttemperatur = float(self.track_daten["temperature"].iloc[0])
        akku = erzeuge_akku(cfg.simulation.akkutyp, cfg.battery,
                            starttemperatur_c=starttemperatur,
                            thermik_aktiv=cfg.simulation.thermisches_modell_aktiv)
        simulator = FahrtSimulator(EBike(cfg.bike), akku, cfg, self.wetterservice)
        ergebnis = simulator.simuliere(self.track_daten)
        kennzahlen = ergebnis.kennzahlen()
        # Bei abgebrochenen Fahrten ist Wh/km allein wenig aussagekraeftig -
        # entscheidend sind die erreichte Distanz, ob die Fahrt vollstaendig
        # war und welche Mindestkapazitaet noetig gewesen waere.
        return {
            "Distanz [km]": kennzahlen["Strecke gefahren [km]"],
            "Vollstaendig": kennzahlen["Fahrt vollstaendig"],
            "End-SoC [%]": kennzahlen["End-SoC [%]"],
            "Verbrauch [Wh]": kennzahlen["Energieverbrauch [Wh]"],
            "Verbrauch [Wh/km]": kennzahlen["Verbrauch [Wh/km]"],
            "Min. Kapazitaet [Ah]": mindestkapazitaet_abschaetzen(ergebnis),
            "Max. Leistung [W]": kennzahlen["Maximale Leistung [W]"],
            "Max. Strom [A]": kennzahlen["Maximaler Motorstrom [A]"],
            "Rekuperiert [Wh]": kennzahlen["Rekuperierte Energie [Wh]"],
        }

    # -- Variation eines Parameters ---------------------------------------
    def variiere(self, bereich: str, attribut: str, werte: list,
                 beschriftung: str | None = None) -> pd.DataFrame:
        """Variiert einen einzelnen Parameter.

        Args:
            bereich: "bike", "battery" oder "simulation".
            attribut: Name des Attributs in der jeweiligen Konfiguration.
            werte: Liste der zu untersuchenden Werte.
            beschriftung: Achsenbeschriftung fuer den Plot.

        Returns:
            DataFrame mit einer Zeile pro untersuchtem Wert.

        Raises:
            AttributeError: wenn das Attribut nicht existiert.
        """
        if not hasattr(getattr(self.basis_cfg, bereich), attribut):
            raise AttributeError(
                f"'{attribut}' ist kein Attribut von cfg.{bereich}")

        beschriftung = beschriftung or attribut
        zeilen = []
        for wert in werte:
            cfg = copy.deepcopy(self.basis_cfg)
            setattr(getattr(cfg, bereich), attribut, wert)
            logger.info("Parameterstudie: %s.%s = %s", bereich, attribut, wert)
            ergebnis = self._einzellauf(cfg)
            ergebnis[beschriftung] = wert
            zeilen.append(ergebnis)

        tabelle = pd.DataFrame(zeilen)
        spalten = [beschriftung] + [s for s in tabelle.columns if s != beschriftung]
        return tabelle[spalten]

    # -- Fertige Studien ---------------------------------------------------
    def standardstudien(self) -> dict[str, pd.DataFrame]:
        """Fuehrt die in der Angabe genannten Standardstudien durch."""
        studien = {}
        studien["Gesamtmasse"] = self.variiere(
            "bike", "masse_fahrer_kg", [50, 60, 70, 80, 90, 100, 110],
            "Masse Fahrer [kg]")
        studien["Luftwiderstand"] = self.variiere(
            "bike", "cw_a_m2", [0.30, 0.40, 0.5625, 0.70, 0.85],
            "cw*A [m2]")
        studien["Raddurchmesser"] = self.variiere(
            "bike", "raddurchmesser_inch", [24, 26, 27, 28, 29],
            "Raddurchmesser [inch]")
        studien["Rollwiderstand"] = self.variiere(
            "bike", "rollwiderstandsbeiwert", [0.003, 0.005, 0.006, 0.008, 0.012],
            "Rollwiderstandsbeiwert [-]")
        # Der Bereich muss die tatsaechlich benoetigte Groessenordnung
        # enthalten. Mit 2..6 parallelen Zellen wurde jeder Akku leer, der
        # End-SoC lag ueberall bei 0 % und die Studie war aussagelos.
        studien["Akkukapazitaet"] = self.variiere(
            "battery", "zellen_parallel", [4, 6, 8, 10, 12, 13, 14, 16, 20],
            "Parallele Zellen [-]")
        return studien

    def kleinste_ausreichende_konfiguration(self, reserve: float = 0.15) -> dict:
        """Sucht automatisch die kleinste Konfiguration mit ausreichender Reserve.

        Args:
            reserve: geforderte Restladung am Ziel (0.15 = 15 %).

        Returns:
            Dictionary mit Zellzahl, Kapazitaet und End-SoC.
        """
        return kleinste_konfiguration_suchen(
            self.track_daten, self.basis_cfg, self.wetterservice, reserve)

    # -- Darstellung -------------------------------------------------------
    def plotte(self, studien: dict[str, pd.DataFrame],
               dateiname: str = "09_parameterstudie.png") -> str:
        """Stellt alle Studien in einem gemeinsamen Bild dar."""
        if not studien:
            raise ValueError("Es wurden keine Studien uebergeben.")
        anzahl = len(studien)
        spalten = 2 if anzahl > 1 else 1
        zeilen = (anzahl + spalten - 1) // spalten
        fig, achsen = plt.subplots(zeilen, spalten, figsize=(13, 4 * zeilen),
                                   squeeze=False)
        achsen = achsen.flatten()

        for ax, (name, tabelle) in zip(achsen, studien.items()):
            x_spalte = tabelle.columns[0]
            ax.plot(tabelle[x_spalte], tabelle["Verbrauch [Wh/km]"],
                    "o-", color="tab:blue", label="Verbrauch [Wh/km]")
            ax.set_xlabel(x_spalte)
            ax.set_ylabel("Verbrauch [Wh/km]", color="tab:blue")
            ax.grid(True, alpha=0.3)
            ax.set_title(name)

            ax2 = ax.twinx()
            unvollstaendig = ~tabelle["Vollstaendig"].astype(bool)
            if unvollstaendig.any():
                # Bei abgebrochenen Fahrten sagt der End-SoC (immer 0 %)
                # nichts aus - dann ist die erreichte Distanz die
                # interessante Groesse.
                ax2.plot(tabelle[x_spalte], tabelle["Distanz [km]"],
                         "s--", color="tab:green")
                ax2.set_ylabel("erreichte Distanz [km]", color="tab:green")
                ax.plot(tabelle.loc[unvollstaendig, x_spalte],
                        tabelle.loc[unvollstaendig, "Verbrauch [Wh/km]"],
                        "x", color="tab:red", markersize=9,
                        label="Fahrt abgebrochen")
                ax.legend(fontsize=8)
            else:
                ax2.plot(tabelle[x_spalte], tabelle["End-SoC [%]"],
                         "s--", color="tab:green")
                ax2.set_ylabel("End-SoC [%]", color="tab:green")

        for ax in achsen[anzahl:]:
            ax.axis("off")

        fig.tight_layout()
        pfad = os.path.join(self.ordner, dateiname)
        fig.savefig(pfad, dpi=150)
        plt.close(fig)
        logger.info("Parameterstudie gespeichert: %s", pfad)
        return pfad

    def speichere_csv(self, studien: dict[str, pd.DataFrame],
                      dateiname: str = "parameterstudie.csv") -> str:
        """Schreibt alle Studien in eine gemeinsame CSV-Datei."""
        teile = []
        for name, tabelle in studien.items():
            kopie = tabelle.copy()
            kopie.insert(0, "Studie", name)
            kopie = kopie.rename(columns={kopie.columns[1]: "Parameterwert"})
            teile.append(kopie)
        gesamt = pd.concat(teile, ignore_index=True)
        pfad = os.path.join(self.ordner, dateiname)
        gesamt.to_csv(pfad, index=False, sep=";")
        logger.info("Parameterstudie als CSV gespeichert: %s", pfad)
        return pfad
