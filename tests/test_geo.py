"""Tests fuer die geodaetischen Hilfsfunktionen."""

import math

import pytest

from ebike import geo


class TestHaversine:
    def test_gleicher_punkt_ergibt_null(self):
        assert geo.haversine_distanz(47.5, 12.1, 47.5, 12.1) == pytest.approx(0.0)

    def test_bekannte_distanz_innsbruck_muenchen(self):
        # Luftlinie Innsbruck - Muenchen betraegt rund 97 km
        d = geo.haversine_distanz(47.2692, 11.4041, 48.1351, 11.5820)
        assert d == pytest.approx(97000, rel=0.03)

    def test_symmetrie(self):
        a = geo.haversine_distanz(47.58, 12.17, 47.59, 12.18)
        b = geo.haversine_distanz(47.59, 12.18, 47.58, 12.17)
        assert a == pytest.approx(b)

    def test_ein_breitengrad_entspricht_111_km(self):
        d = geo.haversine_distanz(47.0, 12.0, 48.0, 12.0)
        assert d == pytest.approx(111195, rel=0.01)


class TestBearing:
    def test_richtung_norden(self):
        assert geo.bearing(47.0, 12.0, 48.0, 12.0) == pytest.approx(0.0, abs=0.1)

    def test_richtung_osten(self):
        assert geo.bearing(47.0, 12.0, 47.0, 13.0) == pytest.approx(90.0, abs=0.5)

    def test_ergebnis_immer_zwischen_0_und_360(self):
        winkel = geo.bearing(47.0, 12.0, 46.0, 11.0)
        assert 0.0 <= winkel < 360.0


class TestHimmelsrichtung:
    @pytest.mark.parametrize("winkel,erwartet", [
        (0, "N"), (90, "O"), (180, "S"), (270, "W"),
        (45, "NO"), (359, "N"), (360, "N"),
    ])
    def test_bekannte_winkel(self, winkel, erwartet):
        assert geo.himmelsrichtung(winkel) == erwartet

    def test_negative_winkel_werden_umgerechnet(self):
        assert geo.himmelsrichtung(-90) == "W"


class TestSteigungswinkel:
    def test_ebene_strecke(self):
        assert geo.steigungswinkel(0.0, 100.0) == pytest.approx(0.0)

    def test_45_grad(self):
        assert geo.steigungswinkel(10.0, 10.0) == pytest.approx(math.pi / 4)

    def test_gefaelle_ist_negativ(self):
        assert geo.steigungswinkel(-5.0, 100.0) < 0

    def test_stillstand_gibt_null(self):
        # Ohne zurueckgelegte Strecke gibt es keine definierte Steigung
        assert geo.steigungswinkel(5.0, 0.0) == 0.0
