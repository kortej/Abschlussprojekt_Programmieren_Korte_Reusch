"""Tests fuer das Akkumodell.

Der erste Test prueft direkt den in der OOP-Uebung angegebenen Testfall.
"""

import pytest

from ebike.battery import (BatteryPack, Bremswiderstand, LiPoAkku, NmcAkku,
                           ThermischesModell, erzeuge_akku)
from ebike.config import BatteryConfig


class TestBatteryPackGrundmodell:
    def test_testfall_aus_der_uebung(self):
        """Referenzfall aus der OOP-Uebung (battery_simulator.py).

        Akku: 10 Ah, Start-SoC 0.7, 32 V bis 42 V.
        Lastprofil: Stroeme [3, 11, 4, -1.5, 1] A mit den Dauern
        [300, 240, 90, 150, 120] s. Erwartete Ausgabe laut Angabe:
        BatteryPack(SoC=59.5%, V=37.95 V).
        """
        akku = BatteryPack(capacity_nom_Ah=10.0, internal_resistance_mOhm=80.0,
                           initial_soc=0.7, Vmin=32.0, Vmax=42.0)
        stroeme = [3.0, 11.0, 4.0, -1.5, 1.0]
        dauern = [300.0, 240.0, 90.0, 150.0, 120.0]
        for strom, dauer in zip(stroeme, dauern):
            akku.apply_current(strom, dauer)
        assert akku.soc == pytest.approx(0.595, abs=1e-3)
        assert akku.voltage() == pytest.approx(37.95, abs=0.01)

    def test_soc_wird_bei_null_begrenzt(self):
        akku = BatteryPack(10.0, initial_soc=0.01)
        akku.apply_current(100.0, 3600.0)
        assert akku.soc == 0.0
        assert akku.is_empty()

    def test_soc_wird_bei_eins_begrenzt(self):
        akku = BatteryPack(10.0, initial_soc=0.99)
        akku.apply_current(-100.0, 3600.0)
        assert akku.soc == 1.0
        assert akku.is_full()

    def test_spannung_faellt_unter_last(self):
        akku = BatteryPack(10.0, internal_resistance_mOhm=100.0, initial_soc=0.5)
        assert akku.voltage(10.0) < akku.voltage(0.0)

    def test_lineare_kennlinie(self):
        akku = BatteryPack(10.0, initial_soc=0.5, Vmin=32.0, Vmax=42.0)
        assert akku.open_circuit_voltage() == pytest.approx(37.0)

    @pytest.mark.parametrize("kapazitaet", [0, -5])
    def test_ungueltige_kapazitaet(self, kapazitaet):
        with pytest.raises(ValueError):
            BatteryPack(kapazitaet)

    def test_ungueltiger_start_soc(self):
        with pytest.raises(ValueError):
            BatteryPack(10.0, initial_soc=1.5)

    def test_negative_dauer(self):
        akku = BatteryPack(10.0)
        with pytest.raises(ValueError):
            akku.apply_current(1.0, -10.0)


class TestKennlinienAkkus:
    def test_lipo_endpunkte(self):
        akku = LiPoAkku(10.0)
        assert akku.open_circuit_voltage(0.0) == pytest.approx(32.0)
        assert akku.open_circuit_voltage(1.0) == pytest.approx(42.0)

    def test_nmc_endpunkte(self):
        akku = NmcAkku(10.0)
        assert akku.open_circuit_voltage(0.0) == pytest.approx(32.0)
        assert akku.open_circuit_voltage(1.0) == pytest.approx(42.0)

    def test_lipo_hat_bei_mittlerem_soc_hoehere_spannung_als_nmc(self):
        """Die LiPo-Kennlinie liegt im mittleren Bereich deutlich hoeher."""
        lipo, nmc = LiPoAkku(10.0), NmcAkku(10.0)
        assert lipo.open_circuit_voltage(0.5) > nmc.open_circuit_voltage(0.5)

    def test_kennlinie_ist_monoton_steigend(self):
        akku = LiPoAkku(10.0)
        werte = [akku.open_circuit_voltage(s / 100) for s in range(101)]
        assert all(b >= a for a, b in zip(werte, werte[1:]))

    def test_soc_ausserhalb_wird_begrenzt(self):
        akku = NmcAkku(10.0)
        assert akku.open_circuit_voltage(-0.5) == pytest.approx(32.0)
        assert akku.open_circuit_voltage(2.0) == pytest.approx(42.0)


