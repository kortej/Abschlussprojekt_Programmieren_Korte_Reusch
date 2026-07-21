"""Geodaetische Hilfsfunktionen.

Enthaelt die Haversine-Formel fuer die Distanz zwischen zwei GPS-Punkten,
die Berechnung der Fahrtrichtung (Bearing) und die Umrechnung eines Winkels
in eine Himmelsrichtung.
"""

import math

ERDRADIUS_M = 6371000.0

# Kuerzel der 16 Himmelsrichtungen, beginnend bei Norden
HIMMELSRICHTUNGEN = [
    "N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def haversine_distanz(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Berechnet die Distanz zweier GPS-Punkte auf der Erdoberflaeche in Metern.

    Args:
        lat1, lon1: Breiten- und Laengengrad des ersten Punktes in Grad.
        lat2, lon2: Breiten- und Laengengrad des zweiten Punktes in Grad.

    Returns:
        Horizontale Distanz in Metern.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return ERDRADIUS_M * c


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Berechnet die Fahrtrichtung von Punkt 1 nach Punkt 2.

    Returns:
        Winkel in Grad, gemessen im Uhrzeigersinn von Norden (0..360).
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)

    x = math.sin(delta_lambda) * math.cos(phi2)
    y = (math.cos(phi1) * math.sin(phi2)
         - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda))
    winkel = math.degrees(math.atan2(x, y))
    return (winkel + 360.0) % 360.0


def himmelsrichtung(winkel_grad: float) -> str:
    """Wandelt einen Winkel in eine Himmelsrichtung um (z.B. 95 Grad -> 'O')."""
    winkel = winkel_grad % 360.0
    # 360 Grad / 16 Sektoren = 22.5 Grad pro Sektor
    index = int((winkel + 11.25) // 22.5) % 16
    return HIMMELSRICHTUNGEN[index]


def steigungswinkel(delta_hoehe_m: float, delta_strecke_m: float) -> float:
    """Berechnet den Steigungswinkel phi aus Hoehen- und Streckendifferenz.

    Args:
        delta_hoehe_m: Hoehenunterschied in Metern (positiv = bergauf).
        delta_strecke_m: horizontal zurueckgelegte Strecke in Metern.

    Returns:
        Steigungswinkel in Radiant. Bei Stillstand wird 0 zurueckgegeben.
    """
    if delta_strecke_m <= 0.0:
        return 0.0
    return math.atan2(delta_hoehe_m, delta_strecke_m)
