"""E-Bike-Simulation - Abschlussprojekt Programmieren 1 (MCI).

Das Paket berechnet aus aufgezeichneten GPS-Daten die Fahrwiderstaende eines
E-Bikes und simuliert damit den Ladezustand zweier Akkutypen.
"""

__version__ = "1.0.0"

from .bike import EBike
from .battery import BatteryPack, LiPoAkku, NmcAkku, erzeuge_akku
from .config import ProjectConfig
from .data_loader import Track
from .simulation import FahrtSimulator, SimulationsErgebnis

__all__ = [
    "EBike",
    "BatteryPack",
    "LiPoAkku",
    "NmcAkku",
    "erzeuge_akku",
    "ProjectConfig",
    "Track",
    "FahrtSimulator",
    "SimulationsErgebnis",
]
