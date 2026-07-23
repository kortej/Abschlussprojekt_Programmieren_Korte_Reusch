"""Tests fuer die korrigierten Berechnungen.

Abgedeckt sind die Punkte, die in der Rueckmeldung bemaengelt wurden:

* Akkustrom und Leistung muessen physikalisch zusammenpassen
* GPS-Ausreisser duerfen keine unrealistischen Steigungen erzeugen
* die Durchschnittsgeschwindigkeit muss aus Strecke und Zeit folgen
* ein Zeitschritt darf nicht mehr Ladung entnehmen als vorhanden ist
* die Kapazitaetsschaetzung darf nicht linear hochrechnen
"""

import numpy as np
import pandas as pd
import pytest

from ebike.battery import Bremswiderstand, LiPoAkku, erzeuge_akku
from ebike.bike import EBike
from ebike.config import ProjectConfig
from ebike.data_loader import Track
from ebike.simulation import (FahrtSimulator, kleinste_konfiguration_suchen,
                              mindestkapazitaet_abschaetzen,
                              notwendige_kapazitaet)


# ---------------------------------------------------------------------------
# Hilfsdaten
# ---------------------------------------------------------------------------
def schreibe_csv(pfad, ele, anzahl=80, dlat=0.00018, sekunden=2):
    """Schreibt eine kleine Test-CSV mit vorgegebenem Hoehenprofil."""
    zeit = pd.date_range("2024-08-23T16:00:00Z", periods=anzahl, freq=f"{sekunden}s")
    pd.DataFrame({
        "lat": 47.58 + np.arange(anzahl) * dlat,
        "lon": 12.17 * np.ones(anzahl),
        "ele": ele,
        "time": zeit.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "temperature": 25.0 * np.ones(anzahl),
    }).to_csv(pfad, sep=";", index=False)
    return str(pfad)


@pytest.fixture
def akku():
    return LiPoAkku(capacity_nom_Ah=10.0, internal_resistance_mOhm=50.0,
                    initial_soc=1.0, Vmin=32.0, Vmax=42.0)


# ---------------------------------------------------------------------------
# 1) Akkustrom aus der Leistung
# ---------------------------------------------------------------------------
class TestStromAusLeistung:
    """P = (U_OC - R_i * I) * I muss exakt erfuellt sein."""

    @pytest.mark.parametrize("leistung", [0.0, 100.0, 800.0, 2000.0, -300.0])
    def test_leistung_wird_exakt_getroffen(self, akku, leistung):
        strom = akku.strom_fuer_leistung(leistung)
        assert akku.voltage(strom) * strom == pytest.approx(leistung, rel=1e-9,
                                                            abs=1e-9)

    def test_entladen_ergibt_positiven_strom(self, akku):
        assert akku.strom_fuer_leistung(500.0) > 0

    def test_laden_ergibt_negativen_strom(self, akku):
        assert akku.strom_fuer_leistung(-500.0) < 0

    def test_ueberlast_wird_auf_leistungsmaximum_begrenzt(self, akku):
        """Mehr als U_OC^2/(4*R_i) kann kein Akku liefern."""
        u_oc = akku.open_circuit_voltage()
        r_i = akku.aktueller_innenwiderstand()
        strom = akku.strom_fuer_leistung(10 * u_oc ** 2 / (4 * r_i))
        assert strom == pytest.approx(u_oc / (2 * r_i))

    def test_ohne_innenwiderstand_gilt_i_gleich_p_durch_u(self):
        akku = LiPoAkku(capacity_nom_Ah=10.0, internal_resistance_mOhm=0.0)
        assert akku.strom_fuer_leistung(420.0) == pytest.approx(
            420.0 / akku.open_circuit_voltage())

    def test_simulation_ist_energetisch_konsistent(self, tmp_path):
        """P_elektrisch muss P_mech / Wirkungsgrad entsprechen."""
        pfad = schreibe_csv(tmp_path / "t.csv", 500.0 + np.arange(80) * 0.4)
        track = Track.aus_csv(pfad)
        track.berechne_kinematik(glaettung_fenster=3)
        cfg = ProjectConfig()
        a = erzeuge_akku("lipo", cfg.battery, thermik_aktiv=False)
        ergebnis = FahrtSimulator(EBike(cfg.bike), a, cfg).simuliere(track.daten)

        d = ergebnis.daten
        antrieb = d[d["p_mech_w"] > 0]
        erwartet = antrieb["p_mech_w"] / cfg.bike.wirkungsgrad_antrieb
        assert np.allclose(antrieb["p_elektrisch_w"], erwartet, rtol=1e-6)


