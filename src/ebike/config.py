"""Zentrale Konfiguration des Projekts.

Alle Parameter der Simulation stehen hier an einer Stelle. Dadurch muessen wir
zum Aendern eines Wertes nicht im ganzen Code suchen. Verwendet werden
`dataclasses`, weil sie sehr wenig Schreibarbeit machen und trotzdem echte
Klassen sind.
"""

from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Projektpfade
# ---------------------------------------------------------------------------
# Alle Standardpfade werden relativ zum Projektordner aufgeloest und nicht
# relativ zum aktuellen Arbeitsverzeichnis. Dadurch laesst sich das Programm
# auch aus einem beliebigen anderen Ordner starten:
#     python C:\...\ebike-simulation\main.py
PROJEKTORDNER = Path(__file__).resolve().parents[2]
STANDARD_DATENPFAD = PROJEKTORDNER / "data" / "final_project_input_data.csv"
STANDARD_AUSGABEORDNER = PROJEKTORDNER / "output"


def pfad_aufloesen(pfad: str | Path) -> str:
    """Loest einen Pfad sinnvoll auf.

    Absolute Pfade bleiben unveraendert. Ein relativer Pfad wird zuerst
    gegenueber dem aktuellen Arbeitsverzeichnis geprueft; existiert er dort
    nicht, wird er relativ zum Projektordner interpretiert.
    """
    p = Path(pfad).expanduser()
    if p.is_absolute():
        return str(p)
    if p.exists():
        return str(p.resolve())
    return str((PROJEKTORDNER / p).resolve())


# ---------------------------------------------------------------------------
# Physikalische Konstanten
# ---------------------------------------------------------------------------
G = 9.81  # Erdbeschleunigung in m/s^2
R_LUFT = 287.058  # spezifische Gaskonstante trockener Luft in J/(kg*K)
P0 = 101325.0  # Standard-Luftdruck auf Meereshoehe in Pa
T0 = 288.15  # Standard-Temperatur auf Meereshoehe in K
TEMPERATURGRADIENT = 0.0065  # Temperaturabnahme in K/m
INCH_IN_M = 0.0254  # 1 Zoll in Meter


@dataclass
class BikeConfig:
    """Parameter von Fahrrad und Fahrer (Werte aus der Angabe)."""

    masse_fahrer_kg: float = 70.0
    masse_fahrrad_kg: float = 10.0
    cw_a_m2: float = 0.5625  # Produkt aus cw-Wert und Stirnflaeche
    raddurchmesser_inch: float = 27.0
    motorkonstante_nm_per_a: float = 1.5
    rollwiderstandsbeiwert: float = 0.006  # typ. Wert Fahrradreifen auf Asphalt
    wirkungsgrad_antrieb: float = 0.85  # Verluste Motor + Elektronik
    wirkungsgrad_rekuperation: float = 0.50  # beim Bremsen zurueckgewonnener Anteil

    @property
    def gesamtmasse_kg(self) -> float:
        """Gesamtmasse von Fahrer und Fahrrad."""
        return self.masse_fahrer_kg + self.masse_fahrrad_kg

    @property
    def radradius_m(self) -> float:
        """Radradius in Meter."""
        return self.raddurchmesser_inch * INCH_IN_M / 2.0


@dataclass
class BatteryConfig:
    """Aufbau des Akkupacks (10S xP laut Angabe).

    Die Zellkapazitaet ist in der Angabe nicht festgelegt, wir nehmen eine
    typische Zelle mit 3.5 Ah an. Ueber `zellen_parallel` laesst sich die
    Packkapazitaet skalieren.

    Der Standardwert von 20 parallelen Zellen (= 70 Ah bzw. rund 2.7 kWh)
    ist bewusst grosszuegig gewaehlt, damit die aufgezeichnete Fahrt sicher
    vollstaendig simuliert werden kann. Die tatsaechlich noetige Groesse
    bestimmt `simulation.notwendige_kapazitaet()`; mit `--auslegung` sucht das
    Programm die kleinste ausreichende Konfiguration automatisch.
    Ein handelsueblicher E-Bike-Akku (4P = 14 Ah, ca. 550 Wh) reicht fuer
    diese Strecke nicht aus - nachvollziehbar mit `--zellen-parallel 4`.
    """

    zellen_seriell: int = 10
    zellen_parallel: int = 20
    zellkapazitaet_ah: float = 3.5
    start_soc: float = 1.0
    # thermisches Modell
    waermekapazitaet_j_per_k: float = 45000.0  # Pack (~ 2 kg * ...)
    waermeuebergang_w_per_k: float = 3.0  # Kuehlung an Umgebungsluft
    temperaturkoeffizient_ri: float = 0.015  # 1/K, Ri steigt bei Kaelte
    referenztemperatur_c: float = 25.0
    max_ladestrom_a: float = 15.0  # mehr kann der Akku nicht aufnehmen


@dataclass
class SimulationConfig:
    """Einstellungen fuer den Ablauf der Simulation."""

    akkutyp: str = "lipo"  # "lipo" oder "nmc"
    rekuperation_aktiv: bool = True
    thermisches_modell_aktiv: bool = True
    wind_aktiv: bool = True
    glaettung_fenster: int = 9  # Fensterbreite fuer die Glaettung der Rohdaten
    max_geschwindigkeit_ms: float = 25.0  # Plausibilitaetsgrenze fuer GPS-Ausreisser
    # Die GPS-Hoehe rauscht stark. Die Steigung wird deshalb nicht zwischen
    # zwei Einzelpunkten, sondern ueber ein Streckenfenster bestimmt.
    steigung_fenster_m: float = 30.0  # Basislaenge der Steigungsberechnung in m
    max_steigung_prozent: float = 30.0  # Plausibilitaetsgrenze der Steigung
    max_beschleunigung_ms2: float = 3.0  # Plausibilitaetsgrenze der Beschleunigung


@dataclass
class ProjectConfig:
    """Sammelklasse: haelt alle Teil-Konfigurationen zusammen."""

    bike: BikeConfig = field(default_factory=BikeConfig)
    battery: BatteryConfig = field(default_factory=BatteryConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    datenpfad: str = str(STANDARD_DATENPFAD)
    ausgabeordner: str = str(STANDARD_AUSGABEORDNER)
