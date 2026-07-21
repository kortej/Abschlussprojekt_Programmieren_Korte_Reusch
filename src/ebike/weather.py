"""Abfrage historischer Wetterdaten (Erweiterung "Wetterdaten & Wind").

Verwendet die kostenlosen und schluessellosen APIs von Open-Meteo. Je nach
Alter der Aufzeichnung wird automatisch der passende Endpunkt gewaehlt:

* Forecast-API   https://open-meteo.com/en/docs
  `api.open-meteo.com/v1/forecast` - Vorhersage und Rueckblick, laut
  Dokumentation ueber `past_days` bis maximal 92 Tage in die Vergangenheit.
* Archiv-API     https://open-meteo.com/en/docs/historical-weather-api
  `archive-api.open-meteo.com/v1/archive` - Reanalyse-Daten fuer weiter
  zurueckliegende Zeitraeume.

Beide Endpunkte erwarten dieselben Parameter und liefern dasselbe
JSON-Format (`hourly` mit `time` und den angeforderten Groessen), sodass die
Auswertung identisch ist. Schlaegt der gewaehlte Endpunkt fehl, wird der
jeweils andere als Ausweichweg versucht.

Die Daten werden lokal als JSON zwischengespeichert (Cache). Der Cache
enthaelt zusaetzlich die Metadaten der Anfrage (Koordinaten, Start- und
Enddatum). Passen sie nicht zur aktuellen Fahrt, wird der Cache verworfen und
neu abgefragt - sonst wuerden bei einer anderen Strecke die alten Wetterdaten
weiterverwendet.

Abgefragt wird ausschliesslich der Tag der Aufzeichnung: Start- und Enddatum
stammen aus dem ersten und letzten Messpunkt der Fahrt, fuer die
mitgelieferten Daten also einmal der 23.08.2024.

Fuer die Abfrage selbst gibt es zwei Wege. Ist das offizielle SDK
(`openmeteo-requests`) installiert, wird es bevorzugt; andernfalls wird der
Endpunkt direkt mit `requests` abgefragt. Beide Wege erzeugen dieselbe
Datenstruktur, sodass Cache, Pruefung und Auswertung identisch bleiben.

Ohne Internetverbindung faellt das Programm automatisch auf Standardwerte
zurueck; die Simulation laeuft dann trotzdem durch. Ob echte API-Daten oder
Offline-Werte verwendet wurden, ist ueber `echte_api_daten` erkennbar und
wird auch im Bericht ausgewiesen.
"""

import json
import logging
import os
from datetime import datetime

import pandas as pd
import requests

from .environment import Wind

logger = logging.getLogger(__name__)

# Das offizielle Open-Meteo-SDK (`openmeteo-requests`) ist optional. Ist es
# installiert, wird es bevorzugt: es spricht das FlatBuffers-Format der API,
# bringt ueber `requests-cache` und `retry-requests` einen HTTP-Cache sowie
# automatische Wiederholungsversuche mit und liefert die Werte direkt als
# NumPy-Arrays. Fehlt eines der Pakete, laeuft alles unveraendert ueber
# `requests` - das Projekt bleibt also ohne Zusatzpakete lauffaehig.
try:
    import openmeteo_requests
    import requests_cache
    from retry_requests import retry

    SDK_VERFUEGBAR = True
except ImportError:  # pragma: no cover - haengt von der Installation ab
    SDK_VERFUEGBAR = False

# Endpunkt fuer aktuelle und wenige Wochen alte Zeitraeume (siehe Doku oben)
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"
# Endpunkt fuer weiter zurueckliegende Zeitraeume
ARCHIV_API_URL = "https://archive-api.open-meteo.com/v1/archive"

# Die Forecast-API erlaubt laut Dokumentation `past_days` bis 92 Tage. Mit
# etwas Sicherheitsabstand wird ab 85 Tagen das Archiv verwendet.
MAX_RUECKBLICK_TAGE_FORECAST = 85

# Stuendlich abgefragte Groessen - Reihenfolge ist wichtig, weil das SDK die
# Variablen in Anfragereihenfolge zurueckliefert und ueber den Index
# zugeordnet werden muss.
HOURLY_FELDER = ["temperature_2m", "wind_speed_10m", "wind_direction_10m",
                 "surface_pressure", "relative_humidity_2m"]

# Diese Felder muss eine gueltige Antwort enthalten
PFLICHTFELDER = ("time", "wind_speed_10m", "wind_direction_10m", "temperature_2m")


