"""Reverse Geocoding: GPS-Koordinaten zu Ortsnamen.

Erweiterung "Nutzen einer API um die GPS-Koordinaten in Adressen/Orte
umzuwandeln". Verwendet wird Nominatim (OpenStreetMap).

Wichtig: Nominatim erlaubt laut Nutzungsbedingungen maximal eine Anfrage pro
Sekunde und verlangt einen aussagekraeftigen User-Agent. Beides ist hier
umgesetzt. Zusaetzlich werden die Ergebnisse in einer JSON-Datei
zwischengespeichert, damit wiederholte Programmlaeufe die API nicht belasten.
"""

import json
import logging
import os
import time

import numpy as np
import requests

logger = logging.getLogger(__name__)

GEOCODING_API_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "MCI-EBike-Abschlussprojekt/1.0 (Lehrveranstaltungsprojekt)"


class GeocodingService:
    """Wandelt Koordinaten in lesbare Ortsnamen um."""

    def __init__(self, cache_datei: str = "output/geocoding_cache.json",
                 pause_s: float = 1.1, timeout_s: float = 10.0):
        self.cache_datei = cache_datei
        self.pause_s = pause_s
        self.timeout_s = timeout_s
        self.cache = self._lade_cache()
        self.api_aufrufe = 0
        self.fehlversuche = 0

    # -- Cache -------------------------------------------------------------
    def _lade_cache(self) -> dict:
        if os.path.exists(self.cache_datei):
            try:
                with open(self.cache_datei, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                logger.warning("Geocoding-Cache unlesbar, wird neu angelegt.")
        return {}

    def _speichere_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_datei) or ".", exist_ok=True)
            with open(self.cache_datei, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except OSError as fehler:
            logger.warning("Geocoding-Cache konnte nicht gespeichert werden: %s", fehler)

    # -- Abfrage -----------------------------------------------------------
    def ort(self, latitude: float, longitude: float) -> str:
        """Gibt einen kurzen Ortsnamen fuer die Koordinate zurueck.

        Bei Fehlern (kein Internet, Zeitueberschreitung) wird ein Platzhalter
        mit den Koordinaten zurueckgegeben, damit das Programm weiterlaeuft.
        """
        schluessel = f"{latitude:.4f},{longitude:.4f}"
        if schluessel in self.cache:
            return self.cache[schluessel]

        parameter = {
            "lat": latitude,
            "lon": longitude,
            "format": "jsonv2",
            "zoom": 14,
            "accept-language": "de",
        }
        try:
            antwort = requests.get(GEOCODING_API_URL, params=parameter,
                                   headers={"User-Agent": USER_AGENT},
                                   timeout=self.timeout_s)
            antwort.raise_for_status()
            inhalt = antwort.json()
            self.api_aufrufe += 1
            time.sleep(self.pause_s)  # Rate-Limit von Nominatim einhalten
            name = self._kurzname(inhalt)
        except (requests.RequestException, ValueError) as fehler:
            # Fehlversuche werden bewusst nicht gespeichert, damit beim
            # naechsten Programmstart erneut abgefragt werden kann.
            self.fehlversuche += 1
            logger.warning("Reverse Geocoding fehlgeschlagen: %s", fehler)
            return f"{latitude:.3f}, {longitude:.3f}"

        self.cache[schluessel] = name
        self._speichere_cache()
        return name

    @staticmethod
    def _kurzname(antwort: dict) -> str:
        """Sucht aus der Nominatim-Antwort einen moeglichst kurzen Ortsnamen."""
        adresse = antwort.get("address", {})
        for schluessel in ("village", "town", "city", "hamlet", "suburb",
                           "municipality", "county"):
            if schluessel in adresse:
                return adresse[schluessel]
        return antwort.get("display_name", "Unbekannt").split(",")[0]

    def orte_entlang_strecke(self, daten, anzahl: int = 8) -> list[dict]:
        """Bestimmt Ortsnamen fuer gleichmaessig verteilte Punkte der Strecke.

        Args:
            daten: DataFrame des Tracks (mit Spalten lat, lon, distanz_m, t_s).
            anzahl: Anzahl der abzufragenden Wegpunkte.

        Returns:
            Liste von Dictionaries mit lat, lon, ort, distanz_km, t_s.
        """
        if anzahl < 2:
            raise ValueError("Es werden mindestens zwei Wegpunkte benoetigt.")

        indizes = [int(i) for i in (len(daten) - 1) * np.linspace(0, 1, anzahl)]
        ergebnis = []
        for i in indizes:
            zeile = daten.iloc[i]
            ergebnis.append({
                "lat": float(zeile["lat"]),
                "lon": float(zeile["lon"]),
                "ort": self.ort(float(zeile["lat"]), float(zeile["lon"])),
                "distanz_km": float(zeile["distanz_m"]) / 1000.0,
                "t_s": float(zeile["t_s"]),
            })
        if self.fehlversuche:
            logger.warning("%d von %d Geocoding-Abfragen sind fehlgeschlagen - "
                           "fuer diese Punkte werden Koordinaten angezeigt.",
                           self.fehlversuche, len(ergebnis))
        logger.info("%d Wegpunkte geocodiert (%d API-Aufrufe, %d Fehlversuche)",
                    len(ergebnis), self.api_aufrufe, self.fehlversuche)
        return ergebnis

    @property
    def erfolgreich(self) -> bool:
        """True, wenn mindestens ein Ort tatsaechlich aufgeloest wurde."""
        return bool(self.cache) and self.fehlversuche == 0
