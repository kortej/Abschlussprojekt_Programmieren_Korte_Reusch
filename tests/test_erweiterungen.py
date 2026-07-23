"""Tests der Erweiterungsmodule.

Bisher waren `weather`, `geocoding`, `mapping`, `plotting`, `parameter_study`
und `report` nicht getestet. Die HTTP-Zugriffe werden hier durch gemockte
Antworten ersetzt, damit die Tests offline und ohne Rate-Limit laufen.
"""

import json
import pathlib
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
import requests

from ebike.battery import erzeuge_akku
from ebike.bike import EBike
from ebike.config import ProjectConfig
from ebike.data_loader import Track
from ebike.geocoding import GeocodingService
from ebike.mapping import StreckenKarte
from ebike.parameter_study import Parameterstudie
from ebike.plotting import ErgebnisPlotter
from ebike.report import LatexReport, latex_escape
from ebike.results_export import (aktualisiere_readme, als_markdown,
                                  sammle_ergebnisse, speichere_json)
from ebike.simulation import FahrtSimulator
from ebike.weather import WetterService


# ---------------------------------------------------------------------------
# Hilfsmittel
# ---------------------------------------------------------------------------
class GemockteAntwort:
    """Ersetzt ein `requests.Response`-Objekt."""

    def __init__(self, nutzdaten, statuscode=200):
        self._nutzdaten = nutzdaten
        self.status_code = statuscode

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._nutzdaten, Exception):
            raise self._nutzdaten
        return self._nutzdaten


WETTER_ANTWORT = {
    "hourly": {
        "time": ["2024-08-23T16:00", "2024-08-23T17:00", "2024-08-23T18:00"],
        "temperature_2m": [25.0, 24.0, 23.0],
        "wind_speed_10m": [18.0, 12.0, 9.0],
        "wind_direction_10m": [270.0, 250.0, 230.0],
        "surface_pressure": [960.0, 960.5, 961.0],
        "relative_humidity_2m": [45.0, 50.0, 55.0],
    }
}

START = datetime(2024, 8, 23, 16, 0)
ENDE = datetime(2024, 8, 23, 18, 0)


@pytest.fixture
def track(tmp_path):
    """Kleiner kuenstlicher Track mit Anstieg und Abfahrt."""
    anzahl = 80
    zeit = pd.date_range("2024-08-23T16:00:00Z", periods=anzahl, freq="2s")
    ele = 500.0 + np.concatenate([np.arange(40) * 1.2, 48.0 - np.arange(40) * 1.2])
    pfad = tmp_path / "track.csv"
    pd.DataFrame({
        "lat": 47.58 + np.arange(anzahl) * 0.00018,
        "lon": 12.17 + np.arange(anzahl) * 0.00005,
        "ele": ele,
        "time": zeit.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "temperature": 25.0 * np.ones(anzahl),
    }).to_csv(pfad, sep=";", index=False)
    t = Track.aus_csv(str(pfad))
    t.berechne_kinematik(glaettung_fenster=3)
    return t


@pytest.fixture
def ergebnis(track):
    cfg = ProjectConfig()
    akku = erzeuge_akku("lipo", cfg.battery, thermik_aktiv=True)
    return FahrtSimulator(EBike(cfg.bike), akku, cfg).simuliere(track.daten)


