"""Tests fuer das Umgebungsmodell (Luftdichte, Wind) und das E-Bike-Modell."""

import math

import pytest

from ebike.bike import EBike
from ebike.config import G, BikeConfig
from ebike.environment import Atmosphaere, Wind


class TestAtmosphaere:
    def test_druck_auf_meereshoehe(self):
        assert Atmosphaere().druck(0.0) == pytest.approx(101325.0)

    def test_druck_nimmt_mit_hoehe_ab(self):
        atm = Atmosphaere()
        assert atm.druck(2000.0) < atm.druck(0.0)

    def test_luftdichte_standardbedingungen(self):
        # 15 C auf Meereshoehe -> ca. 1.225 kg/m^3
        rho = Atmosphaere().luftdichte(0.0, 15.0)
        assert rho == pytest.approx(1.225, abs=0.005)

    def test_warme_luft_ist_leichter(self):
        atm = Atmosphaere()
        assert atm.luftdichte(500.0, 30.0) < atm.luftdichte(500.0, 0.0)

    def test_hohe_luft_ist_duenner(self):
        atm = Atmosphaere()
        assert atm.luftdichte(2000.0, 15.0) < atm.luftdichte(0.0, 15.0)

    def test_feuchte_luft_ist_leichter_als_trockene(self):
        atm = Atmosphaere()
        assert atm.feuchte_luftdichte(0.0, 25.0, 1.0) < atm.luftdichte(0.0, 25.0)

    def test_ungueltige_feuchte(self):
        with pytest.raises(ValueError):
            Atmosphaere().feuchte_luftdichte(0.0, 20.0, 1.5)

    def test_unphysikalische_temperatur(self):
        with pytest.raises(ValueError):
            Atmosphaere().luftdichte(0.0, -300.0)


class TestWind:
    def test_gegenwind(self):
        # Fahrt nach Norden, Wind kommt aus Norden -> voller Gegenwind
        wind = Wind(geschwindigkeit_ms=5.0, richtung_grad=0.0)
        assert wind.gegenwindkomponente(0.0) == pytest.approx(5.0)

    def test_rueckenwind(self):
        wind = Wind(5.0, 180.0)
        assert wind.gegenwindkomponente(0.0) == pytest.approx(-5.0)

    def test_seitenwind_hat_keine_komponente(self):
        wind = Wind(5.0, 90.0)
        assert wind.gegenwindkomponente(0.0) == pytest.approx(0.0, abs=1e-9)

    def test_anstroemgeschwindigkeit(self):
        wind = Wind(3.0, 0.0)
        assert wind.anstroemgeschwindigkeit(10.0, 0.0) == pytest.approx(13.0)


class TestEBike:
    @pytest.fixture
    def bike(self):
        return EBike(BikeConfig())

    def test_gesamtmasse(self, bike):
        assert bike.cfg.gesamtmasse_kg == pytest.approx(80.0)

    def test_radradius(self, bike):
        # 27 Zoll -> Durchmesser 0.6858 m -> Radius 0.3429 m
        assert bike.cfg.radradius_m == pytest.approx(0.3429, abs=1e-4)

    def test_beschleunigungskraft(self, bike):
        assert bike.kraft_beschleunigung(2.0) == pytest.approx(160.0)

    def test_steigungskraft_bei_ebene_ist_null(self, bike):
        assert bike.kraft_steigung(0.0) == pytest.approx(0.0)

    def test_steigungskraft_bergauf(self, bike):
        phi = math.radians(10)
        erwartet = 80.0 * G * math.sin(phi)
        assert bike.kraft_steigung(phi) == pytest.approx(erwartet)

    def test_gefaelle_gibt_negative_kraft(self, bike):
        assert bike.kraft_steigung(math.radians(-10)) < 0

    def test_rollwiderstand_bei_stillstand_null(self, bike):
        assert bike.kraft_rollwiderstand(0.0, 0.0) == 0.0

    def test_rollwiderstand_in_der_ebene(self, bike):
        erwartet = 0.006 * 80.0 * G
        assert bike.kraft_rollwiderstand(0.0, 5.0) == pytest.approx(erwartet)

    def test_luftwiderstand_waechst_quadratisch(self, bike):
        f1 = bike.kraft_luftwiderstand(5.0, 1.225)
        f2 = bike.kraft_luftwiderstand(10.0, 1.225)
        assert f2 / f1 == pytest.approx(4.0, rel=1e-6)

    def test_luftwiderstand_formel(self, bike):
        erwartet = 0.5 * 1.225 * 0.5625 * 10.0 ** 2
        assert bike.kraft_luftwiderstand(10.0, 1.225) == pytest.approx(erwartet)

    def test_rueckenwind_verringert_luftwiderstand(self, bike):
        ohne = bike.kraft_luftwiderstand(10.0, 1.225)
        mit = bike.kraft_luftwiderstand(10.0, 1.225, Wind(5.0, 180.0), 0.0)
        assert mit < ohne

    def test_drehmoment_und_motorstrom(self, bike):
        moment = bike.drehmoment(100.0)
        assert moment == pytest.approx(100.0 * bike.cfg.radradius_m)
        assert bike.motorstrom(moment) == pytest.approx(moment / 1.5)

    def test_leistung(self, bike):
        assert bike.mechanische_leistung(100.0, 5.0) == pytest.approx(500.0)

    def test_gesamtberechnung_liefert_alle_groessen(self, bike):
        werte = bike.strom_aus_fahrzustand(5.0, 0.0, 0.0, 1.2)
        assert set(werte) == {"kraft_n", "p_mech_w", "drehmoment_nm", "strom_ideal_a"}
        assert werte["kraft_n"] > 0

    def test_ungueltige_masse(self):
        with pytest.raises(ValueError):
            EBike(BikeConfig(masse_fahrer_kg=-70, masse_fahrrad_kg=0))

    def test_ungueltige_motorkonstante(self):
        with pytest.raises(ValueError):
            EBike(BikeConfig(motorkonstante_nm_per_a=0.0))
