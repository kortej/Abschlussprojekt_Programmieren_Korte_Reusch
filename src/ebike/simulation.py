"""Simulation der Fahrt.

Der `FahrtSimulator` geht die GPS-Punkte Schritt fuer Schritt durch und
berechnet fuer jeden Zeitschritt:

1. Luftdichte aus Hoehe und gemessener Temperatur
2. Wind zum jeweiligen Zeitpunkt (falls Wetterdaten vorhanden)
3. Fahrwiderstaende, mechanische Leistung, Raddrehmoment, Motorstrom
4. elektrische Batterieleistung aus der mechanischen Leistung und dem
   Wirkungsgrad; daraus der Batteriestrom ueber P = (U_OC - R_i * I) * I
5. Neuer Ladezustand, Klemmenspannung und Akkutemperatur

Der Ablauf ist zusaetzlich als Aktivitaetsdiagramm in `docs/` dokumentiert.
"""

import copy
import logging

import numpy as np
import pandas as pd

from .battery import BatteryPack, Bremswiderstand
from .bike import EBike
from .config import ProjectConfig
from .environment import Atmosphaere, Wind

logger = logging.getLogger(__name__)


class SimulationsErgebnis:
    """Behaelter fuer die Ergebnisse einer Simulation."""

    def __init__(self, daten: pd.DataFrame, akku: BatteryPack,
                 bremswiderstand: Bremswiderstand, abbruchgrund: str | None = None):
        self.daten = daten
        self.akku = akku
        self.bremswiderstand = bremswiderstand
        self.abbruchgrund = abbruchgrund
        # Maximaler kumulierter Netto-Ladungsbedarf waehrend der Fahrt.
        # Diese Groesse - nicht die am Ende entnommene Ladung - bestimmt die
        # notwendige nutzbare Akkukapazitaet.
        self.max_ladungsbedarf_ah = 0.0

    @property
    def vollstaendig(self) -> bool:
        """True, wenn die gesamte Strecke gefahren werden konnte."""
        return self.abbruchgrund is None

    @property
    def gefahrene_distanz_km(self) -> float:
        return float(self.daten["distanz_m"].iloc[-1]) / 1000.0

    @property
    def verbrauchte_energie_wh(self) -> float:
        """Aus dem Akku entnommene Energie (ohne die zurueckgeladene)."""
        return float(self.daten["energie_akku_wh"].iloc[-1])

    def kennzahlen(self) -> dict:
        """Die wichtigsten Ergebnisgroessen als Dictionary."""
        d = self.daten
        distanz = self.gefahrene_distanz_km
        verbrauch = self.verbrauchte_energie_wh
        return {
            "Akkutyp": self.akku.name,
            "Nennkapazitaet [Ah]": round(self.akku.capacity_nom_Ah, 2),
            "Strecke gefahren [km]": round(distanz, 2),
            "Fahrt vollstaendig": self.vollstaendig,
            "End-SoC [%]": round(float(d["soc"].iloc[-1]) * 100, 1),
            "Minimaler SoC [%]": round(float(d["soc"].min()) * 100, 1),
            "Energieverbrauch [Wh]": round(verbrauch, 1),
            "Verbrauch [Wh/km]": round(verbrauch / distanz, 1) if distanz > 0 else 0.0,
            "Rekuperierte Energie [Wh]": round(float(d["energie_rekup_wh"].iloc[-1]), 1),
            "Mittlere Leistung [W]": round(float(d["p_mech_w"].clip(lower=0).mean()), 1),
            "Maximale Leistung [W]": round(float(d["p_mech_w"].max()), 1),
            "Maximaler Motorstrom [A]": round(float(d["strom_motor_a"].max()), 1),
            "Max. Akkutemperatur [C]": (round(float(d["akku_temp_c"].max()), 1)
                                        if d["akku_temp_c"].notna().any() else None),
            "Bremswiderstand [Wh]": round(self.bremswiderstand.dissipierte_energie_wh, 1),
            "Max. Ladungsbedarf [Ah]": round(self.max_ladungsbedarf_ah, 2),
            "Bremswiderstand Aktivierungen": self.bremswiderstand.aktivierungen,
        }

    def __repr__(self) -> str:
        status = "vollstaendig" if self.vollstaendig else f"abgebrochen ({self.abbruchgrund})"
        return f"SimulationsErgebnis({self.akku.name}, {status})"