class WetterService:
    """Holt stuendliche Wetterdaten fuer Ort und Zeitraum der Fahrt."""

    def __init__(self, cache_datei: str = "output/wetter_cache.json",
                 timeout_s: float = 10.0, sdk_verwenden: bool = True,
                 http_cache_dauer_s: int = 3600):
        self.cache_datei = cache_datei
        self.timeout_s = timeout_s
        # Nur wirksam, wenn `openmeteo-requests` auch installiert ist
        self.sdk_verwenden = sdk_verwenden
        self.http_cache_dauer_s = http_cache_dauer_s
        self.daten: pd.DataFrame | None = None
        self.quelle = "nicht geladen"
        # True, wenn tatsaechlich Daten der API (bzw. eines dazu passenden
        # Caches) verwendet werden - sonst wird offline gerechnet.
        self.echte_api_daten = False

    # -- Cache -------------------------------------------------------------
    @staticmethod
    def metadaten(latitude: float, longitude: float,
                  start: datetime, ende: datetime) -> dict:
        """Beschreibt, fuer welche Anfrage ein Datensatz gilt."""
        return {
            "latitude": round(latitude, 4),
            "longitude": round(longitude, 4),
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": ende.strftime("%Y-%m-%d"),
        }

    def _lade_cache(self, erwartet: dict | None = None) -> dict | None:
        """Liest den Cache und prueft, ob er zur aktuellen Anfrage passt.

        Args:
            erwartet: Metadaten der aktuellen Anfrage. Stimmen sie nicht mit
                den gespeicherten ueberein, gilt der Cache als ungueltig.

        Returns:
            Die gespeicherten Rohdaten oder None.
        """
        if not os.path.exists(self.cache_datei):
            return None
        try:
            with open(self.cache_datei, "r", encoding="utf-8") as f:
                inhalt = json.load(f)
        except (OSError, json.JSONDecodeError) as fehler:
            logger.warning("Wetter-Cache konnte nicht gelesen werden: %s", fehler)
            return None

        if not isinstance(inhalt, dict):
            return None
        gespeichert = inhalt.get("_anfrage")
        rohdaten = inhalt.get("_daten")
        if gespeichert is None or rohdaten is None:
            logger.info("Wetter-Cache ohne Metadaten - wird verworfen.")
            return None
        if erwartet is not None and gespeichert != erwartet:
            logger.info("Wetter-Cache gilt fuer eine andere Anfrage "
                        "(%s statt %s) - es wird neu abgefragt.",
                        gespeichert, erwartet)
            return None
        return rohdaten

    def _schreibe_cache(self, rohdaten: dict, metadaten: dict) -> None:
        """Speichert Rohdaten gemeinsam mit den Metadaten der Anfrage."""
        try:
            os.makedirs(os.path.dirname(self.cache_datei) or ".", exist_ok=True)
            with open(self.cache_datei, "w", encoding="utf-8") as f:
                json.dump({"_anfrage": metadaten, "_daten": rohdaten}, f)
        except OSError as fehler:
            logger.warning("Wetter-Cache konnte nicht geschrieben werden: %s", fehler)

    @staticmethod
    def antwort_gueltig(rohdaten) -> bool:
        """Prueft die Struktur einer API-Antwort.

        Gecacht wird erst nach dieser Pruefung - sonst wuerde eine fehlerhafte
        Antwort dauerhaft gespeichert und bei jedem Start wiederverwendet.
        """
        if not isinstance(rohdaten, dict):
            return False
        stunden = rohdaten.get("hourly")
        if not isinstance(stunden, dict):
            return False
        if any(feld not in stunden for feld in PFLICHTFELDER):
            return False
        return bool(stunden.get("time"))

    # -- Abfrage ueber das offizielle SDK ----------------------------------
    def _sdk_client(self):
        """Baut den SDK-Client mit HTTP-Cache und Wiederholungsversuchen."""
        sitzung = requests_cache.CachedSession(
            os.path.join(os.path.dirname(self.cache_datei) or ".",
                         "openmeteo_http_cache"),
            expire_after=self.http_cache_dauer_s)
        # retry_requests.retry() erwartet die Sitzung als erstes Argument -
        # nicht als Dekorator um die Sitzung herum.
        sitzung = retry(sitzung, retries=5, backoff_factor=0.2)
        return openmeteo_requests.Client(session=sitzung)

    @staticmethod
    def _sdk_antwort_umwandeln(antwort, felder: list[str]) -> dict:
        """Uebersetzt die FlatBuffers-Antwort in dasselbe Format wie die JSON-API.

        Dadurch bleiben Cache, Pruefung und Auswertung fuer beide Wege gleich.
        Die Variablen kommen in der Reihenfolge zurueck, in der sie angefragt
        wurden; deshalb wird ueber den Index zugeordnet.

        Args:
            antwort: Antwortobjekt des SDK fuer einen Ort.
            felder: Angefragte stuendliche Groessen in Anfragereihenfolge.

        Returns:
            dict der Form {"hourly": {"time": [...], "<feld>": [...]}}.
        """
        stunden = antwort.Hourly()
        zeitpunkte = pd.date_range(
            start=pd.to_datetime(stunden.Time(), unit="s", utc=True),
            end=pd.to_datetime(stunden.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=stunden.Interval()),
            inclusive="left")

        ergebnis = {"time": [z.strftime("%Y-%m-%dT%H:%M") for z in zeitpunkte]}
        for index, feld in enumerate(felder):
            werte = stunden.Variables(index).ValuesAsNumpy()
            ergebnis[feld] = [float(w) for w in werte]
        return {"hourly": ergebnis}

    def _abfragen_sdk(self, parameter: dict, url: str, felder: list[str]
                      ) -> dict | None:
        """Fragt einen Endpunkt ueber das SDK ab.

        Returns:
            Rohdaten im JSON-Format der API oder None bei Misserfolg.
        """
        sdk_parameter = dict(parameter)
        # Das SDK erwartet die stuendlichen Groessen als Liste, nicht als
        # kommagetrennten String.
        sdk_parameter["hourly"] = felder
        antworten = self._sdk_client().weather_api(url, params=sdk_parameter)
        if not antworten:
            raise ValueError("leere Antwort")
        return self._sdk_antwort_umwandeln(antworten[0], felder)

    # -- Abfrage -----------------------------------------------------------
    @staticmethod
    def endpunkte_fuer(ende: datetime, heute: datetime | None = None
                       ) -> list[tuple[str, str]]:
        """Waehlt die Reihenfolge der Endpunkte nach dem Alter der Fahrt.

        Die Forecast-API deckt laut Dokumentation nur die letzten 92 Tage ab.
        Fuer aeltere Aufzeichnungen ist die Archiv-API zustaendig. Der jeweils
        andere Endpunkt bleibt als Ausweichweg in der Liste, weil die Grenze
        zwischen beiden nicht exakt festliegt.

        Args:
            ende: Zeitpunkt des letzten Messpunktes der Fahrt.
            heute: Referenzzeitpunkt (nur fuer Tests uebergeben).

        Returns:
            Liste aus (Name, URL) in der Reihenfolge, in der abgefragt wird.
        """
        heute = heute or datetime.now(tz=ende.tzinfo)
        alter_tage = (heute - ende).days
        forecast = ("Forecast-API", FORECAST_API_URL)
        archiv = ("Archiv-API", ARCHIV_API_URL)
        if alter_tage <= MAX_RUECKBLICK_TAGE_FORECAST:
            return [forecast, archiv]
        return [archiv, forecast]

    def _abfragen(self, parameter: dict, ende: datetime, felder: list[str]
                  ) -> tuple[dict | None, str]:
        """Fragt die Endpunkte der Reihe nach ab, bis einer gueltig antwortet.

        Pro Endpunkt wird zuerst das SDK versucht (falls installiert), danach
        der direkte `requests`-Weg.

        Returns:
            (Rohdaten, Beschreibung des Weges) oder (None, "") bei Misserfolg.
        """
        letzter_fehler = "kein Endpunkt erreichbar"

        for name, url in self.endpunkte_fuer(ende):
            parameter_endpunkt = dict(parameter)
            if name == "Forecast-API":
                # Die Forecast-API liefert ohne diese Angabe nur die Zukunft
                parameter_endpunkt["past_days"] = 92

            wege = []
            if SDK_VERFUEGBAR and self.sdk_verwenden:
                wege.append(("SDK", lambda p=parameter_endpunkt, u=url:
                             self._abfragen_sdk(p, u, felder)))
            wege.append(("requests", lambda p=parameter_endpunkt, u=url:
                         self._abfragen_requests(p, u)))

            for weg, abfrage in wege:
                try:
                    logger.info("Frage Wetterdaten von Open-Meteo ab "
                                "(%s, %s) ...", name, weg)
                    rohdaten = abfrage()
                except Exception as fehler:  # SDK wirft eigene Fehlertypen
                    letzter_fehler = str(fehler)
                    logger.warning("%s ueber %s nicht verwendbar (%s)",
                                   name, weg, fehler)
                    continue

                if not self.antwort_gueltig(rohdaten):
                    letzter_fehler = "unvollstaendige Antwort"
                    logger.warning("Antwort der %s (%s) ist unvollstaendig.",
                                   name, weg)
                    continue

                return rohdaten, f"{name} ({weg})"

        logger.warning("Wetterabfrage fehlgeschlagen (%s). "
                       "Es werden Standardwerte verwendet.", letzter_fehler)
        self.quelle = "Standardwerte (offline)"
        self.echte_api_daten = False
        return None, ""

    def _abfragen_requests(self, parameter: dict, url: str) -> dict:
        """Fragt einen Endpunkt direkt ueber `requests` ab (ohne SDK)."""
        parameter_json = dict(parameter)
        parameter_json["hourly"] = ",".join(HOURLY_FELDER)
        antwort = requests.get(url, params=parameter_json, timeout=self.timeout_s)
        antwort.raise_for_status()
        return antwort.json()

    def hole_daten(self, latitude: float, longitude: float,
                   start: datetime, ende: datetime,
                   cache_verwenden: bool = True) -> pd.DataFrame | None:
        """Laedt Wind, Temperatur und Luftdruck fuer den Fahrtzeitraum.

        Returns:
            DataFrame mit stuendlichen Werten oder None, falls keine Daten
            verfuegbar sind (z.B. ohne Internetverbindung).
        """
        anfrage = self.metadaten(latitude, longitude, start, ende)
        rohdaten = self._lade_cache(anfrage) if cache_verwenden else None

        if rohdaten is not None:
            self.quelle = "Cache (Open-Meteo)"
            self.echte_api_daten = True
            logger.info("Wetterdaten aus dem lokalen Cache geladen")
        else:
            parameter = dict(anfrage)
            parameter["timezone"] = "UTC"

            rohdaten, endpunkt = self._abfragen(parameter, ende, HOURLY_FELDER)
            if rohdaten is None:
                return None

            self._schreibe_cache(rohdaten, anfrage)
            self.quelle = f"Open-Meteo {endpunkt}"
            self.echte_api_daten = True

        try:
            df = pd.DataFrame(rohdaten["hourly"])
            df["time"] = pd.to_datetime(df["time"], utc=True)
        except (KeyError, TypeError, ValueError) as fehler:
            logger.warning("Wetterdaten haben ein unerwartetes Format: %s", fehler)
            self.quelle = "Standardwerte (fehlerhafte Antwort)"
            self.echte_api_daten = False
            return None

        self.daten = df
        return df

    # -- Auswertung --------------------------------------------------------
    def wind_zum_zeitpunkt(self, zeitpunkt) -> Wind:
        """Gibt den Wind zum naechstgelegenen Stundenwert zurueck.

        Ohne geladene Daten wird Windstille angenommen.
        """
        if self.daten is None or self.daten.empty:
            return Wind(0.0, 0.0)
        index = (self.daten["time"] - zeitpunkt).abs().idxmin()
        zeile = self.daten.loc[index]
        # Open-Meteo liefert die Windgeschwindigkeit in km/h
        return Wind(geschwindigkeit_ms=float(zeile["wind_speed_10m"]) / 3.6,
                    richtung_grad=float(zeile["wind_direction_10m"]))

    def luftfeuchte_zum_zeitpunkt(self, zeitpunkt) -> float:
        """Relative Luftfeuchte (0..1) zum naechstgelegenen Stundenwert."""
        if self.daten is None or self.daten.empty:
            return 0.5
        index = (self.daten["time"] - zeitpunkt).abs().idxmin()
        return float(self.daten.loc[index, "relative_humidity_2m"]) / 100.0

    def zusammenfassung(self) -> dict:
        """Kennzahlen des Wetters waehrend der Fahrt."""
        if self.daten is None or self.daten.empty:
            return {"Wetterquelle": self.quelle, "Echte API-Daten": "nein"}
        return {
            "Wetterquelle": self.quelle,
            "Echte API-Daten": "ja" if self.echte_api_daten else "nein",
            "Mittlerer Wind [km/h]": round(self.daten["wind_speed_10m"].mean(), 1),
            "Max. Wind [km/h]": round(self.daten["wind_speed_10m"].max(), 1),
            "Mittlere Windrichtung [Grad]": round(
                self.daten["wind_direction_10m"].mean(), 0),
            "Mittlere Lufttemperatur [C]": round(
                self.daten["temperature_2m"].mean(), 1),
        }
