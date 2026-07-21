"""Grafische Darstellung der Simulationsergebnisse mit matplotlib.

Alle Methoden speichern die Grafik als PNG und geben den Dateipfad zurueck,
damit die Bilder spaeter im LaTeX-Report eingebunden werden koennen.
"""

import logging
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")  # kein Fenster noetig, wir speichern nur Dateien
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)


class ErgebnisPlotter:
    """Erzeugt alle Diagramme zu einer Simulation."""

    def __init__(self, ergebnis, ausgabeordner: str = "output"):
        self.ergebnis = ergebnis
        self.daten = ergebnis.daten
        self.ordner = ausgabeordner
        os.makedirs(self.ordner, exist_ok=True)

    def _speichern(self, fig, dateiname: str) -> str:
        pfad = os.path.join(self.ordner, dateiname)
        fig.tight_layout()
        fig.savefig(pfad, dpi=150)
        plt.close(fig)
        logger.info("Plot gespeichert: %s", pfad)
        return pfad

    # -- Einzelne Plots ----------------------------------------------------
    def uebersicht(self, dateiname: str = "01_uebersicht.png") -> str:
        """Vier Diagramme: Geschwindigkeit, Leistung, SoC und Spannung."""
        d = self.daten
        t_min = d["t_s"] / 60.0

        fig, achsen = plt.subplots(4, 1, figsize=(11, 12), sharex=True)

        achsen[0].plot(t_min, d["v_kmh"], color="tab:blue", linewidth=0.8)
        achsen[0].set_ylabel("Geschwindigkeit [km/h]")
        achsen[0].set_title("Verlauf der Fahrt")

        achsen[1].plot(t_min, d["p_mech_w"], color="tab:red", linewidth=0.6)
        achsen[1].axhline(0, color="grey", linewidth=0.8)
        achsen[1].set_ylabel("mech. Leistung [W]")

        achsen[2].plot(t_min, d["soc"] * 100, color="tab:green", linewidth=1.2)
        achsen[2].set_ylabel("Ladezustand [%]")
        achsen[2].set_ylim(0, 105)

        achsen[3].plot(t_min, d["spannung_v"], color="tab:purple", linewidth=0.8)
        achsen[3].set_ylabel("Klemmenspannung [V]")
        achsen[3].set_xlabel("Zeit [min]")

        for a in achsen:
            a.grid(True, alpha=0.3)
        return self._speichern(fig, dateiname)

    def hoehenprofil(self, dateiname: str = "02_hoehenprofil.png") -> str:
        """Hoehenprofil ueber der Distanz, eingefaerbt nach Steigung."""
        d = self.daten
        km = d["distanz_m"] / 1000.0

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        ax1.fill_between(km, d["ele_m"], d["ele_m"].min() - 10,
                         color="tab:brown", alpha=0.35)
        ax1.plot(km, d["ele_m"], color="tab:brown", linewidth=1.0)
        ax1.set_ylabel("Seehoehe [m]")
        ax1.set_title("Hoehenprofil der Fahrt")
        ax1.grid(True, alpha=0.3)

        ax2.plot(km, d["steigung_prozent"], color="tab:orange", linewidth=0.5)
        ax2.axhline(0, color="grey", linewidth=0.8)
        ax2.set_ylabel("Steigung [%]")
        ax2.set_xlabel("Distanz [km]")
        ax2.set_ylim(-25, 25)
        ax2.grid(True, alpha=0.3)
        return self._speichern(fig, dateiname)

    def kraefte(self, dateiname: str = "03_kraefte.png") -> str:
        """Aufteilung der Fahrwiderstaende."""
        d = self.daten
        t_min = d["t_s"] / 60.0

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
        ax1.plot(t_min, d["f_steig_n"], label="Steigung", linewidth=0.6)
        ax1.plot(t_min, d["f_luft_n"], label="Luftwiderstand", linewidth=0.6)
        ax1.plot(t_min, d["f_roll_n"], label="Rollwiderstand", linewidth=0.6)
        ax1.plot(t_min, d["f_beschl_n"], label="Beschleunigung", linewidth=0.4, alpha=0.6)
        ax1.set_xlabel("Zeit [min]")
        ax1.set_ylabel("Kraft [N]")
        ax1.set_title("Fahrwiderstaende ueber die Zeit")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Mittlere Energieanteile (nur antreibende Anteile)
        anteile = {}
        for spalte, name in [("f_steig_n", "Steigung"),
                             ("f_luft_n", "Luft"),
                             ("f_roll_n", "Rollen"),
                             ("f_beschl_n", "Beschleunigung")]:
            arbeit = np.sum(np.clip(d[spalte], 0, None) * d["distanz_m"].diff().fillna(0))
            anteile[name] = arbeit / 3.6e6  # in kWh
        ax2.bar(list(anteile.keys()), list(anteile.values()), color="tab:blue")
        ax2.set_ylabel("Arbeit [kWh]")
        ax2.set_title("Energieanteile der Widerstaende")
        ax2.grid(True, axis="y", alpha=0.3)
        return self._speichern(fig, dateiname)

    def akkutemperatur(self, dateiname: str = "04_akkutemperatur.png") -> str:
        """Akkutemperatur, Umgebungstemperatur und Akkustrom."""
        d = self.daten
        t_min = d["t_s"] / 60.0

        fig, ax1 = plt.subplots(figsize=(11, 5))
        ax1.plot(t_min, d["akku_temp_c"], color="tab:red", label="Akkutemperatur")
        ax1.plot(t_min, d["umgebungstemp_c"], color="tab:blue",
                 linewidth=0.8, label="Umgebungstemperatur")
        ax1.set_xlabel("Zeit [min]")
        ax1.set_ylabel("Temperatur [C]")
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc="upper left")

        ax2 = ax1.twinx()
        ax2.plot(t_min, d["strom_akku_a"], color="grey", alpha=0.3, linewidth=0.4)
        ax2.set_ylabel("Akkustrom [A]")
        ax1.set_title("Thermisches Verhalten des Akkus")
        return self._speichern(fig, dateiname)

    def kennlinien(self, akkus: list, dateiname: str = "05_kennlinien.png") -> str:
        """Vergleich der OCV-SoC-Kennlinien der beiden Akkutypen."""
        soc = np.linspace(0, 1, 200)
        fig, ax = plt.subplots(figsize=(8, 5))
        for akku in akkus:
            spannungen = [akku.open_circuit_voltage(s) for s in soc]
            ax.plot(soc * 100, spannungen, label=f"{akku.name}-Akku")
        ax.set_xlabel("Ladezustand [%]")
        ax.set_ylabel("Leerlaufspannung [V]")
        ax.set_title("OCV-Kennlinien der simulierten Akkutypen")
        ax.grid(True, alpha=0.3)
        ax.legend()
        return self._speichern(fig, dateiname)

    def himmelsrichtungen(self, dateiname: str = "06_himmelsrichtungen.png") -> str:
        """Windrose: wie viel Strecke wurde in welche Richtung gefahren."""
        d = self.daten
        strecke = d["distanz_m"].diff().fillna(0.0)
        richtungen = np.deg2rad(d["richtung_grad"])

        anzahl_sektoren = 16
        kanten = np.linspace(0, 2 * np.pi, anzahl_sektoren + 1)
        summen = np.zeros(anzahl_sektoren)
        for winkel, s in zip(richtungen, strecke):
            sektor = int(((winkel + np.pi / anzahl_sektoren) % (2 * np.pi))
                         // (2 * np.pi / anzahl_sektoren))
            summen[sektor] += s

        fig = plt.figure(figsize=(7, 7))
        ax = fig.add_subplot(projection="polar")
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.bar(kanten[:-1], summen / 1000.0,
               width=2 * np.pi / anzahl_sektoren, bottom=0.0,
               color="tab:cyan", edgecolor="k", linewidth=0.4)
        ax.set_title("Zurueckgelegte Strecke [km] je Himmelsrichtung")
        return self._speichern(fig, dateiname)

    def orte(self, wegpunkte: list, dateiname: str = "07_orte.png") -> str:
        """Hoehenprofil mit den per Reverse Geocoding bestimmten Ortsnamen."""
        d = self.daten
        km = d["distanz_m"] / 1000.0

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(km, d["ele_m"], color="tab:brown", linewidth=1.0)
        ax.fill_between(km, d["ele_m"], d["ele_m"].min() - 10,
                        color="tab:brown", alpha=0.25)

        for punkt in wegpunkte:
            hoehe = np.interp(punkt["distanz_km"], km, d["ele_m"])
            ax.plot(punkt["distanz_km"], hoehe, "o", color="tab:red", markersize=5)
            ax.annotate(punkt["ort"], (punkt["distanz_km"], hoehe),
                        textcoords="offset points", xytext=(0, 12),
                        ha="center", fontsize=8, rotation=30)
        ax.set_xlabel("Distanz [km]")
        ax.set_ylabel("Seehoehe [m]")
        ax.set_title("Orte entlang der Strecke (Reverse Geocoding, OpenStreetMap)")
        ax.grid(True, alpha=0.3)
        return self._speichern(fig, dateiname)

    def akkuvergleich(self, ergebnisse: dict,
                      dateiname: str = "08_akkuvergleich.png") -> str:
        """Vergleicht den SoC-Verlauf mehrerer Akkutypen."""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
        for name, erg in ergebnisse.items():
            d = erg.daten
            ax1.plot(d["distanz_m"] / 1000.0, d["soc"] * 100, label=name)
            ax2.plot(d["distanz_m"] / 1000.0, d["spannung_v"],
                     linewidth=0.7, label=name)
        ax1.set_ylabel("Ladezustand [%]")
        ax1.set_title("Vergleich der Akkutypen")
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        ax2.set_ylabel("Klemmenspannung [V]")
        ax2.set_xlabel("Distanz [km]")
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        return self._speichern(fig, dateiname)

    def alle(self, akkus: list | None = None, wegpunkte: list | None = None) -> list[str]:
        """Erzeugt alle Standardplots und gibt die Dateipfade zurueck."""
        pfade = [self.uebersicht(), self.hoehenprofil(), self.kraefte(),
                 self.akkutemperatur(), self.himmelsrichtungen()]
        if akkus:
            pfade.append(self.kennlinien(akkus))
        if wegpunkte:
            pfade.append(self.orte(wegpunkte))
        return pfade