class FahrtSimulator:
    """Simuliert die Fahrt eines E-Bikes entlang eines aufgezeichneten Tracks."""

    def __init__(self, bike: EBike, akku: BatteryPack, cfg: ProjectConfig,
                 wetterservice=None, atmosphaere: Atmosphaere | None = None):
        self.bike = bike
        self.akku = akku
        self.cfg = cfg
        self.wetterservice = wetterservice
        self.atmosphaere = atmosphaere if atmosphaere is not None else Atmosphaere()
        self.bremswiderstand = Bremswiderstand(cfg.battery.max_ladestrom_a)

    # -- Ein einzelner Zeitschritt ----------------------------------------
    def _schritt(self, zeile, wind: Wind) -> dict:
        """Berechnet alle physikalischen Groessen fuer einen Zeitschritt."""
        dt = float(zeile["dt_s"])
        v = float(zeile["v_ms"])
        a = float(zeile["a_ms2"])
        phi = float(zeile["phi_rad"])
        hoehe = float(zeile["ele_glatt_m"])
        temperatur = float(zeile["temperature"])
        richtung = float(zeile["richtung_grad"])

        # 1) Luftdichte aus Hoehe und Temperatur
        rho = self.atmosphaere.luftdichte(hoehe, temperatur)

        # 2) Kraefte und Leistung
        f_beschl = self.bike.kraft_beschleunigung(a)
        f_steig = self.bike.kraft_steigung(phi)
        f_roll = self.bike.kraft_rollwiderstand(phi, v)
        f_luft = self.bike.kraft_luftwiderstand(v, rho, wind, richtung)
        f_gesamt = f_beschl + f_steig + f_roll + f_luft

        p_mech = f_gesamt * v
        drehmoment = self.bike.drehmoment(f_gesamt)
        # Der Motorstrom dient der Auslegung von Motor und Leistungselektronik.
        # Er ist NICHT identisch mit dem Batteriestrom.
        strom_motor = self.bike.motorstrom(drehmoment)

        # 3) Elektrische Leistung, die der Akku liefern bzw. aufnehmen muss.
        #    Beim Antreiben treten Verluste auf (der Akku muss mehr liefern),
        #    beim Rekuperieren kommt nur ein Teil zurueck.
        if p_mech >= 0:
            p_batterie = p_mech / self.bike.cfg.wirkungsgrad_antrieb
        elif self.cfg.simulation.rekuperation_aktiv:
            p_batterie = p_mech * self.bike.cfg.wirkungsgrad_rekuperation
        else:
            p_batterie = 0.0  # ohne Rekuperation wird alles mechanisch gebremst

        # 4) Batteriestrom konsistent aus der Leistung:
        #    P = (U_OC - R_i * I) * I  ->  I
        strom_akku = self.akku.strom_fuer_leistung(p_batterie)

        return {
            "dt": dt, "rho": rho,
            "f_beschl": f_beschl, "f_steig": f_steig,
            "f_roll": f_roll, "f_luft": f_luft, "f_gesamt": f_gesamt,
            "p_mech": p_mech, "p_batterie": p_batterie, "drehmoment": drehmoment,
            "strom_motor": strom_motor, "strom_akku": strom_akku,
            "temperatur": temperatur, "wind_gegen": wind.gegenwindkomponente(richtung),
        }

    # -- Gesamte Fahrt -----------------------------------------------------
    def simuliere(self, track_daten: pd.DataFrame) -> SimulationsErgebnis:
        """Fuehrt die Simulation ueber alle GPS-Punkte durch.

        Args:
            track_daten: DataFrame mit berechneter Kinematik.

        Returns:
            Ein `SimulationsErgebnis` mit dem Verlauf aller Groessen.
        """
        if track_daten.empty:
            raise ValueError("Der Track enthaelt keine Daten.")

        logger.info("Starte Simulation mit Akkutyp %s (%.1f Ah)",
                    self.akku.name, self.akku.capacity_nom_Ah)

        ergebnisse = []
        energie_akku_wh = 0.0
        energie_rekup_wh = 0.0
        # Kumulierter Netto-Ladungsbedarf; sein Maximum ist die tatsaechlich
        # benoetigte nutzbare Akkukapazitaet.
        ladung_kumuliert_as = 0.0
        max_ladung_kumuliert_as = 0.0
        abbruchgrund = None
        letzter_wind = Wind(0.0, 0.0)

        for index, zeile in track_daten.iterrows():
            # Wind nur einmal pro Stunde neu abfragen (die API liefert
            # ohnehin nur Stundenwerte) - spart Rechenzeit
            if self.wetterservice is not None and self.cfg.simulation.wind_aktiv:
                if index % 200 == 0:
                    letzter_wind = self.wetterservice.wind_zum_zeitpunkt(zeile["time"])
            wind = letzter_wind

            werte = self._schritt(zeile, wind)
            dt = werte["dt"]

            # Akku-Umgebungstemperatur fuer das thermische Modell setzen
            self.akku.umgebungstemperatur_c = werte["temperatur"]

            strom = werte["strom_akku"]

            # Fehlerbehandlung 1: Akku leer -> Simulation abbrechen
            if self.akku.is_empty() and strom > 0:
                abbruchgrund = (f"Akku bei km {zeile['distanz_m'] / 1000:.2f} leer - "
                                f"die Fahrt kann nicht fortgesetzt werden.")
                logger.error(abbruchgrund)
                break

            # Fehlerbehandlung 2: Akku voll -> Bremswiderstand
            spannung_vor = self.akku.voltage(0.0)
            strom_effektiv = self.bremswiderstand.begrenze_ladestrom(
                strom, self.akku, spannung_vor, dt)
            if strom_effektiv != strom:
                logger.debug("Bremswiderstand aktiv bei t = %.0f s: "
                             "%.1f A koennen nicht geladen werden",
                             zeile["t_s"], strom - strom_effektiv)

            # Klemmenspannung und elektrische Leistung gehoeren zum Zustand
            # am Beginn des Zeitschritts - also VOR dem Aktualisieren des SoC.
            # Sonst passen Strom, Spannung und Leistung nicht exakt zusammen.
            spannung = self.akku.voltage(strom_effektiv)
            p_elektrisch = spannung * strom_effektiv

            # apply_current gibt zurueck, wie lange der Strom tatsaechlich
            # fliessen konnte - der Akku kann innerhalb eines Zeitschritts
            # leer oder voll werden.
            try:
                wirksame_dauer = self.akku.apply_current(strom_effektiv, dt)
            except ValueError as fehler:
                abbruchgrund = f"Fehler im Akkumodell: {fehler}"
                logger.error(abbruchgrund)
                break

            if p_elektrisch > 0:
                energie_akku_wh += p_elektrisch * wirksame_dauer / 3600.0
            else:
                energie_rekup_wh += -p_elektrisch * wirksame_dauer / 3600.0

            ladung_kumuliert_as += strom_effektiv * wirksame_dauer
            max_ladung_kumuliert_as = max(max_ladung_kumuliert_as,
                                          ladung_kumuliert_as)

            rest_dauer = dt - wirksame_dauer
            if rest_dauer > 1e-9 and strom_effektiv < 0:
                # Der Akku ist waehrend des Schritts voll geworden. Die
                # restliche rekuperierte Energie muss der Bremswiderstand
                # aufnehmen.
                self.bremswiderstand.nimm_energie_auf(
                    abs(p_elektrisch) * rest_dauer / 3600.0)
            elif rest_dauer > 1e-9 and strom_effektiv > 0:
                # Der Akku ist waehrend des Schritts leer geworden. Der Rest
                # des Zeitschritts kann nicht mehr gefahren werden.
                abbruchgrund = (
                    f"Akku bei km {zeile['distanz_m'] / 1000:.2f} leer - "
                    f"die Fahrt kann nicht fortgesetzt werden.")
                logger.error(abbruchgrund)

            ergebnisse.append({
                "t_s": zeile["t_s"],
                "time": zeile["time"],
                "lat": zeile["lat"],
                "lon": zeile["lon"],
                "distanz_m": zeile["distanz_m"],
                "ele_m": zeile["ele_glatt_m"],
                "v_kmh": zeile["v_kmh"],
                "a_ms2": zeile["a_ms2"],
                "steigung_prozent": zeile["steigung_prozent"],
                "richtung_grad": zeile["richtung_grad"],
                "himmelsrichtung": zeile["himmelsrichtung"],
                "luftdichte": werte["rho"],
                "wind_gegen_ms": werte["wind_gegen"],
                "f_beschl_n": werte["f_beschl"],
                "f_steig_n": werte["f_steig"],
                "f_roll_n": werte["f_roll"],
                "f_luft_n": werte["f_luft"],
                "f_gesamt_n": werte["f_gesamt"],
                "p_mech_w": werte["p_mech"],
                "p_batterie_soll_w": werte["p_batterie"],
                "p_elektrisch_w": p_elektrisch,
                "drehmoment_nm": werte["drehmoment"],
                "strom_motor_a": werte["strom_motor"],
                "strom_akku_a": strom_effektiv,
                "spannung_v": spannung,
                "soc": self.akku.soc,
                "akku_temp_c": self.akku.temperatur_c,
                "umgebungstemp_c": werte["temperatur"],
                "energie_akku_wh": energie_akku_wh,
                "energie_rekup_wh": energie_rekup_wh,
                "ladung_kumuliert_ah": ladung_kumuliert_as / 3600.0,
                "dt_wirksam_s": wirksame_dauer,
            })

            if abbruchgrund is not None:
                break

        if not ergebnisse:
            raise RuntimeError("Die Simulation hat keinen einzigen Schritt berechnet.")

        daten = pd.DataFrame(ergebnisse)

        # Plausibilitaetspruefung: SoC muss im gueltigen Bereich bleiben
        if daten["soc"].min() < -1e-9 or daten["soc"].max() > 1 + 1e-9:
            logger.error("Der Ladezustand hat den gueltigen Bereich verlassen!")

        logger.info("Simulation beendet: %d Schritte, End-SoC = %.1f %%",
                    len(daten), daten["soc"].iloc[-1] * 100)

        ergebnis = SimulationsErgebnis(daten, self.akku, self.bremswiderstand,
                                       abbruchgrund)
        ergebnis.max_ladungsbedarf_ah = max_ladung_kumuliert_as / 3600.0
        return ergebnis