# ---------------------------------------------------------------------------
# Wetterdaten
# ---------------------------------------------------------------------------
class TestWetterService:

    def test_erfolgreiche_abfrage(self, tmp_path, monkeypatch):
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort(WETTER_ANTWORT))
        dienst = WetterService(cache_datei=str(tmp_path / "cache.json"), sdk_verwenden=False)
        daten = dienst.hole_daten(47.58, 12.17, START, ENDE)

        assert daten is not None and len(daten) == 3
        assert dienst.echte_api_daten is True
        assert dienst.zusammenfassung()["Echte API-Daten"] == "ja"

    def test_fehlerhafte_abfrage_faellt_offline_zurueck(self, tmp_path, monkeypatch):
        """Bei HTTP 403 muss die Simulation trotzdem weiterlaufen koennen."""
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort({}, statuscode=403))
        dienst = WetterService(cache_datei=str(tmp_path / "cache.json"), sdk_verwenden=False)

        assert dienst.hole_daten(47.58, 12.17, START, ENDE) is None
        assert dienst.echte_api_daten is False
        assert "offline" in dienst.quelle
        # Ohne Daten wird Windstille angenommen
        assert dienst.wind_zum_zeitpunkt(pd.Timestamp("2024-08-23T16:30:00Z")
                                         ).geschwindigkeit_ms == 0.0

    def test_unvollstaendige_antwort_wird_nicht_gecacht(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache.json"
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort({"hourly": {"time": []}}))
        dienst = WetterService(cache_datei=str(cache), sdk_verwenden=False)

        assert dienst.hole_daten(47.58, 12.17, START, ENDE) is None
        assert not cache.exists()

    def test_passender_cache_wird_verwendet(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache.json"
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort(WETTER_ANTWORT))
        WetterService(cache_datei=str(cache),
                      sdk_verwenden=False).hole_daten(47.58, 12.17, START, ENDE)

        def keine_abfrage(*a, **k):
            raise AssertionError("Der Cache haette verwendet werden muessen.")

        monkeypatch.setattr(requests, "get", keine_abfrage)
        zweiter = WetterService(cache_datei=str(cache), sdk_verwenden=False)
        assert zweiter.hole_daten(47.58, 12.17, START, ENDE) is not None
        assert zweiter.quelle.startswith("Cache")

    def test_cache_anderer_strecke_wird_verworfen(self, tmp_path, monkeypatch):
        """Sonst wuerden fuer eine andere Route alte Wetterdaten gelten."""
        cache = tmp_path / "cache.json"
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort(WETTER_ANTWORT))
        WetterService(cache_datei=str(cache),
                      sdk_verwenden=False).hole_daten(47.58, 12.17, START, ENDE)

        aufrufe = []

        def zaehlend(*a, **k):
            aufrufe.append(k.get("params"))
            return GemockteAntwort(WETTER_ANTWORT)

        monkeypatch.setattr(requests, "get", zaehlend)
        zweiter = WetterService(cache_datei=str(cache), sdk_verwenden=False)
        zweiter.hole_daten(52.52, 13.40, START, ENDE)  # Berlin statt Tirol
        assert len(aufrufe) == 1, "Die API haette neu abgefragt werden muessen."

    def test_cache_anderen_datums_wird_verworfen(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache.json"
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort(WETTER_ANTWORT))
        WetterService(cache_datei=str(cache),
                      sdk_verwenden=False).hole_daten(47.58, 12.17, START, ENDE)

        aufrufe = []
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: (aufrufe.append(1),
                                             GemockteAntwort(WETTER_ANTWORT))[1])
        zweiter = WetterService(cache_datei=str(cache), sdk_verwenden=False)
        zweiter.hole_daten(47.58, 12.17, datetime(2025, 1, 1), datetime(2025, 1, 1))
        assert len(aufrufe) == 1

    def test_cache_ohne_metadaten_wird_verworfen(self, tmp_path):
        """Alte Cache-Dateien im frueheren Format duerfen nicht gelten."""
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps(WETTER_ANTWORT), encoding="utf-8")
        dienst = WetterService(cache_datei=str(cache), sdk_verwenden=False)
        assert dienst._lade_cache(dienst.metadaten(47.58, 12.17, START, ENDE)) is None

    def test_antwort_gueltig(self):
        assert WetterService.antwort_gueltig(WETTER_ANTWORT) is True
        assert WetterService.antwort_gueltig({"hourly": {}}) is False
        assert WetterService.antwort_gueltig("kein dict") is False

    def test_windwerte_werden_umgerechnet(self, tmp_path, monkeypatch):
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort(WETTER_ANTWORT))
        dienst = WetterService(cache_datei=str(tmp_path / "c.json"), sdk_verwenden=False)
        dienst.hole_daten(47.58, 12.17, START, ENDE)
        wind = dienst.wind_zum_zeitpunkt(pd.Timestamp("2024-08-23T16:05:00Z"))
        assert wind.geschwindigkeit_ms == pytest.approx(18.0 / 3.6)
        assert dienst.luftfeuchte_zum_zeitpunkt(
            pd.Timestamp("2024-08-23T16:05:00Z")) == pytest.approx(0.45)