# ---------------------------------------------------------------------------
# 2) Plausibilisierung der Steigung
# ---------------------------------------------------------------------------
class TestSteigungsplausibilisierung:

    def test_hoehenrauschen_erzeugt_keine_extremen_steigungen(self, tmp_path):
        """Ein Hoehenausreisser darf keine Steigung von 500 % erzeugen."""
        ele = 500.0 * np.ones(80)
        ele[40] = 530.0  # 30 m Sprung zwischen zwei Punkten
        pfad = schreibe_csv(tmp_path / "t.csv", ele)
        track = Track.aus_csv(pfad)
        track.berechne_kinematik(glaettung_fenster=9, steigung_fenster_m=30.0,
                                 max_steigung_prozent=30.0)
        assert track.daten["steigung_prozent"].abs().max() <= 30.0

    def test_gleichmaessige_steigung_wird_richtig_erkannt(self, tmp_path):
        """Bei 20 m Schritt und 1 m Anstieg sind es rund 5 %."""
        ele = 500.0 + np.arange(80) * 1.0
        pfad = schreibe_csv(tmp_path / "t.csv", ele)
        track = Track.aus_csv(pfad)
        track.berechne_kinematik(glaettung_fenster=3, steigung_fenster_m=40.0)
        mitte = track.daten["steigung_prozent"].iloc[20:60]
        assert mitte.mean() == pytest.approx(5.0, abs=1.0)

    def test_stillstand_ergibt_steigung_null(self):
        """Ohne horizontale Distanz gibt es keine sinnvolle Steigung."""
        strecke = np.zeros(10)
        hoehe = np.linspace(500, 520, 10)
        phi, prozent = Track._steigung_ueber_fenster(strecke, hoehe, 30.0, 30.0)
        assert np.all(prozent == 0.0)
        assert np.all(phi == 0.0)

    def test_ungueltiges_fenster_wirft_fehler(self):
        with pytest.raises(ValueError):
            Track._steigung_ueber_fenster(np.arange(5.0), np.zeros(5), 0.0, 30.0)

    def test_beschleunigung_wird_begrenzt(self, tmp_path):
        pfad = schreibe_csv(tmp_path / "t.csv", 500.0 * np.ones(80))
        track = Track.aus_csv(pfad)
        track.berechne_kinematik(glaettung_fenster=3, max_beschleunigung_ms2=1.5)
        assert track.daten["a_ms2"].abs().max() <= 1.5


# ---------------------------------------------------------------------------
# 3) Durchschnittsgeschwindigkeit
# ---------------------------------------------------------------------------
class TestDurchschnittsgeschwindigkeit:

    def test_entspricht_strecke_durch_zeit(self, tmp_path):
        pfad = schreibe_csv(tmp_path / "t.csv", 500.0 * np.ones(80))
        track = Track.aus_csv(pfad)
        track.berechne_kinematik(glaettung_fenster=3)

        erwartet = track.gesamtdistanz_km / (track.gesamtdauer_s / 3600.0)
        assert track.durchschnittsgeschwindigkeit_kmh == pytest.approx(erwartet)
        assert track.zusammenfassung()["Durchschnittsgeschw. [km/h]"] == \
            pytest.approx(round(erwartet, 2))

    def test_bewegungsdurchschnitt_ignoriert_pausen(self, tmp_path):
        """Eine lange Pause senkt den Gesamt-, nicht den Bewegungsschnitt."""
        anzahl = 60
        zeit = list(pd.date_range("2024-01-01T00:00:00Z", periods=anzahl, freq="2s"))
        # nach der Haelfte 30 Minuten Pause ohne Ortsveraenderung
        zeit = zeit[:30] + [z + pd.Timedelta(minutes=30) for z in zeit[30:]]
        lat = 47.58 + np.concatenate([np.arange(30) * 0.00018,
                                      np.full(30, 29 * 0.00018)])
        pfad = tmp_path / "pause.csv"
        pd.DataFrame({
            "lat": lat, "lon": 12.17 * np.ones(anzahl),
            "ele": 500.0 * np.ones(anzahl),
            "time": [z.strftime("%Y-%m-%dT%H:%M:%S.000Z") for z in zeit],
            "temperature": 20.0 * np.ones(anzahl),
        }).to_csv(pfad, sep=";", index=False)

        track = Track.aus_csv(str(pfad))
        track.berechne_kinematik(glaettung_fenster=3)
        assert (track.bewegungsgeschwindigkeit_kmh()
                > track.durchschnittsgeschwindigkeit_kmh)


