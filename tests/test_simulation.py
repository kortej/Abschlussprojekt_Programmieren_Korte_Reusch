"""Tests fuer das Einlesen der Daten und den Ablauf der Simulation.

Es wird ein kleiner kuenstlicher Track erzeugt, damit die Tests schnell
laufen und nicht von der grossen CSV-Datei abhaengen.
"""

import numpy as np
import pandas as pd
import pytest

from ebike.battery import erzeuge_akku
from ebike.bike import EBike
from ebike.config import ProjectConfig
from ebike.data_loader import Track
from ebike.simulation import FahrtSimulator, mindestkapazitaet_abschaetzen


@pytest.fixture
def test_csv(tmp_path):
    """Erzeugt eine kleine CSV-Datei mit einer geraden Strecke nach Norden."""
    anzahl = 60
    zeit = pd.date_range("2024-08-23T16:00:00Z", periods=anzahl, freq="2s")
    daten = pd.DataFrame({
        "lat": 47.58 + np.arange(anzahl) * 0.00018,  # ca. 20 m pro Schritt
        "lon": 12.17 * np.ones(anzahl),
        "ele": 500.0 + np.arange(anzahl) * 0.5,      # gleichmaessig bergauf
        "time": zeit.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "temperature": 25.0 * np.ones(anzahl),
    })
    pfad = tmp_path / "test.csv"
    daten.to_csv(pfad, sep=";", index=False)
    return str(pfad)


@pytest.fixture
def track(test_csv):
    t = Track.aus_csv(test_csv)
    t.berechne_kinematik(glaettung_fenster=3)
    return t


class TestDatenEinlesen:
    def test_datei_wird_geladen(self, test_csv):
        t = Track.aus_csv(test_csv)
        assert len(t.daten) == 60

    def test_fehlende_datei(self):
        with pytest.raises(FileNotFoundError):
            Track.aus_csv("gibt_es_nicht.csv")

    def test_fehlende_spalten(self, tmp_path):
        pfad = tmp_path / "kaputt.csv"
        pd.DataFrame({"lat": [1.0], "lon": [2.0]}).to_csv(pfad, sep=";", index=False)
        with pytest.raises(ValueError, match="fehlen die Spalten"):
            Track.aus_csv(str(pfad))

    def test_zu_wenige_punkte(self, tmp_path):
        pfad = tmp_path / "kurz.csv"
        pd.DataFrame({
            "lat": [47.5], "lon": [12.1], "ele": [500.0],
            "time": ["2024-08-23T16:00:00.000Z"], "temperature": [20.0],
        }).to_csv(pfad, sep=";", index=False)
        with pytest.raises(ValueError):
            Track.aus_csv(str(pfad))


class TestKinematik:
    def test_alle_spalten_vorhanden(self, track):
        for spalte in ["v_ms", "a_ms2", "phi_rad", "distanz_m",
                       "richtung_grad", "himmelsrichtung", "t_s"]:
            assert spalte in track.daten.columns

    def test_distanz_ist_monoton(self, track):
        assert track.daten["distanz_m"].is_monotonic_increasing

    def test_richtung_ist_norden(self, track):
        # Die Teststrecke verlaeuft exakt nach Norden
        assert track.daten["himmelsrichtung"].mode().iloc[0] == "N"

    def test_geschwindigkeit_plausibel(self, track):
        # ca. 20 m in 2 s -> rund 10 m/s
        assert 5.0 < track.daten["v_ms"].mean() < 15.0

    def test_steigung_ist_positiv(self, track):
        assert track.daten["steigung_prozent"].mean() > 0

    def test_geschwindigkeit_wird_begrenzt(self, track):
        assert track.daten["v_ms"].max() <= 25.0

    def test_zusammenfassung_enthaelt_kennzahlen(self, track):
        z = track.zusammenfassung()
        assert z["Gesamtdistanz [km]"] > 0
        assert z["Aufstieg [m]"] > 0


class TestSimulation:
    def _simuliere(self, track, **overrides):
        cfg = ProjectConfig()
        for schluessel, wert in overrides.items():
            setattr(cfg.battery, schluessel, wert)
        akku = erzeuge_akku("lipo", cfg.battery, thermik_aktiv=True)
        simulator = FahrtSimulator(EBike(cfg.bike), akku, cfg)
        return simulator.simuliere(track.daten)

    def test_simulation_laeuft_durch(self, track):
        ergebnis = self._simuliere(track)
        assert ergebnis.vollstaendig
        assert len(ergebnis.daten) == len(track.daten)

    def test_soc_bleibt_im_gueltigen_bereich(self, track):
        ergebnis = self._simuliere(track)
        assert ergebnis.daten["soc"].min() >= 0.0
        assert ergebnis.daten["soc"].max() <= 1.0

    def test_soc_sinkt_beim_bergauffahren(self, track):
        ergebnis = self._simuliere(track)
        assert ergebnis.daten["soc"].iloc[-1] < 1.0

    def test_akku_erwaermt_sich(self, track):
        ergebnis = self._simuliere(track)
        temperaturen = ergebnis.daten["akku_temp_c"]
        assert temperaturen.iloc[-1] >= temperaturen.iloc[0]

    def test_kleiner_akku_wird_leer_und_bricht_ab(self, track):
        ergebnis = self._simuliere(track, zellkapazitaet_ah=0.02, zellen_parallel=1)
        assert not ergebnis.vollstaendig
        assert "leer" in ergebnis.abbruchgrund

    def test_kennzahlen_sind_vollstaendig(self, track):
        kennzahlen = self._simuliere(track).kennzahlen()
        for schluessel in ["Akkutyp", "Strecke gefahren [km]", "End-SoC [%]",
                           "Energieverbrauch [Wh]", "Bremswiderstand [Wh]"]:
            assert schluessel in kennzahlen

    def test_leerer_track_wirft_fehler(self, track):
        cfg = ProjectConfig()
        akku = erzeuge_akku("lipo", cfg.battery)
        simulator = FahrtSimulator(EBike(cfg.bike), akku, cfg)
        with pytest.raises(ValueError):
            simulator.simuliere(pd.DataFrame())

    def test_kapazitaetsabschaetzung_ist_positiv(self, track):
        ergebnis = self._simuliere(track)
        assert mindestkapazitaet_abschaetzen(ergebnis) > 0