# ---------------------------------------------------------------------------
# Reverse Geocoding
# ---------------------------------------------------------------------------
class TestGeocodingService:

    def test_ort_wird_aufgeloest(self, tmp_path, monkeypatch):
        antwort = {"address": {"village": "Ellmau"}, "display_name": "Ellmau, Tirol"}
        monkeypatch.setattr(requests, "get", lambda *a, **k: GemockteAntwort(antwort))
        dienst = GeocodingService(cache_datei=str(tmp_path / "geo.json"), pause_s=0.0)

        assert dienst.ort(47.51, 12.30) == "Ellmau"
        assert dienst.api_aufrufe == 1

    def test_zweite_abfrage_kommt_aus_dem_cache(self, tmp_path, monkeypatch):
        antwort = {"address": {"town": "Kufstein"}}
        monkeypatch.setattr(requests, "get", lambda *a, **k: GemockteAntwort(antwort))
        dienst = GeocodingService(cache_datei=str(tmp_path / "geo.json"), pause_s=0.0)
        dienst.ort(47.58, 12.17)
        dienst.ort(47.58, 12.17)
        assert dienst.api_aufrufe == 1

    def test_fehler_liefert_koordinaten_als_platzhalter(self, tmp_path, monkeypatch):
        """Bei HTTP 403 darf das Programm nicht abstuerzen."""
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort({}, statuscode=403))
        dienst = GeocodingService(cache_datei=str(tmp_path / "geo.json"), pause_s=0.0)

        assert dienst.ort(47.58, 12.17) == "47.580, 12.170"
        assert dienst.fehlversuche == 1
        assert dienst.erfolgreich is False

    def test_wegpunkte_entlang_der_strecke(self, track, tmp_path, monkeypatch):
        antwort = {"address": {"city": "Woergl"}}
        monkeypatch.setattr(requests, "get", lambda *a, **k: GemockteAntwort(antwort))
        dienst = GeocodingService(cache_datei=str(tmp_path / "geo.json"), pause_s=0.0)

        punkte = dienst.orte_entlang_strecke(track.daten, anzahl=4)
        assert len(punkte) == 4
        assert all({"lat", "lon", "ort", "distanz_km"} <= set(p) for p in punkte)
        assert punkte[0]["distanz_km"] <= punkte[-1]["distanz_km"]

    def test_zu_wenige_wegpunkte_wirft_fehler(self, track, tmp_path):
        dienst = GeocodingService(cache_datei=str(tmp_path / "geo.json"))
        with pytest.raises(ValueError):
            dienst.orte_entlang_strecke(track.daten, anzahl=1)

    def test_kurzname_faellt_auf_display_name_zurueck(self):
        assert GeocodingService._kurzname({"display_name": "Soell, Tirol"}) == "Soell"


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------
class TestPlotting:

    def test_alle_plotdateien_werden_erzeugt(self, ergebnis, tmp_path):
        plotter = ErgebnisPlotter(ergebnis, str(tmp_path))
        akku = erzeuge_akku("nmc", ProjectConfig().battery, thermik_aktiv=False)
        wegpunkte = [{"ort": "A", "distanz_km": 0.0},
                     {"ort": "B", "distanz_km": 1.0}]

        pfade = plotter.alle(akkus=[ergebnis.akku, akku], wegpunkte=wegpunkte)
        assert len(pfade) == 7
        for pfad in pfade:
            assert (tmp_path / pfad.split("/")[-1]).exists()

    def test_akkuvergleich_wird_erzeugt(self, ergebnis, tmp_path):
        plotter = ErgebnisPlotter(ergebnis, str(tmp_path))
        pfad = plotter.akkuvergleich({"LiPo": ergebnis})
        assert (tmp_path / "08_akkuvergleich.png").exists()
        assert pfad.endswith("08_akkuvergleich.png")


# ---------------------------------------------------------------------------
# Karte
# ---------------------------------------------------------------------------
class TestStreckenKarte:

    def test_html_karte_wird_erzeugt(self, ergebnis, tmp_path):
        karte = StreckenKarte(ergebnis.daten, str(tmp_path))
        pfad = karte.erzeuge(wegpunkte=[
            {"lat": 47.58, "lon": 12.17, "ort": "Start", "distanz_km": 0.0},
            {"lat": 47.585, "lon": 12.172, "ort": "Mitte", "distanz_km": 0.5},
            {"lat": 47.59, "lon": 12.175, "ort": "Ziel", "distanz_km": 1.0}])

        inhalt = open(pfad, encoding="utf-8").read()
        assert pfad.endswith("strecke.html")
        assert "leaflet" in inhalt.lower()
        assert "Mitte" in inhalt

    def test_leere_daten_werfen_fehler(self):
        with pytest.raises(ValueError):
            StreckenKarte(pd.DataFrame(), "output")

    def test_unbekannte_farbgroesse_wirft_fehler(self, ergebnis, tmp_path):
        karte = StreckenKarte(ergebnis.daten, str(tmp_path))
        with pytest.raises(ValueError):
            karte.erzeuge(farbgroesse="gibtsnicht")