class TestFactory:
    def test_erzeugt_richtigen_typ(self):
        cfg = BatteryConfig()
        assert isinstance(erzeuge_akku("lipo", cfg), LiPoAkku)
        assert isinstance(erzeuge_akku("NMC", cfg), NmcAkku)

    def test_kapazitaet_skaliert_mit_parallelzellen(self):
        cfg = BatteryConfig(zellkapazitaet_ah=3.5, zellen_parallel=4)
        akku = erzeuge_akku("lipo", cfg)
        assert akku.capacity_nom_Ah == pytest.approx(14.0)

    def test_innenwiderstand_des_packs(self):
        # 8 mOhm * 10 seriell / 4 parallel = 20 mOhm
        cfg = BatteryConfig(zellen_seriell=10, zellen_parallel=4)
        akku = erzeuge_akku("lipo", cfg, thermik_aktiv=False)
        assert akku.internal_resistance == pytest.approx(0.020)

    def test_unbekannter_typ(self):
        with pytest.raises(ValueError):
            erzeuge_akku("bleiakku", BatteryConfig())


class TestThermischesModell:
    def test_erwaermung_durch_verluste(self):
        modell = ThermischesModell(starttemperatur_c=20.0,
                                   waermekapazitaet_j_per_k=1000.0,
                                   waermeuebergang_w_per_k=0.0)
        modell.update(verlustleistung_w=100.0, umgebungstemperatur_c=20.0,
                      dauer_s=10.0)
        assert modell.temperatur_c == pytest.approx(21.0)

    def test_abkuehlung_zur_umgebung(self):
        modell = ThermischesModell(starttemperatur_c=40.0,
                                   waermekapazitaet_j_per_k=1000.0,
                                   waermeuebergang_w_per_k=10.0)
        modell.update(0.0, umgebungstemperatur_c=20.0, dauer_s=10.0)
        assert modell.temperatur_c < 40.0

    def test_kalter_akku_hat_hoeheren_innenwiderstand(self):
        kalt = ThermischesModell(starttemperatur_c=0.0)
        akku = BatteryPack(10.0, internal_resistance_mOhm=20.0,
                           thermisches_modell=kalt,
                           temperaturkoeffizient_ri=0.01,
                           referenztemperatur_c=25.0)
        assert akku.aktueller_innenwiderstand() > 0.020

    def test_ungueltige_waermekapazitaet(self):
        with pytest.raises(ValueError):
            ThermischesModell(waermekapazitaet_j_per_k=0.0)


class TestBremswiderstand:
    def test_entladestrom_bleibt_unveraendert(self):
        akku = BatteryPack(10.0, initial_soc=0.5)
        bw = Bremswiderstand(max_ladestrom_a=10.0)
        assert bw.begrenze_ladestrom(5.0, akku, 38.0, 10.0) == 5.0
        assert bw.dissipierte_energie_wh == 0.0

    def test_voller_akku_nimmt_nichts_auf(self):
        akku = BatteryPack(10.0, initial_soc=1.0)
        bw = Bremswiderstand(max_ladestrom_a=10.0)
        strom = bw.begrenze_ladestrom(-5.0, akku, 42.0, 10.0)
        assert strom == 0.0
        assert bw.dissipierte_energie_wh > 0.0
        assert bw.aktivierungen == 1

    def test_ladestrom_wird_begrenzt(self):
        akku = BatteryPack(10.0, initial_soc=0.5)
        bw = Bremswiderstand(max_ladestrom_a=10.0)
        strom = bw.begrenze_ladestrom(-25.0, akku, 38.0, 10.0)
        assert strom == pytest.approx(-10.0)
        # 15 A * 38 V * 10 s = 1583 Ws = 0.44 Wh
        assert bw.dissipierte_energie_wh == pytest.approx(15 * 38 * 10 / 3600, rel=1e-6)
