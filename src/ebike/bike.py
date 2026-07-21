"""Modell des E-Bikes: Fahrwiderstaende, Leistung, Drehmoment, Motorstrom.

Umgesetzt ist das Freikoerperdiagramm aus der Angabe:

    F_antrieb = F_beschl + F_steigung + F_roll + F_luft

Daraus folgen Leistung, Raddrehmoment und - ueber die Motorkonstante - der
Motorstrom.
"""

import logging
import math


from .config import G, BikeConfig
from .environment import Wind

logger = logging.getLogger(__name__)


class EBike:
    """Ein E-Bike mit Fahrer. Berechnet die noetige Antriebskraft."""

    def __init__(self, konfiguration: BikeConfig | None = None):
        self.cfg = konfiguration if konfiguration is not None else BikeConfig()
        if self.cfg.gesamtmasse_kg <= 0:
            raise ValueError("Die Gesamtmasse muss groesser als 0 sein.")
        if self.cfg.motorkonstante_nm_per_a <= 0:
            raise ValueError("Die Motorkonstante muss groesser als 0 sein.")

    # -- Einzelne Fahrwiderstaende ----------------------------------------
    def kraft_beschleunigung(self, a_ms2: float) -> float:
        """Traegheitskraft F = m * a in Newton."""
        return self.cfg.gesamtmasse_kg * a_ms2

    def kraft_steigung(self, phi_rad: float) -> float:
        """Hangabtriebskraft F = m * g * sin(phi) in Newton."""
        return self.cfg.gesamtmasse_kg * G * math.sin(phi_rad)

    def kraft_rollwiderstand(self, phi_rad: float, v_ms: float) -> float:
        """Rollwiderstand F = c_rr * m * g * cos(phi) in Newton.

        Bei Stillstand rollt nichts, deshalb wird dann 0 zurueckgegeben.
        """
        if v_ms <= 0.01:
            return 0.0
        return (self.cfg.rollwiderstandsbeiwert * self.cfg.gesamtmasse_kg
                * G * math.cos(phi_rad))

    def kraft_luftwiderstand(self, v_ms: float, luftdichte: float,
                             wind: Wind | None = None,
                             fahrtrichtung_grad: float = 0.0) -> float:
        """Luftwiderstand F_D = 0.5 * rho * cw*A * v_rel^2 in Newton.

        Bei Rueckenwind kann v_rel negativ werden, dann schiebt der Wind und
        die Kraft wird negativ. Deshalb rechnen wir mit v_rel * |v_rel|.
        """
        v_rel = v_ms
        if wind is not None:
            v_rel = wind.anstroemgeschwindigkeit(v_ms, fahrtrichtung_grad)
        return 0.5 * luftdichte * self.cfg.cw_a_m2 * v_rel * abs(v_rel)

    # -- Zusammengesetzte Groessen ----------------------------------------
    def antriebskraft(self, v_ms: float, a_ms2: float, phi_rad: float,
                      luftdichte: float, wind: Wind | None = None,
                      fahrtrichtung_grad: float = 0.0) -> float:
        """Summe aller Fahrwiderstaende in Newton (negativ = Bremsen noetig)."""
        return (self.kraft_beschleunigung(a_ms2)
                + self.kraft_steigung(phi_rad)
                + self.kraft_rollwiderstand(phi_rad, v_ms)
                + self.kraft_luftwiderstand(v_ms, luftdichte, wind, fahrtrichtung_grad))

    def mechanische_leistung(self, kraft_n: float, v_ms: float) -> float:
        """Mechanische Leistung am Rad P = F * v in Watt."""
        return kraft_n * v_ms

    def drehmoment(self, kraft_n: float) -> float:
        """Drehmoment am angetriebenen Rad T = F * r in Nm.

        Angetrieben wird nur ein Rad (Radnabenmotor ohne Getriebe), die
        gesamte Antriebskraft wirkt also ueber einen Radradius.
        """
        return kraft_n * self.cfg.radradius_m

    def motorstrom(self, drehmoment_nm: float) -> float:
        """Motorstrom I = T / Km in Ampere."""
        return drehmoment_nm / self.cfg.motorkonstante_nm_per_a

    def strom_aus_fahrzustand(self, v_ms: float, a_ms2: float, phi_rad: float,
                              luftdichte: float, wind: Wind | None = None,
                              fahrtrichtung_grad: float = 0.0) -> dict:
        """Berechnet in einem Schritt Kraft, Leistung, Moment und Strom.

        Returns:
            Dictionary mit den Zwischen- und Endergebnissen.
        """
        f = self.antriebskraft(v_ms, a_ms2, phi_rad, luftdichte, wind, fahrtrichtung_grad)
        p_mech = self.mechanische_leistung(f, v_ms)
        t = self.drehmoment(f)
        i = self.motorstrom(t)
        return {
            "kraft_n": f,
            "p_mech_w": p_mech,
            "drehmoment_nm": t,
            "strom_ideal_a": i,
        }

    def __repr__(self) -> str:
        return (f"EBike(m={self.cfg.gesamtmasse_kg:.0f} kg, "
                f"cwA={self.cfg.cw_a_m2} m^2, "
                f"r_rad={self.cfg.radradius_m:.3f} m)")