# ---------------------------------------------------------------------------
# Parameterstudie
# ---------------------------------------------------------------------------
class TestParameterstudie:

    def test_parameter_wird_tatsaechlich_veraendert(self, track, tmp_path):
        """Die Studie muss unterschiedliche Ergebnisse liefern."""
        studie = Parameterstudie(track.daten, ProjectConfig(),
                                 ausgabeordner=str(tmp_path))
        tabelle = studie.variiere("bike", "masse_fahrer_kg", [50, 120],
                                  "Masse [kg]")

        assert list(tabelle["Masse [kg]"]) == [50, 120]
        assert tabelle["Verbrauch [Wh]"].iloc[1] > tabelle["Verbrauch [Wh]"].iloc[0]

    def test_unbekanntes_attribut_wirft_fehler(self, track, tmp_path):
        studie = Parameterstudie(track.daten, ProjectConfig(),
                                 ausgabeordner=str(tmp_path))
        with pytest.raises(AttributeError):
            studie.variiere("bike", "gibtsnicht", [1, 2])

    def test_plot_und_csv_werden_erzeugt(self, track, tmp_path):
        studie = Parameterstudie(track.daten, ProjectConfig(),
                                 ausgabeordner=str(tmp_path))
        studien = {"Masse": studie.variiere("bike", "masse_fahrer_kg", [70, 90],
                                            "Masse [kg]")}
        plot = studie.plotte(studien)
        csv = studie.speichere_csv(studien)

        assert (tmp_path / "09_parameterstudie.png").exists()
        gelesen = pd.read_csv(csv, sep=";")
        assert list(gelesen["Studie"]) == ["Masse", "Masse"]
        assert plot.endswith(".png")

    def test_ergebnis_enthaelt_distanz_und_mindestkapazitaet(self, track, tmp_path):
        """Bei abgebrochenen Fahrten sind diese Groessen entscheidend."""
        studie = Parameterstudie(track.daten, ProjectConfig(),
                                 ausgabeordner=str(tmp_path))
        tabelle = studie.variiere("battery", "zellen_parallel", [4], "Zellen")
        for spalte in ("Distanz [km]", "Vollstaendig", "Min. Kapazitaet [Ah]"):
            assert spalte in tabelle.columns