def mindestkapazitaet_abschaetzen(ergebnis: SimulationsErgebnis,
                                  reserve: float = 0.15) -> float:
    """Notwendige Kapazitaet aus dem kumulierten Ladungsbedarf eines Laufs.

    Massgebend ist nicht die am Ende entnommene Ladung, sondern das Maximum
    des kumulierten Netto-Ladungsbedarfs waehrend der Fahrt (nach einer langen
    Abfahrt mit Rekuperation kann die Bilanz zwischendurch schon wieder
    kleiner sein).

    Wichtig: Wurde die Fahrt wegen eines leeren Akkus abgebrochen, beschreibt
    das Ergebnis nur den gefahrenen Teil der Strecke. Fuer die Auslegung der
    *gesamten* Strecke ist `notwendige_kapazitaet()` zu verwenden, das die
    Strecke mit einem ausreichend grossen virtuellen Akku durchrechnet. Eine
    lineare Hochrechnung der ersten Kilometer waere bei ungleichmaessigen
    Strecken (Anstiege, Abfahrten) irrefuehrend.

    Args:
        ergebnis: ein Simulationsergebnis.
        reserve: gewuenschte Restladung am Ziel (0.15 = 15 %).

    Returns:
        Empfohlene Nennkapazitaet in Ah.
    """
    if not 0.0 <= reserve < 1.0:
        raise ValueError("Die Reserve muss zwischen 0 und 1 liegen.")
    bedarf_ah = max(ergebnis.max_ladungsbedarf_ah, 0.0)
    return float(np.round(bedarf_ah / (1.0 - reserve), 2))