# ---------------------------------------------------------------------------
# 4) Teilweise ausgefuehrte Zeitschritte
# ---------------------------------------------------------------------------
class TestTeilzeitschritt:

    def test_es_wird_nicht_mehr_entnommen_als_vorhanden(self):
        akku = LiPoAkku(capacity_nom_Ah=1.0, initial_soc=1.0)  # 3600 As
        dauer = akku.apply_current(current=10.0, duration=1000.0)

        assert dauer == pytest.approx(360.0)  # 3600 As / 10 A
        assert akku.soc == pytest.approx(0.0)
        assert akku.entladene_ladung_As == pytest.approx(3600.0)

    def test_es_wird_nicht_mehr_geladen_als_hineinpasst(self):
        akku = LiPoAkku(capacity_nom_Ah=1.0, initial_soc=0.5)  # 1800 As frei
        dauer = akku.apply_current(current=-10.0, duration=1000.0)

        assert dauer == pytest.approx(180.0)
        assert akku.soc == pytest.approx(1.0)
        assert akku.geladene_ladung_As == pytest.approx(1800.0)

    def test_vollstaendiger_schritt_gibt_volle_dauer_zurueck(self):
        akku = LiPoAkku(capacity_nom_Ah=10.0, initial_soc=1.0)
        assert akku.apply_current(1.0, 10.0) == pytest.approx(10.0)

    def test_negative_dauer_wirft_fehler(self):
        with pytest.raises(ValueError):
            LiPoAkku(capacity_nom_Ah=10.0).apply_current(1.0, -1.0)

    def test_ladungszaehler_bleiben_konsistent(self):
        """Die Zaehler duerfen nie mehr als die Nennkapazitaet melden."""
        akku = LiPoAkku(capacity_nom_Ah=2.0, initial_soc=1.0)
        for _ in range(50):
            akku.apply_current(20.0, 30.0)
        assert akku.entladene_ladung_As <= akku.capacity_nom_As + 1e-6

    def test_bremswiderstand_nimmt_restenergie_auf(self):
        widerstand = Bremswiderstand()
        widerstand.nimm_energie_auf(12.5)
        assert widerstand.dissipierte_energie_wh == pytest.approx(12.5)
        assert widerstand.aktivierungen == 1
        widerstand.nimm_energie_auf(-1.0)  # negative Werte werden ignoriert
        assert widerstand.aktivierungen == 1


# ---------------------------------------------------------------------------
# 5) und 11) Kapazitaetsauslegung
# ---------------------------------------------------------------------------
class TestKapazitaetsauslegung:

    @pytest.fixture
    def track_daten(self, tmp_path):
        ele = 500.0 + np.concatenate([np.arange(40) * 1.5,
                                      60.0 - np.arange(40) * 1.5])
        pfad = schreibe_csv(tmp_path / "t.csv", ele)
        track = Track.aus_csv(pfad)
        track.berechne_kinematik(glaettung_fenster=3)
        return track.daten

    def test_bedarf_kommt_aus_dem_kumulierten_maximum(self, track_daten):
        cfg = ProjectConfig()
        a = erzeuge_akku("lipo", cfg.battery, thermik_aktiv=False)
        ergebnis = FahrtSimulator(EBike(cfg.bike), a, cfg).simuliere(track_daten)

        assert ergebnis.max_ladungsbedarf_ah == pytest.approx(
            ergebnis.daten["ladung_kumuliert_ah"].max())
        assert mindestkapazitaet_abschaetzen(ergebnis, reserve=0.0) == \
            pytest.approx(ergebnis.max_ladungsbedarf_ah, abs=0.01)

    def test_reserve_erhoeht_die_empfehlung(self, track_daten):
        cfg = ProjectConfig()
        a = erzeuge_akku("lipo", cfg.battery, thermik_aktiv=False)
        ergebnis = FahrtSimulator(EBike(cfg.bike), a, cfg).simuliere(track_daten)
        assert (mindestkapazitaet_abschaetzen(ergebnis, 0.15)
                > mindestkapazitaet_abschaetzen(ergebnis, 0.0))

    def test_ungueltige_reserve_wirft_fehler(self, track_daten):
        cfg = ProjectConfig()
        a = erzeuge_akku("lipo", cfg.battery, thermik_aktiv=False)
        ergebnis = FahrtSimulator(EBike(cfg.bike), a, cfg).simuliere(track_daten)
        with pytest.raises(ValueError):
            mindestkapazitaet_abschaetzen(ergebnis, reserve=1.0)

    def test_virtueller_akku_wird_nicht_leer(self, track_daten):
        """Die Auslegung darf nicht an einem leeren Akku scheitern."""
        cfg = ProjectConfig()
        cfg.battery.zellen_parallel = 1  # winziger Basisakku
        bedarf = notwendige_kapazitaet(track_daten, cfg,
                                       virtuelle_kapazitaet_ah=200.0)
        assert bedarf["vollstaendig"] is True
        assert bedarf["netto_ladung_ah"] > 0
        assert bedarf["empfohlene_kapazitaet_ah"] > bedarf["netto_ladung_ah"]

    def test_ergebnis_ist_unabhaengig_vom_basisakku(self, track_daten):
        """Frueher lieferte ein zu kleiner Akku eine voellig andere Empfehlung."""
        klein = ProjectConfig()
        klein.battery.zellen_parallel = 1
        gross = ProjectConfig()
        gross.battery.zellen_parallel = 20

        a = notwendige_kapazitaet(track_daten, klein)["empfohlene_kapazitaet_ah"]
        b = notwendige_kapazitaet(track_daten, gross)["empfohlene_kapazitaet_ah"]
        assert a == pytest.approx(b, rel=0.02)

    def test_kleinste_konfiguration_reicht_gerade_aus(self, track_daten):
        cfg = ProjectConfig()
        gefunden = kleinste_konfiguration_suchen(track_daten, cfg, reserve=0.15,
                                                 max_parallel=30)
        assert gefunden["gefunden"] is True
        assert gefunden["end_soc_prozent"] >= 15.0
        assert gefunden["zellen_parallel"] >= 1