# ---------------------------------------------------------------------------
# LaTeX-Bericht
# ---------------------------------------------------------------------------
class TestLatexReport:

    def test_erwartete_abschnitte_stehen_in_der_tex_datei(self, tmp_path):
        report = LatexReport(str(tmp_path))
        report.abschnitt("Kenngroessen der Fahrt", "Einleitender Text.")
        report.kennzahlentabelle({"Distanz [km]": 12.3, "Leer": None},
                                 "Auswertung")
        pfad = report.speichere()

        inhalt = open(pfad, encoding="utf-8").read()
        assert r"\section{Kenngroessen der Fahrt}" in inhalt
        assert r"\begin{document}" in inhalt and r"\end{document}" in inhalt
        assert "Distanz [km]" in inhalt
        assert "Leer" not in inhalt  # None-Werte werden weggelassen

    def test_breite_tabelle_wird_skaliert_und_gedreht(self, tmp_path):
        """Sonst laufen die Spalten rechts aus der Seite (Overfull hbox)."""
        tabelle = pd.DataFrame({f"Sehr lange Spaltenueberschrift {i}": [i]
                                for i in range(9)})
        report = LatexReport(str(tmp_path))
        report.dataframe(tabelle, "Parameterstudie")
        inhalt = open(report.speichere(), encoding="utf-8").read()

        assert r"\resizebox{\textwidth}" in inhalt
        assert r"\begin{landscape}" in inhalt

    def test_schmale_tabelle_bleibt_im_hochformat(self, tmp_path):
        report = LatexReport(str(tmp_path))
        report.dataframe(pd.DataFrame({"A": [1], "B": [2]}), "Klein")
        inhalt = open(report.speichere(), encoding="utf-8").read()
        assert r"\begin{landscape}" not in inhalt

    def test_lange_ueberschriften_werden_gekuerzt(self):
        kurz = LatexReport._kopfzeile("A" * 40, max_laenge=10)
        assert len(kurz) < 40 and kurz.endswith("}")

    def test_fehlendes_bild_wird_uebersprungen(self, tmp_path):
        report = LatexReport(str(tmp_path))
        report.bild(str(tmp_path / "gibtsnicht.png"), "Test")
        assert r"\includegraphics" not in open(report.speichere(),
                                               encoding="utf-8").read()

    def test_sonderzeichen_werden_maskiert(self):
        assert latex_escape("100 % & 5_3") == r"100 \% \& 5\_3"

    def test_overfull_pruefung(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text("Overfull \\hbox (12.0pt too wide)\n"
                       "Overfull \\hbox (3.0pt too wide)\n", encoding="utf-8")
        assert LatexReport.pruefe_log(str(log)) == 2

        sauber = tmp_path / "sauber.log"
        sauber.write_text("alles gut", encoding="utf-8")
        assert LatexReport.pruefe_log(str(sauber)) == 0
        assert LatexReport.pruefe_log(str(tmp_path / "fehlt.log")) == 0


# ---------------------------------------------------------------------------
# Ergebnisexport / README
# ---------------------------------------------------------------------------
class TestErgebnisexport:

    def test_json_wird_geschrieben(self, track, ergebnis, tmp_path):
        daten = sammle_ergebnisse(track, {"LiPo": ergebnis},
                                  {"Wetterquelle": "Test"},
                                  {"empfohlene_kapazitaet_ah": 22.75})
        pfad = speichere_json(daten, str(tmp_path))
        gelesen = json.load(open(pfad, encoding="utf-8"))

        assert gelesen["fahrt"]["Gesamtdistanz [km]"] > 0
        assert "LiPo" in gelesen["akkus"]
        assert gelesen["kapazitaet"]["empfohlene_kapazitaet_ah"] == 22.75

    def test_readme_wird_zwischen_den_marken_ersetzt(self, track, ergebnis, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# Titel\n\n<!-- ERGEBNISSE:START -->\nalt\n"
                          "<!-- ERGEBNISSE:ENDE -->\n\nSchluss\n", encoding="utf-8")
        daten = sammle_ergebnisse(track, {"LiPo": ergebnis}, {})

        assert aktualisiere_readme(daten, str(readme)) is True
        inhalt = readme.read_text(encoding="utf-8")
        assert "alt" not in inhalt
        assert "# Titel" in inhalt and "Schluss" in inhalt
        assert "Gesamtdistanz [km]" in inhalt

    def test_readme_ohne_marken_bleibt_unveraendert(self, track, ergebnis, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# Ohne Marken\n", encoding="utf-8")
        daten = sammle_ergebnisse(track, {"LiPo": ergebnis}, {})

        assert aktualisiere_readme(daten, str(readme)) is False
        assert readme.read_text(encoding="utf-8") == "# Ohne Marken\n"

    def test_fehlendes_readme_wird_gemeldet(self, track, ergebnis, tmp_path):
        daten = sammle_ergebnisse(track, {"LiPo": ergebnis}, {})
        assert aktualisiere_readme(daten, str(tmp_path / "fehlt.md")) is False

    def test_markdown_enthaelt_alle_abschnitte(self, track, ergebnis):
        daten = sammle_ergebnisse(track, {"LiPo": ergebnis}, {"Wetterquelle": "X"},
                                  {"empfohlene_kapazitaet_ah": 20.0},
                                  {"zellen_parallel": 7})
        text = als_markdown(daten)
        for ueberschrift in ("Kenngroessen der Fahrt", "Simulation mit LiPo-Akku",
                             "Notwendige Akkukapazitaet",
                             "Kleinste ausreichende Konfiguration", "Wetter"):
            assert ueberschrift in text


class TestFahrtbericht:
    """Der zusammengebaute Bericht muss alle Abschnitte enthalten."""

    def test_bericht_enthaelt_alle_abschnitte(self, track, ergebnis, tmp_path,
                                              monkeypatch):
        import ebike.report as report_modul

        # pdflatex wird hier nicht benoetigt - nur der Quelltext wird geprueft
        monkeypatch.setattr(report_modul.shutil, "which", lambda _: None)

        studie = pd.DataFrame({"Masse [kg]": [70, 90], "Verbrauch [Wh]": [1.0, 2.0]})
        pdf = report_modul.erstelle_fahrtbericht(
            track, {"LiPo": ergebnis}, plots=[], studien={"Masse": studie},
            studienplot=None,
            wetter={"Wetterquelle": "Standardwerte (offline)",
                    "Echte API-Daten": "nein"},
            wegpunkte=[{"ort": "Ellmau"}, {"ort": "Soell"}],
            kartenpfad=str(tmp_path / "strecke.html"),
            ausgabeordner=str(tmp_path),
            kapazitaet={"empfohlene_kapazitaet_ah": 22.75, "zellen_parallel": 7})

        assert pdf is None  # ohne pdflatex nur die .tex-Datei
        inhalt = (tmp_path / "fahrtbericht.tex").read_text(encoding="utf-8")
        for abschnitt in ("Einleitung", "Kenngroessen der Fahrt",
                          "Auslegung der Akkukapazitaet",
                          "Ergebnisse der Simulation", "Grafische Auswertung",
                          "Parameterstudien", "Zusammenfassung"):
            assert f"\\section{{{abschnitt}}}" in inhalt
        # Offline-Wetter muss deutlich gekennzeichnet sein
        assert "Wetter-API war bei diesem Lauf nicht" in inhalt
        assert "Ellmau" in inhalt and "22.75" in inhalt

    def test_abbruchgrund_wird_ausgewiesen(self, track, tmp_path, monkeypatch):
        import ebike.report as report_modul
        monkeypatch.setattr(report_modul.shutil, "which", lambda _: None)

        cfg = ProjectConfig()
        cfg.battery.zellen_parallel = 1  # viel zu klein -> Abbruch
        akku = erzeuge_akku("lipo", cfg.battery, thermik_aktiv=False)
        leer = FahrtSimulator(EBike(cfg.bike), akku, cfg).simuliere(track.daten)

        report_modul.erstelle_fahrtbericht(
            track, {"LiPo": leer}, [], {}, None, {}, [], None, str(tmp_path))
        inhalt = (tmp_path / "fahrtbericht.tex").read_text(encoding="utf-8")
        assert (r"\textbf{Hinweis:}" in inhalt) == (not leer.vollstaendig)

    def test_ohne_pdflatex_bleibt_die_tex_datei(self, tmp_path, monkeypatch):
        import ebike.report as report_modul
        monkeypatch.setattr(report_modul.shutil, "which", lambda _: None)

        bericht = LatexReport(str(tmp_path))
        bericht.abschnitt("Test")
        assert bericht.kompiliere() is None
        assert (tmp_path / "fahrtbericht.tex").exists()

    def test_fehlender_pdflatex_aufruf_wird_abgefangen(self, tmp_path, monkeypatch):
        import ebike.report as report_modul
        monkeypatch.setattr(report_modul.shutil, "which", lambda _: "/usr/bin/pdflatex")

        def wirft(*a, **k):
            raise OSError("pdflatex nicht ausfuehrbar")

        monkeypatch.setattr(report_modul.subprocess, "run", wirft)
        bericht = LatexReport(str(tmp_path))
        bericht.abschnitt("Test")
        assert bericht.kompiliere() is None


class TestEndpunktwahl:
    """Open-Meteo bietet zwei Endpunkte - es muss der passende gewaehlt werden."""

    def test_junge_fahrt_nutzt_forecast_api(self):
        from ebike.weather import FORECAST_API_URL, WetterService
        heute = datetime(2026, 7, 20)
        reihenfolge = WetterService.endpunkte_fuer(datetime(2026, 7, 1), heute)
        assert reihenfolge[0] == ("Forecast-API", FORECAST_API_URL)

    def test_alte_fahrt_nutzt_archiv_api(self):
        from ebike.weather import ARCHIV_API_URL, WetterService
        heute = datetime(2026, 7, 20)
        # Die aufgezeichnete Fahrt vom 23.08.2024 liegt weit ausserhalb der
        # 92 Tage, die die Forecast-API abdeckt
        reihenfolge = WetterService.endpunkte_fuer(datetime(2024, 8, 23), heute)
        assert reihenfolge[0] == ("Archiv-API", ARCHIV_API_URL)

    def test_grenze_liegt_innerhalb_der_92_tage(self):
        from ebike.weather import MAX_RUECKBLICK_TAGE_FORECAST
        assert MAX_RUECKBLICK_TAGE_FORECAST <= 92

    def test_beide_endpunkte_bleiben_als_ausweichweg(self):
        from ebike.weather import WetterService
        for datum in (datetime(2026, 7, 1), datetime(2024, 8, 23)):
            assert len(WetterService.endpunkte_fuer(datum, datetime(2026, 7, 20))) == 2

    def test_archiv_wird_versucht_wenn_forecast_scheitert(self, tmp_path, monkeypatch):
        """Eine junge Fahrt darf nicht offline enden, nur weil ein Endpunkt streikt."""
        from ebike.weather import ARCHIV_API_URL, WetterService

        aufgerufen = []

        def gefakete_abfrage(url, params=None, timeout=None):
            aufgerufen.append(url)
            if url != ARCHIV_API_URL:
                raise requests.RequestException("403 Client Error: Forbidden")
            return GemockteAntwort(WETTER_ANTWORT)

        monkeypatch.setattr(requests, "get", gefakete_abfrage)
        dienst = WetterService(cache_datei=str(tmp_path / "cache.json"), sdk_verwenden=False)
        df = dienst.hole_daten(47.5, 12.1, datetime(2026, 7, 1), datetime(2026, 7, 1))

        assert df is not None
        assert len(aufgerufen) == 2  # erst Forecast, dann Archiv
        assert dienst.echte_api_daten is True
        assert "Archiv-API" in dienst.quelle

    def test_forecast_bekommt_past_days(self, tmp_path, monkeypatch):
        """Ohne past_days liefert die Forecast-API nur zukuenftige Stunden."""
        from ebike.weather import WetterService

        gesehen = {}

        def gefakete_abfrage(url, params=None, timeout=None):
            gesehen.update(params or {})
            return GemockteAntwort(WETTER_ANTWORT)

        monkeypatch.setattr(requests, "get", gefakete_abfrage)
        dienst = WetterService(cache_datei=str(tmp_path / "cache.json"), sdk_verwenden=False)
        dienst.hole_daten(47.5, 12.1, datetime(2026, 7, 1), datetime(2026, 7, 1))

        assert gesehen.get("past_days") == 92

    def test_alle_endpunkte_kaputt_ergibt_offline(self, tmp_path, monkeypatch):
        from ebike.weather import WetterService

        def wirft(url, params=None, timeout=None):
            raise requests.RequestException("403 Client Error: Forbidden")

        monkeypatch.setattr(requests, "get", wirft)
        dienst = WetterService(cache_datei=str(tmp_path / "cache.json"), sdk_verwenden=False)

        assert dienst.hole_daten(47.5, 12.1, datetime(2024, 8, 23),
                                 datetime(2024, 8, 23)) is None
        assert dienst.echte_api_daten is False
        assert "offline" in dienst.quelle


# ---------------------------------------------------------------------------
# Wetterabfrage ueber das offizielle Open-Meteo-SDK
# ---------------------------------------------------------------------------
class GemockteVariable:
    """Ersetzt `VariableWithValues` des SDK."""

    def __init__(self, werte):
        self._werte = werte

    def ValuesAsNumpy(self):  # noqa: N802 - Namensgebung vom SDK vorgegeben
        import numpy as np
        return np.array(self._werte, dtype=float)


class GemockteStunden:
    """Ersetzt `VariablesWithTime` des SDK (3 Stunden, stuendlich)."""

    def __init__(self, spalten):
        self._spalten = spalten

    def Time(self):  # noqa: N802
        return int(pd.Timestamp("2024-08-23T16:00:00Z").timestamp())

    def TimeEnd(self):  # noqa: N802
        return int(pd.Timestamp("2024-08-23T19:00:00Z").timestamp())

    def Interval(self):  # noqa: N802
        return 3600

    def Variables(self, index):  # noqa: N802
        return GemockteVariable(self._spalten[index])


class GemockteSdkAntwort:
    def __init__(self, spalten):
        self._spalten = spalten

    def Hourly(self):  # noqa: N802
        return GemockteStunden(self._spalten)


class TestWetterServiceSdk:
    """Der SDK-Weg muss dieselben Daten liefern wie der `requests`-Weg."""

    SPALTEN = [[20.0, 21.0, 22.0],      # temperature_2m
               [10.0, 12.0, 14.0],      # wind_speed_10m
               [180.0, 190.0, 200.0],   # wind_direction_10m
               [950.0, 951.0, 952.0],   # surface_pressure
               [55.0, 56.0, 57.0]]      # relative_humidity_2m

    def _dienst_mit_gemocktem_sdk(self, tmp_path, monkeypatch, aufrufe=None):
        import ebike.weather as wetter_modul

        monkeypatch.setattr(wetter_modul, "SDK_VERFUEGBAR", True)

        def gemockte_abfrage(selbst, parameter, url, felder):
            if aufrufe is not None:
                aufrufe.append((dict(parameter), url, list(felder)))
            return selbst._sdk_antwort_umwandeln(
                GemockteSdkAntwort(self.SPALTEN), felder)

        monkeypatch.setattr(wetter_modul.WetterService, "_abfragen_sdk",
                            gemockte_abfrage)
        return wetter_modul.WetterService(cache_datei=str(tmp_path / "cache.json"))

    def test_sdk_liefert_verwendbare_daten(self, tmp_path, monkeypatch):
        dienst = self._dienst_mit_gemocktem_sdk(tmp_path, monkeypatch)
        daten = dienst.hole_daten(47.58, 12.17, START, ENDE)

        assert daten is not None and len(daten) == 3
        assert dienst.echte_api_daten is True
        assert "SDK" in dienst.quelle
        # Windgeschwindigkeit kommt in km/h und wird in m/s umgerechnet
        wind = dienst.wind_zum_zeitpunkt(pd.Timestamp("2024-08-23T17:00:00Z"))
        assert wind.geschwindigkeit_ms == pytest.approx(12.0 / 3.6)
        assert wind.richtung_grad == pytest.approx(190.0)

    def test_nur_der_eine_fahrttag_wird_abgefragt(self, tmp_path, monkeypatch):
        """Start- und Enddatum muessen dem Tag der Aufzeichnung entsprechen."""
        aufrufe = []
        dienst = self._dienst_mit_gemocktem_sdk(tmp_path, monkeypatch, aufrufe)
        dienst.hole_daten(47.58, 12.17, START, ENDE)

        parameter, url, felder = aufrufe[0]
        assert parameter["start_date"] == "2024-08-23"
        assert parameter["end_date"] == "2024-08-23"
        assert "archive-api.open-meteo.com" in url
        assert felder[0] == "temperature_2m"

    def test_umwandlung_entspricht_dem_json_format(self, tmp_path, monkeypatch):
        """Beide Wege muessen dieselbe Struktur erzeugen."""
        from ebike.weather import HOURLY_FELDER, WetterService

        roh = WetterService._sdk_antwort_umwandeln(
            GemockteSdkAntwort(self.SPALTEN), HOURLY_FELDER)

        assert WetterService.antwort_gueltig(roh)
        assert roh["hourly"]["time"] == ["2024-08-23T16:00", "2024-08-23T17:00",
                                         "2024-08-23T18:00"]
        assert roh["hourly"]["wind_speed_10m"] == [10.0, 12.0, 14.0]

    def test_sdk_fehler_faellt_auf_requests_zurueck(self, tmp_path, monkeypatch):
        """Faellt das SDK aus, muss der direkte Weg einspringen."""
        import ebike.weather as wetter_modul

        monkeypatch.setattr(wetter_modul, "SDK_VERFUEGBAR", True)

        def wirft(*a, **k):
            raise RuntimeError("SDK nicht erreichbar")

        monkeypatch.setattr(wetter_modul.WetterService, "_abfragen_sdk", wirft)
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort(WETTER_ANTWORT))

        dienst = wetter_modul.WetterService(cache_datei=str(tmp_path / "c.json"))
        daten = dienst.hole_daten(47.58, 12.17, START, ENDE)

        assert daten is not None
        assert "requests" in dienst.quelle

    def test_ohne_sdk_wird_requests_verwendet(self, tmp_path, monkeypatch):
        """Ohne installiertes SDK darf nichts anderes versucht werden."""
        import ebike.weather as wetter_modul

        monkeypatch.setattr(wetter_modul, "SDK_VERFUEGBAR", False)
        monkeypatch.setattr(wetter_modul.WetterService, "_abfragen_sdk", None)
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort(WETTER_ANTWORT))

        dienst = wetter_modul.WetterService(cache_datei=str(tmp_path / "c.json"))
        assert dienst.hole_daten(47.58, 12.17, START, ENDE) is not None
        assert "requests" in dienst.quelle