def notwendige_kapazitaet(track_daten: pd.DataFrame, cfg: ProjectConfig,
                          wetterservice=None, reserve: float = 0.15,
                          virtuelle_kapazitaet_ah: float = 1000.0) -> dict:
    """Bestimmt die notwendige Akkukapazitaet fuer die gesamte Strecke.

    Die Strecke wird einmal mit einem absichtlich viel zu grossen virtuellen
    Akku simuliert. Dieser wird garantiert nicht leer, dadurch laesst sich der
    Ladungsbedarf ueber die vollstaendige Route bestimmen - ohne Hochrechnung.

    Args:
        track_daten: DataFrame mit berechneter Kinematik.
        cfg: Basiskonfiguration (wird nicht veraendert).
        wetterservice: optionaler Wetterservice fuer den Wind.
        reserve: gewuenschte Restladung am Ziel.
        virtuelle_kapazitaet_ah: Kapazitaet des Hilfsakkus.

    Returns:
        Dictionary mit `netto_ladung_ah`, `empfohlene_kapazitaet_ah`,
        `energie_wh` und `vollstaendig`.
    """
    from .battery import erzeuge_akku  # lokal, um Zirkelimporte zu vermeiden

    hilfs_cfg = copy.deepcopy(cfg)
    zellkapazitaet = hilfs_cfg.battery.zellkapazitaet_ah
    hilfs_cfg.battery.zellen_parallel = max(
        1, int(np.ceil(virtuelle_kapazitaet_ah / zellkapazitaet)))

    starttemperatur = float(track_daten["temperature"].iloc[0])
    akku = erzeuge_akku(hilfs_cfg.simulation.akkutyp, hilfs_cfg.battery,
                        starttemperatur_c=starttemperatur,
                        thermik_aktiv=hilfs_cfg.simulation.thermisches_modell_aktiv)
    simulator = FahrtSimulator(EBike(hilfs_cfg.bike), akku, hilfs_cfg, wetterservice)
    ergebnis = simulator.simuliere(track_daten)

    netto_ah = max(ergebnis.max_ladungsbedarf_ah, 0.0)
    empfohlen = float(np.round(netto_ah / (1.0 - reserve), 2))
    logger.info("Ladungsbedarf der gesamten Strecke: %.2f Ah -> "
                "empfohlene Kapazitaet mit %.0f %% Reserve: %.2f Ah",
                netto_ah, reserve * 100, empfohlen)
    return {
        "netto_ladung_ah": round(netto_ah, 2),
        "empfohlene_kapazitaet_ah": empfohlen,
        "energie_wh": round(ergebnis.verbrauchte_energie_wh, 1),
        "vollstaendig": ergebnis.vollstaendig,
    }


