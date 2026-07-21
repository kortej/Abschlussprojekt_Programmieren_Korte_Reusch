"""Umgebungsmodell: Luftdruck, Luftdichte und Wind.

Erweiterung "Bestimmung der Luftdichte aus Temperatur und Hoehe ueber dem
Meeresspiegel".

Die Luftdichte geht direkt in die Luftwiderstandskraft ein
(F_D = 0.5 * rho * cw*A * v^2). Statt eines konstanten Wertes von 1.225 kg/m^3
berechnen wir sie aus der gemessenen Temperatur und der Seehoehe.
"""

import logging
import math

from .config import G, P0, R_LUFT, T0, TEMPERATURGRADIENT

logger = logging.getLogger(__name__)


class Atmosphaere:
    """Berechnet Luftdruck und Luftdichte nach der barometrischen Hoehenformel."""

    def __init__(self, druck_meereshoehe_pa: float = P0):
        self.druck_meereshoehe_pa = druck_meereshoehe_pa

    def druck(self, hoehe_m: float) -> float:
        """Luftdruck in Pa auf der Seehoehe `hoehe_m` (Standardatmosphaere)."""
        basis = 1.0 - TEMPERATURGRADIENT * hoehe_m / T0
        if basis <= 0:
            raise ValueError(f"Hoehe {hoehe_m} m liegt ausserhalb des Modellbereichs.")
        exponent = G / (R_LUFT * TEMPERATURGRADIENT)
        return self.druck_meereshoehe_pa * basis ** exponent

    def luftdichte(self, hoehe_m: float, temperatur_c: float) -> float:
        """Luftdichte in kg/m^3 aus Seehoehe und gemessener Lufttemperatur.

        Verwendet wird das ideale Gasgesetz rho = p / (R * T). Der Druck kommt
        aus der barometrischen Hoehenformel, die Temperatur aus der Messung.
        """
        temperatur_k = temperatur_c + 273.15
        if temperatur_k <= 0:
            raise ValueError("Temperatur unterhalb des absoluten Nullpunkts.")
        return self.druck(hoehe_m) / (R_LUFT * temperatur_k)

    def feuchte_luftdichte(self, hoehe_m: float, temperatur_c: float,
                           relative_feuchte: float) -> float:
        """Luftdichte unter Beruecksichtigung der Luftfeuchtigkeit.

        Feuchte Luft ist leichter als trockene Luft. Der Effekt ist klein
        (< 1 %), wir bilden ihn aber der Vollstaendigkeit halber ab.

        Args:
            relative_feuchte: 0.0 bis 1.0
        """
        if not 0.0 <= relative_feuchte <= 1.0:
            raise ValueError("Die relative Feuchte muss zwischen 0 und 1 liegen.")
        p_gesamt = self.druck(hoehe_m)
        t_k = temperatur_c + 273.15
        # Saettigungsdampfdruck nach Magnus-Formel (in Pa)
        p_saett = 610.94 * math.exp(17.625 * temperatur_c / (temperatur_c + 243.04))
        p_dampf = relative_feuchte * p_saett
        p_trocken = p_gesamt - p_dampf
        return p_trocken / (R_LUFT * t_k) + p_dampf / (461.495 * t_k)


class Wind:
    """Modelliert den Wind und dessen Einfluss auf die Anstroemgeschwindigkeit."""

    def __init__(self, geschwindigkeit_ms: float = 0.0, richtung_grad: float = 0.0):
        """
        Args:
            geschwindigkeit_ms: Windgeschwindigkeit in m/s.
            richtung_grad: meteorologische Windrichtung, also die Richtung
                aus der der Wind kommt (0 = Nordwind).
        """
        self.geschwindigkeit_ms = geschwindigkeit_ms
        self.richtung_grad = richtung_grad

    def gegenwindkomponente(self, fahrtrichtung_grad: float) -> float:
        """Anteil des Windes, der direkt gegen den Fahrer blaest (in m/s).

        Positive Werte bedeuten Gegenwind, negative Werte Rueckenwind.
        """
        # Der Wind kommt aus `richtung_grad`, weht also in die Gegenrichtung.
        winkel = math.radians(self.richtung_grad - fahrtrichtung_grad)
        return self.geschwindigkeit_ms * math.cos(winkel)

    def anstroemgeschwindigkeit(self, v_fahrrad_ms: float,
                                fahrtrichtung_grad: float) -> float:
        """Relative Anstroemgeschwindigkeit fuer den Luftwiderstand."""
        return v_fahrrad_ms + self.gegenwindkomponente(fahrtrichtung_grad)

    def __repr__(self) -> str:
        return (f"Wind({self.geschwindigkeit_ms:.1f} m/s aus "
                f"{self.richtung_grad:.0f} Grad)")
