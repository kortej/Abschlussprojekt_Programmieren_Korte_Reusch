"""Einlesen und Aufbereiten der GPS-Rohdaten.

Die Klasse `Track` kapselt die eingelesenen Messpunkte und berechnet daraus
alle abgeleiteten Groessen: Distanz, Geschwindigkeit, Beschleunigung,
Steigung und Fahrtrichtung.
"""

import logging
import os

import numpy as np
import pandas as pd

from . import geo

logger = logging.getLogger(__name__)

# Diese Spalten muss die CSV-Datei enthalten
ERWARTETE_SPALTEN = ["lat", "lon", "ele", "time", "temperature"]


class Track:
    """Repraesentiert die gefahrene Strecke inklusive abgeleiteter Groessen."""

    def __init__(self, daten: pd.DataFrame):
        """
        Args:
            daten: DataFrame mit den Spalten lat, lon, ele, time, temperature.
        """
        self.daten = daten.copy()

    # -- Erzeugen ----------------------------------------------------------
    @classmethod
    def aus_csv(cls, pfad: str, trennzeichen: str = ";") -> "Track":
        """Liest eine CSV-Datei ein und gibt einen fertigen Track zurueck.

        Raises:
            FileNotFoundError: wenn die Datei nicht existiert.
            ValueError: wenn Spalten fehlen oder zu wenige Punkte vorhanden sind.
        """
        if not os.path.exists(pfad):
            raise FileNotFoundError(f"Die Datendatei '{pfad}' wurde nicht gefunden.")

        logger.info("Lese GPS-Daten aus %s", pfad)
        daten = pd.read_csv(pfad, sep=trennzeichen)

        fehlende = [s for s in ERWARTETE_SPALTEN if s not in daten.columns]
        if fehlende:
            raise ValueError(f"In der CSV fehlen die Spalten: {fehlende}")

        daten["time"] = pd.to_datetime(daten["time"], format="mixed", utc=True)
        daten = daten.sort_values("time").reset_index(drop=True)

        # Zeilen mit fehlenden Werten koennen wir nicht verwenden
        vorher = len(daten)
        daten = daten.dropna(subset=ERWARTETE_SPALTEN).reset_index(drop=True)
        if len(daten) < vorher:
            logger.warning("%d Zeilen mit fehlenden Werten entfernt", vorher - len(daten))

        if len(daten) < 2:
            raise ValueError("Es werden mindestens zwei GPS-Punkte benoetigt.")

        logger.info("%d GPS-Punkte eingelesen", len(daten))
        return cls(daten)

    # -- Berechnung --------------------------------------------------------
    def berechne_kinematik(self, glaettung_fenster: int = 9,
                           max_geschwindigkeit_ms: float = 25.0,
                           steigung_fenster_m: float = 30.0,
                           max_steigung_prozent: float = 30.0,
                           max_beschleunigung_ms2: float = 3.0) -> pd.DataFrame:
        """Berechnet Distanz, Geschwindigkeit, Beschleunigung, Steigung, Richtung.

        GPS-Rohdaten rauschen erheblich. Ohne Plausibilisierung entstehen
        Steigungen von mehreren hundert Prozent und daraus voellig
        unrealistische Kraefte, Drehmomente und Stroeme. Deshalb wird

        * die Hoehe geglaettet,
        * die Steigung ueber ein *streckenbasiertes* Fenster bestimmt
          (nicht zwischen zwei einzelnen GPS-Punkten),
        * die Steigung auf einen realistischen Bereich begrenzt,
        * die Beschleunigung ebenfalls begrenzt.

        Args:
            glaettung_fenster: Fensterbreite des gleitenden Mittelwerts.
            max_geschwindigkeit_ms: Plausibilitaetsgrenze der Geschwindigkeit.
            steigung_fenster_m: Laenge des Streckenfensters fuer die Steigung.
            max_steigung_prozent: Plausibilitaetsgrenze der Steigung in Prozent.
            max_beschleunigung_ms2: Plausibilitaetsgrenze der Beschleunigung.

        Returns:
            Den erweiterten DataFrame (auch als `self.daten` gespeichert).
        """
        d = self.daten

        lat = d["lat"].to_numpy()
        lon = d["lon"].to_numpy()
        ele = d["ele"].to_numpy()

        # Zeitschritte in Sekunden
        dt = d["time"].diff().dt.total_seconds().to_numpy().copy()
        dt[0] = 0.0
        # Ein Zeitschritt von 0 wuerde zu einer Division durch 0 fuehren
        dt_sicher = np.where(dt > 0, dt, np.nan)

        # Horizontale Distanz zwischen aufeinanderfolgenden Punkten
        ds = np.zeros(len(d))
        richtung = np.zeros(len(d))
        for i in range(1, len(d)):
            ds[i] = geo.haversine_distanz(lat[i - 1], lon[i - 1], lat[i], lon[i])
            richtung[i] = geo.bearing(lat[i - 1], lon[i - 1], lat[i], lon[i])
        richtung[0] = richtung[1] if len(d) > 1 else 0.0

        strecke = np.cumsum(ds)

        # Hoehendifferenz: die GPS-Hoehe rauscht, daher vorher glaetten
        ele_glatt = pd.Series(ele).rolling(
            glaettung_fenster, center=True, min_periods=1).mean().to_numpy()
        dh = np.diff(ele_glatt, prepend=ele_glatt[0])

        # Geschwindigkeit v = ds/dt  (raeumliche Strecke inkl. Hoehe)
        ds_3d = np.sqrt(ds ** 2 + dh ** 2)
        v_roh = np.divide(ds_3d, dt_sicher, out=np.zeros_like(ds_3d),
                          where=~np.isnan(dt_sicher))
        v_roh = np.nan_to_num(v_roh)
        # Ausreisser begrenzen und glaetten
        v_roh = np.clip(v_roh, 0.0, max_geschwindigkeit_ms)
        v = pd.Series(v_roh).rolling(
            glaettung_fenster, center=True, min_periods=1).mean().to_numpy()

        # Beschleunigung a = dv/dt, ebenfalls plausibilisiert
        a = np.zeros(len(d))
        a[1:] = np.diff(v) / np.where(dt[1:] > 0, dt[1:], np.nan)
        a = np.nan_to_num(a)
        unplausible_a = int(np.sum(np.abs(a) > max_beschleunigung_ms2))
        if unplausible_a:
            logger.warning("%d Beschleunigungswerte ueber %.1f m/s^2 wurden "
                           "begrenzt (sehr kleine Zeitschritte / GPS-Rauschen)",
                           unplausible_a, max_beschleunigung_ms2)
        a = np.clip(a, -max_beschleunigung_ms2, max_beschleunigung_ms2)

        # Steigung ueber ein Streckenfenster statt zwischen zwei Punkten
        phi, steigung_prozent = self._steigung_ueber_fenster(
            strecke, ele_glatt, steigung_fenster_m, max_steigung_prozent)

        d["dt_s"] = dt
        d["ds_m"] = ds
        d["dh_m"] = dh
        d["ele_glatt_m"] = ele_glatt
        d["distanz_m"] = strecke
        d["v_ms"] = v
        d["v_kmh"] = v * 3.6
        d["a_ms2"] = a
        d["phi_rad"] = phi
        d["steigung_prozent"] = steigung_prozent
        d["richtung_grad"] = richtung
        d["himmelsrichtung"] = [geo.himmelsrichtung(r) for r in richtung]
        d["t_s"] = (d["time"] - d["time"].iloc[0]).dt.total_seconds()

        self.daten = d
        logger.info("Kinematik berechnet: %.2f km, %.0f s Fahrtdauer",
                    d["distanz_m"].iloc[-1] / 1000.0, d["t_s"].iloc[-1])
        logger.info("Steigung: %.1f %% bis %.1f %% (Fenster %.0f m, Grenze +/-%.0f %%)",
                    steigung_prozent.min(), steigung_prozent.max(),
                    steigung_fenster_m, max_steigung_prozent)
        return d

    @staticmethod
    def _steigung_ueber_fenster(strecke_m: np.ndarray, hoehe_m: np.ndarray,
                                fenster_m: float,
                                max_steigung_prozent: float,
                                min_distanz_m: float = 1.0):
        """Bestimmt die Steigung ueber ein zentriertes Streckenfenster.

        Zwischen zwei aufeinanderfolgenden GPS-Punkten liegen oft nur wenige
        Meter. Eine Hoehenabweichung von einem Meter ergibt dort bereits
        Steigungen von ueber 100 %. Deshalb wird die Hoehe an den Stellen
        `s - fenster/2` und `s + fenster/2` interpoliert und die Steigung aus
        der Differenz ueber die tatsaechliche Fensterlaenge gebildet.

        Args:
            strecke_m: kumulierte horizontale Strecke je Punkt.
            hoehe_m: (geglaettete) Seehoehe je Punkt.
            fenster_m: Laenge des Streckenfensters.
            max_steigung_prozent: Plausibilitaetsgrenze in Prozent.
            min_distanz_m: kleinere Fenster gelten als Stillstand (Steigung 0).

        Returns:
            Tupel (phi_rad, steigung_prozent) als numpy-Arrays.
        """
        if fenster_m <= 0:
            raise ValueError("Das Steigungsfenster muss groesser als 0 sein.")

        halb = fenster_m / 2.0
        s_min, s_max = float(strecke_m[0]), float(strecke_m[-1])
        s_unten = np.clip(strecke_m - halb, s_min, s_max)
        s_oben = np.clip(strecke_m + halb, s_min, s_max)

        h_unten = np.interp(s_unten, strecke_m, hoehe_m)
        h_oben = np.interp(s_oben, strecke_m, hoehe_m)

        delta_s = s_oben - s_unten
        delta_h = h_oben - h_unten

        # Punkte mit sehr kleiner horizontaler Distanz (Stillstand, Ampel,
        # Pause) liefern keine sinnvolle Steigung -> 0
        steigung = np.divide(delta_h, delta_s,
                             out=np.zeros_like(delta_h),
                             where=delta_s >= min_distanz_m) * 100.0

        unplausibel = int(np.sum(np.abs(steigung) > max_steigung_prozent))
        if unplausibel:
            logger.warning("%d Steigungswerte ueber +/-%.0f %% wurden begrenzt "
                           "(Hoehenrauschen der GPS-Daten)",
                           unplausibel, max_steigung_prozent)
        steigung = np.clip(steigung, -max_steigung_prozent, max_steigung_prozent)
        phi = np.arctan(steigung / 100.0)
        return phi, steigung

    # -- Kennzahlen --------------------------------------------------------
    @property
    def gesamtdistanz_km(self) -> float:
        return float(self.daten["distanz_m"].iloc[-1]) / 1000.0

    @property
    def gesamtdauer_s(self) -> float:
        return float(self.daten["t_s"].iloc[-1])

    @property
    def hoehenmeter_aufstieg(self) -> float:
        """Summe aller positiven Hoehendifferenzen."""
        dh = self.daten["dh_m"]
        return float(dh[dh > 0].sum())

    @property
    def hoehenmeter_abstieg(self) -> float:
        dh = self.daten["dh_m"]
        return float(-dh[dh < 0].sum())

    @property
    def durchschnittsgeschwindigkeit_kmh(self) -> float:
        """Tatsaechliche Durchschnittsgeschwindigkeit inklusive Pausen.

        Der Mittelwert der Spalte `v_kmh` waere hier falsch: die GPS-Punkte
        haben unterschiedliche zeitliche Abstaende, ein einfacher Mittelwert
        gewichtet also kurze und lange Zeitschritte gleich. Richtig ist der
        Quotient aus Gesamtstrecke und Gesamtdauer.
        """
        if self.gesamtdauer_s <= 0:
            return 0.0
        return self.gesamtdistanz_km / (self.gesamtdauer_s / 3600.0)

    def bewegungsgeschwindigkeit_kmh(self, schwelle_kmh: float = 1.0) -> float:
        """Durchschnittsgeschwindigkeit ohne Stillstandszeiten.

        Args:
            schwelle_kmh: ab dieser Geschwindigkeit gilt die Fahrt als bewegt.
        """
        d = self.daten
        faehrt = d["v_kmh"] > schwelle_kmh
        bewegte_zeit_s = float(d.loc[faehrt, "dt_s"].sum())
        bewegte_strecke_m = float(d.loc[faehrt, "ds_m"].sum())
        if bewegte_zeit_s <= 0:
            return 0.0
        return (bewegte_strecke_m / 1000.0) / (bewegte_zeit_s / 3600.0)

    def zusammenfassung(self) -> dict:
        """Gibt die wichtigsten Kenngroessen der Fahrt als Dictionary zurueck."""
        d = self.daten
        return {
            "Anzahl Messpunkte": len(d),
            "Gesamtdistanz [km]": round(self.gesamtdistanz_km, 2),
            "Fahrtdauer [h]": round(self.gesamtdauer_s / 3600.0, 2),
            "Durchschnittsgeschw. [km/h]": round(self.durchschnittsgeschwindigkeit_kmh, 2),
            "Bewegungsdurchschnitt [km/h]": round(self.bewegungsgeschwindigkeit_kmh(), 2),
            "Maximalgeschw. [km/h]": round(d["v_kmh"].max(), 2),
            "Aufstieg [m]": round(self.hoehenmeter_aufstieg, 1),
            "Abstieg [m]": round(self.hoehenmeter_abstieg, 1),
            "Min. Seehoehe [m]": round(d["ele"].min(), 1),
            "Max. Seehoehe [m]": round(d["ele"].max(), 1),
            "Max. Steigung [%]": round(d["steigung_prozent"].max(), 1),
            "Max. Gefaelle [%]": round(d["steigung_prozent"].min(), 1),
            "Mittlere Temperatur [C]": round(d["temperature"].mean(), 1),
            "Haupt-Himmelsrichtung": d["himmelsrichtung"].mode().iloc[0],
        }

    def __repr__(self) -> str:
        return (f"Track(punkte={len(self.daten)}, "
                f"distanz={self.gesamtdistanz_km:.1f} km)")