def kleinste_konfiguration_suchen(track_daten: pd.DataFrame, cfg: ProjectConfig,
                                  wetterservice=None, reserve: float = 0.15,
                                  max_parallel: int = 40) -> dict:
    """Sucht die kleinste Zellkonfiguration, die die Strecke schafft.

    Ausgehend von der berechneten Mindestkapazitaet wird die Zahl paralleler
    Zellen schrittweise erhoeht, bis die Fahrt vollstaendig gelingt und am
    Ziel noch die geforderte Reserve vorhanden ist.

    Args:
        max_parallel: Obergrenze der Suche (Abbruchkriterium).

    Returns:
        Dictionary mit `zellen_parallel`, `kapazitaet_ah`, `end_soc_prozent`
        und `gefunden`.
    """
    from .battery import erzeuge_akku

    bedarf = notwendige_kapazitaet(track_daten, cfg, wetterservice, reserve)
    zellkapazitaet = cfg.battery.zellkapazitaet_ah
    start = max(1, int(np.floor(bedarf["empfohlene_kapazitaet_ah"] / zellkapazitaet)))

    starttemperatur = float(track_daten["temperature"].iloc[0])
    for parallel in range(start, max_parallel + 1):
        versuch = copy.deepcopy(cfg)
        versuch.battery.zellen_parallel = parallel
        akku = erzeuge_akku(versuch.simulation.akkutyp, versuch.battery,
                            starttemperatur_c=starttemperatur,
                            thermik_aktiv=versuch.simulation.thermisches_modell_aktiv)
        simulator = FahrtSimulator(EBike(versuch.bike), akku, versuch, wetterservice)
        ergebnis = simulator.simuliere(track_daten)
        end_soc = float(ergebnis.daten["soc"].iloc[-1])
        if ergebnis.vollstaendig and end_soc >= reserve:
            logger.info("Kleinste ausreichende Konfiguration: %dP = %.1f Ah "
                        "(End-SoC %.1f %%)", parallel,
                        parallel * zellkapazitaet, end_soc * 100)
            return {
                "zellen_parallel": parallel,
                "kapazitaet_ah": round(parallel * zellkapazitaet, 2),
                "end_soc_prozent": round(end_soc * 100, 1),
                "gefunden": True,
            }

    logger.warning("Bis %dP wurde keine ausreichende Konfiguration gefunden.",
                   max_parallel)
    return {"zellen_parallel": max_parallel,
            "kapazitaet_ah": round(max_parallel * zellkapazitaet, 2),
            "end_soc_prozent": 0.0, "gefunden": False}