class TestWetterhinweisImBericht:
    """Der Offline-Hinweis darf nur bei echtem Offline-Betrieb erscheinen."""

    def _tex(self, track, ergebnis, tmp_path, monkeypatch, wetter):
        import ebike.report as report_modul
        monkeypatch.setattr(report_modul.shutil, "which", lambda _: None)
        report_modul.erstelle_fahrtbericht(
            track, {"LiPo": ergebnis}, [], {}, None, wetter, [], None,
            str(tmp_path))
        return (tmp_path / "fahrtbericht.tex").read_text(encoding="utf-8")

    def test_kein_hinweis_bei_echten_api_daten(self, track, ergebnis, tmp_path,
                                               monkeypatch):
        inhalt = self._tex(track, ergebnis, tmp_path, monkeypatch, {
            "Wetterquelle": "Open-Meteo Archiv-API (SDK)",
            "Echte API-Daten": "ja",
            "Mittlerer Wind [km/h]": 8.4})
        assert "Wetter-API war bei diesem Lauf nicht" not in inhalt
        assert "Archiv-API" in inhalt

    def test_hinweis_bei_offline_werten(self, track, ergebnis, tmp_path,
                                        monkeypatch):
        inhalt = self._tex(track, ergebnis, tmp_path, monkeypatch, {
            "Wetterquelle": "Standardwerte (offline)",
            "Echte API-Daten": "nein"})
        assert "Wetter-API war bei diesem Lauf nicht" in inhalt

    def test_cache_gilt_als_echte_daten(self, track, ergebnis, tmp_path,
                                        monkeypatch, tmp_path_factory):
        """Aus dem Cache geladene API-Daten sind echte Messwerte."""
        dienst = WetterService(cache_datei=str(tmp_path / "cache.json"),
                               sdk_verwenden=False)
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: GemockteAntwort(WETTER_ANTWORT))
        dienst.hole_daten(47.58, 12.17, START, ENDE)

        zweiter = WetterService(cache_datei=str(tmp_path / "cache.json"),
                                sdk_verwenden=False)
        zweiter.hole_daten(47.58, 12.17, START, ENDE)
        assert zweiter.zusammenfassung()["Echte API-Daten"] == "ja"

        ordner = tmp_path_factory.mktemp("bericht")
        inhalt = self._tex(track, ergebnis, ordner, monkeypatch,
                           zweiter.zusammenfassung())
        assert "Wetter-API war bei diesem Lauf nicht" not in inhalt


class TestKommandozeile:
    """Der Bericht muss ohne zusaetzliche Option erzeugt werden."""

    def _argumente(self, argv):
        # main.py liegt im Projektordner, nicht im Paket
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        import main as hauptprogramm
        alt = sys.argv
        try:
            sys.argv = ["main.py"] + argv
            return hauptprogramm.argumente_lesen()
        finally:
            sys.argv = alt

    def test_bericht_ist_standard(self):
        args = self._argumente([])
        assert args.no_report is False

    def test_bericht_abschaltbar(self):
        assert self._argumente(["--no-report"]).no_report is True

    def test_alter_aufruf_mit_report_funktioniert_weiter(self):
        """`--report` war frueher noetig und darf nicht zum Fehler werden."""
        args = self._argumente(["--report"])
        assert args.no_report is False

    def test_studie_bleibt_optional(self):
        assert self._argumente([]).studie is False
        assert self._argumente(["--studie"]).studie is True
