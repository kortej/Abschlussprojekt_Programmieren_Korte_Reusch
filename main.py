"""Hauptprogramm der E-Bike-Simulation.

Aufruf (aus dem Projektordner):

    python main.py                      # Simulation, Plots, Karte, Bericht
    python main.py --akku nmc --no-wetter
    python main.py --studie --auslegung  # zusaetzlich Parameterstudien
    python main.py --no-report           # ohne Bericht (kein pdflatex noetig)

Der komplette Ablauf ist als Aktivitaetsdiagramm in
`docs/aktivitaetsdiagramm.md` dokumentiert.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Alle Pfade werden relativ zu dieser Datei aufgeloest, damit das Programm
# auch aus einem anderen Arbeitsverzeichnis heraus startbar ist:
#     python C:\...\ebike-simulation\main.py
PROJEKTORDNER = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJEKTORDNER / "src"))

from ebike.battery import erzeuge_akku  # noqa: E402
from ebike.bike import EBike  # noqa: E402
from ebike.config import ProjectConfig  # noqa: E402
from ebike.data_loader import Track  # noqa: E402
from ebike.geocoding import GeocodingService  # noqa: E402
from ebike.mapping import StreckenKarte  # noqa: E402
from ebike.parameter_study import Parameterstudie  # noqa: E402
from ebike.plotting import ErgebnisPlotter  # noqa: E402
from ebike.report import erstelle_fahrtbericht  # noqa: E402
from ebike.config import pfad_aufloesen  # noqa: E402
from ebike.results_export import (  # noqa: E402
    aktualisiere_readme, sammle_ergebnisse, speichere_json)
from ebike.simulation import (  # noqa: E402
    FahrtSimulator, kleinste_konfiguration_suchen,
    mindestkapazitaet_abschaetzen, notwendige_kapazitaet)
from ebike.weather import WetterService  # noqa: E402

logger = logging.getLogger("ebike")


def logging_einrichten(ausgabeordner: str, ausfuehrlich: bool = False) -> None:
    """Richtet die Ausgabe auf der Konsole und in eine Logdatei ein."""
    os.makedirs(ausgabeordner, exist_ok=True)
    stufe = logging.DEBUG if ausfuehrlich else logging.INFO
    logging.basicConfig(
        level=stufe,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(ausgabeordner, "simulation.log"),
                                mode="w", encoding="utf-8"),
        ],
    )


def argumente_lesen() -> argparse.Namespace:
    """Definiert die Kommandozeilenoptionen."""
    parser = argparse.ArgumentParser(
        description="Simulation und Auslegung eines E-Bikes aus GPS-Daten.")
    parser.add_argument(
        "--daten",
        default=str(PROJEKTORDNER / "data" / "final_project_input_data.csv"),
        help="Pfad zur CSV-Datei mit den GPS-Daten")
    parser.add_argument(
        "--ausgabe", default=str(PROJEKTORDNER / "output"),
        help="Ordner fuer Plots, Bericht und Logdatei")
    parser.add_argument("--akku", default="beide", choices=["lipo", "nmc", "beide"],
                        help="zu simulierender Akkutyp")
    parser.add_argument("--zellen-parallel", type=int, default=20,
                        help="Anzahl parallel geschalteter Zellen (Kapazitaet)")
    parser.add_argument("--no-wetter", action="store_true",
                        help="keine Wetterdaten abrufen (offline rechnen)")
    parser.add_argument("--no-geocoding", action="store_true",
                        help="kein Reverse Geocoding durchfuehren")
    parser.add_argument("--no-thermik", action="store_true",
                        help="thermisches Akkumodell deaktivieren")
    parser.add_argument("--studie", action="store_true",
                        help="automatische Parameterstudien durchfuehren")
    # Der Bericht wird standardmaessig erzeugt. `--report` bleibt als
    # Schalter erhalten, damit aeltere Aufrufe weiter funktionieren.
    parser.add_argument("--report", action="store_true",
                        help="(Standard) LaTeX-Bericht erzeugen und uebersetzen")
    parser.add_argument("--no-report", action="store_true",
                        help="keinen Bericht erzeugen (spart Zeit und "
                             "benoetigt kein pdflatex)")
    parser.add_argument("--auslegung", action="store_true",
                        help="kleinste ausreichende Akkukonfiguration suchen")
    parser.add_argument("--no-readme", action="store_true",
                        help="README nicht automatisch aktualisieren")
    parser.add_argument("--ausfuehrlich", action="store_true",
                        help="ausfuehrliches Logging (DEBUG)")
    return parser.parse_args()


def main() -> int:
    args = argumente_lesen()

    cfg = ProjectConfig()
    cfg.datenpfad = pfad_aufloesen(args.daten)
    cfg.ausgabeordner = str(Path(args.ausgabe).expanduser().resolve())
    cfg.battery.zellen_parallel = args.zellen_parallel
    cfg.simulation.wind_aktiv = not args.no_wetter
    cfg.simulation.thermisches_modell_aktiv = not args.no_thermik

    logging_einrichten(cfg.ausgabeordner, args.ausfuehrlich)
    logger.info("=== E-Bike-Simulation gestartet ===")

    # 1) Daten einlesen und auswerten -------------------------------------
    try:
        track = Track.aus_csv(cfg.datenpfad)
    except (FileNotFoundError, ValueError) as fehler:
        logger.error("Die Daten konnten nicht geladen werden: %s", fehler)
        return 1

    track.berechne_kinematik(
        glaettung_fenster=cfg.simulation.glaettung_fenster,
        max_geschwindigkeit_ms=cfg.simulation.max_geschwindigkeit_ms,
        steigung_fenster_m=cfg.simulation.steigung_fenster_m,
        max_steigung_prozent=cfg.simulation.max_steigung_prozent,
        max_beschleunigung_ms2=cfg.simulation.max_beschleunigung_ms2)

    logger.info("Zusammenfassung der Fahrt:")
    for schluessel, wert in track.zusammenfassung().items():
        logger.info("  %-30s %s", schluessel + ":", wert)

    # 2) Wetterdaten -------------------------------------------------------
    wetterservice = None
    wetter_kennzahlen = {}
    if not args.no_wetter:
        wetterservice = WetterService(
            cache_datei=os.path.join(cfg.ausgabeordner, "wetter_cache.json"))
        wetterservice.hole_daten(
            latitude=float(track.daten["lat"].mean()),
            longitude=float(track.daten["lon"].mean()),
            start=track.daten["time"].iloc[0].to_pydatetime(),
            ende=track.daten["time"].iloc[-1].to_pydatetime())
        wetter_kennzahlen = wetterservice.zusammenfassung()

    # 3) Reverse Geocoding -------------------------------------------------
    wegpunkte = []
    if not args.no_geocoding:
        geocoder = GeocodingService(
            cache_datei=os.path.join(cfg.ausgabeordner, "geocoding_cache.json"))
        wegpunkte = geocoder.orte_entlang_strecke(track.daten, anzahl=8)
        logger.info("Strecke: %s", " -> ".join(p["ort"] for p in wegpunkte))

    # 4) Simulation --------------------------------------------------------
    typen = ["lipo", "nmc"] if args.akku == "beide" else [args.akku]
    ergebnisse = {}
    akkus = []
    starttemperatur = float(track.daten["temperature"].iloc[0])

    for typ in typen:
        cfg.simulation.akkutyp = typ
        akku = erzeuge_akku(typ, cfg.battery, starttemperatur_c=starttemperatur,
                            thermik_aktiv=cfg.simulation.thermisches_modell_aktiv)
        simulator = FahrtSimulator(EBike(cfg.bike), akku, cfg, wetterservice)
        ergebnis = simulator.simuliere(track.daten)
        ergebnisse[akku.name] = ergebnis
        akkus.append(akku)

        logger.info("--- Ergebnis %s ---", akku.name)
        for schluessel, wert in ergebnis.kennzahlen().items():
            logger.info("  %-32s %s", schluessel + ":", wert)
        logger.info("  Kapazitaet fuer den gefahrenen Teil (15%% Reserve): "
                    "%.2f Ah", mindestkapazitaet_abschaetzen(ergebnis))
        if not ergebnis.vollstaendig:
            logger.info("  Hinweis: Die Fahrt wurde abgebrochen. Die "
                        "Auslegung fuer die Gesamtstrecke steht weiter unten.")

    # 4b) Auslegung der Akkukapazitaet fuer die GESAMTE Strecke -----------
    # Dazu wird die Strecke einmal mit einem viel zu grossen virtuellen Akku
    # simuliert. Eine lineare Hochrechnung der ersten Kilometer waere bei
    # dieser ungleichmaessigen Route irrefuehrend.
    cfg.simulation.akkutyp = typen[0]
    kapazitaet = notwendige_kapazitaet(track.daten, cfg, wetterservice)
    logger.info("--- Auslegung der Akkukapazitaet ---")
    for schluessel, wert in kapazitaet.items():
        logger.info("  %-32s %s", schluessel + ":", wert)

    kleinste = {}
    if args.auslegung:
        kleinste = kleinste_konfiguration_suchen(track.daten, cfg, wetterservice)
        logger.info("  Kleinste ausreichende Konfiguration: %dP = %.1f Ah",
                    kleinste["zellen_parallel"], kleinste["kapazitaet_ah"])

    # 5) Plots -------------------------------------------------------------
    haupt = list(ergebnisse.values())[0]
    plotter = ErgebnisPlotter(haupt, cfg.ausgabeordner)
    plots = plotter.alle(akkus=akkus, wegpunkte=wegpunkte)
    if len(ergebnisse) > 1:
        plots.append(plotter.akkuvergleich(ergebnisse))

    # 6) Karte -------------------------------------------------------------
    kartenpfad = None
    try:
        karte = StreckenKarte(haupt.daten, cfg.ausgabeordner)
        kartenpfad = karte.erzeuge(wegpunkte=wegpunkte)
    except (ValueError, OSError) as fehler:
        logger.warning("Die Karte konnte nicht erzeugt werden: %s", fehler)

    # 7) Parameterstudien --------------------------------------------------
    studien, studienplot = {}, None
    if args.studie:
        logger.info("Starte Parameterstudien - das dauert einen Moment ...")
        studie = Parameterstudie(track.daten, cfg, wetterservice, cfg.ausgabeordner)
        studien = studie.standardstudien()
        studienplot = studie.plotte(studien)
        studie.speichere_csv(studien)

    # 8) Bericht -----------------------------------------------------------
    berichtsstatus = "nicht erzeugt (--no-report)"
    if not args.no_report:
        pdf = erstelle_fahrtbericht(
            track, ergebnisse, plots, studien, studienplot,
            wetter_kennzahlen, wegpunkte, kartenpfad, cfg.ausgabeordner,
            kapazitaet={**kapazitaet, **kleinste})
        if pdf:
            logger.info("Bericht erstellt: %s", pdf)
            berichtsstatus = pdf
        else:
            berichtsstatus = (
                "nur LaTeX-Quelltext (fahrtbericht.tex) - fuer das PDF wird "
                "pdflatex benoetigt: MiKTeX (Windows) oder TeX Live (Linux)")
            logger.warning("Kein PDF erzeugt: %s", berichtsstatus)

    # 9) Ergebnisse exportieren und README aktualisieren -------------------
    # So koennen README, Bericht und Simulation nicht auseinanderlaufen.
    zusammenfassung = sammle_ergebnisse(track, ergebnisse, wetter_kennzahlen,
                                        kapazitaet, kleinste)
    speichere_json(zusammenfassung, cfg.ausgabeordner)
    if not args.no_readme:
        aktualisiere_readme(zusammenfassung, str(PROJEKTORDNER / "README.md"))

    # Abschliessende Uebersicht, damit erkennbar ist, was tatsaechlich
    # erzeugt wurde - und woran es sonst liegt.
    logger.info("=== Fertig. Alle Ergebnisse liegen in '%s' ===", cfg.ausgabeordner)
    logger.info("  Plots:        %d Dateien", len(plots))
    logger.info("  Karte:        %s", kartenpfad or "nicht erzeugt (--no-geocoding)")
    logger.info("  Wetterdaten:  %s", wetter_kennzahlen.get(
        "Wetterquelle", "nicht abgefragt (--no-wetter)"))
    logger.info("  Bericht:      %s", berichtsstatus)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
