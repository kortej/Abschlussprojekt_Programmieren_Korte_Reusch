"""Darstellung der Strecke auf einer interaktiven Karte (folium).

Erzeugt eine HTML-Datei, die man im Browser oeffnen kann. Die Strecke wird
nach Geschwindigkeit oder Ladezustand eingefaerbt, Start, Ziel und die per
Reverse Geocoding bestimmten Orte werden als Marker eingezeichnet.
"""

import logging
import os

import folium
import numpy as np

logger = logging.getLogger(__name__)


class StreckenKarte:
    """Baut eine folium-Karte aus einem Simulationsergebnis."""

    def __init__(self, daten, ausgabeordner: str = "output"):
        """
        Args:
            daten: DataFrame mit den Spalten lat, lon, v_kmh, soc, ele_m.
        """
        if daten.empty:
            raise ValueError("Fuer die Karte werden Streckendaten benoetigt.")
        self.daten = daten
        self.ordner = ausgabeordner
        os.makedirs(self.ordner, exist_ok=True)

    @staticmethod
    def _farbe(wert: float, minimum: float, maximum: float) -> str:
        """Ordnet einem Wert eine Farbe von blau (klein) bis rot (gross) zu."""
        if maximum <= minimum:
            return "#3388ff"
        anteil = (wert - minimum) / (maximum - minimum)
        anteil = float(np.clip(anteil, 0.0, 1.0))
        rot = int(255 * anteil)
        blau = int(255 * (1 - anteil))
        return f"#{rot:02x}40{blau:02x}"

    def erzeuge(self, dateiname: str = "strecke.html",
                farbgroesse: str = "v_kmh",
                wegpunkte: list | None = None,
                schrittweite: int = 3) -> str:
        """Erzeugt die Karte und speichert sie als HTML.

        Args:
            farbgroesse: Spalte, nach der die Strecke eingefaerbt wird.
            wegpunkte: optionale Liste geocodierter Orte fuer Marker.
            schrittweite: nur jeder n-te Punkt wird gezeichnet (kleinere Datei).

        Returns:
            Pfad zur erzeugten HTML-Datei.
        """
        d = self.daten.iloc[::schrittweite].reset_index(drop=True)
        if farbgroesse not in d.columns:
            raise ValueError(f"Die Spalte '{farbgroesse}' existiert nicht.")

        mitte = [d["lat"].mean(), d["lon"].mean()]
        karte = folium.Map(location=mitte, zoom_start=13, tiles="OpenStreetMap")

        werte = d[farbgroesse]
        minimum, maximum = float(werte.min()), float(werte.max())

        # Strecke in kurzen, einzeln eingefaerbten Segmenten zeichnen
        for i in range(1, len(d)):
            folium.PolyLine(
                locations=[[d.loc[i - 1, "lat"], d.loc[i - 1, "lon"]],
                           [d.loc[i, "lat"], d.loc[i, "lon"]]],
                color=self._farbe(float(werte.iloc[i]), minimum, maximum),
                weight=4, opacity=0.85,
            ).add_to(karte)

        folium.Marker(
            [d["lat"].iloc[0], d["lon"].iloc[0]],
            popup="Start", icon=folium.Icon(color="green", icon="play"),
        ).add_to(karte)
        folium.Marker(
            [d["lat"].iloc[-1], d["lon"].iloc[-1]],
            popup="Ziel", icon=folium.Icon(color="red", icon="stop"),
        ).add_to(karte)

        if wegpunkte:
            for punkt in wegpunkte[1:-1]:
                folium.CircleMarker(
                    [punkt["lat"], punkt["lon"]],
                    radius=6, color="black", fill=True, fill_color="orange",
                    fill_opacity=0.9,
                    popup=f"{punkt['ort']} (km {punkt['distanz_km']:.1f})",
                ).add_to(karte)

        legende = (f'<div style="position: fixed; bottom: 30px; left: 30px; '
                   f'z-index: 9999; background: white; padding: 8px; '
                   f'border: 1px solid grey; font-family: sans-serif; font-size: 12px;">'
                   f'<b>Einfaerbung: {farbgroesse}</b><br>'
                   f'blau = {minimum:.1f} &nbsp; rot = {maximum:.1f}</div>')
        karte.get_root().html.add_child(folium.Element(legende))

        pfad = os.path.join(self.ordner, dateiname)
        karte.save(pfad)
        logger.info("Karte gespeichert: %s", pfad)
        return pfad
