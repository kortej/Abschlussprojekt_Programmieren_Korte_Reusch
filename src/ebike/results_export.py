"""Export der Ergebnisse als JSON/CSV und Aktualisierung des README.

Bisher standen die Zahlenwerte im README fest im Text. Nach jeder Aenderung
am Modell stimmten sie nicht mehr mit den tatsaechlich erzeugten Ergebnissen
ueberein. Dieses Modul schreibt die Kennzahlen eines Laufs einmal zentral
nach `output/ergebnisse.json` und traegt sie anschliessend automatisch in das
README ein. Dort ist dafuer ein markierter Bereich vorgesehen:

    <!-- ERGEBNISSE:START -->
    ... automatisch erzeugt ...
    <!-- ERGEBNISSE:ENDE -->

Damit koennen README, Bericht und Simulation nicht mehr auseinanderlaufen.
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

START_MARKE = "<!-- ERGEBNISSE:START -->"
ENDE_MARKE = "<!-- ERGEBNISSE:ENDE -->"


def sammle_ergebnisse(track, ergebnisse: dict, wetter: dict,
                      kapazitaet: dict | None = None,
                      kleinste_konfiguration: dict | None = None) -> dict:
    """Fasst alle Kennzahlen eines Laufs in einem Dictionary zusammen.

    Args:
        track: der ausgewertete `Track`.
        ergebnisse: Dictionary {Akkuname: SimulationsErgebnis}.
        wetter: Kennzahlen des Wetters.
        kapazitaet: Ergebnis von `notwendige_kapazitaet()`.
        kleinste_konfiguration: Ergebnis der automatischen Suche.

    Returns:
        Serialisierbares Dictionary mit allen Kennzahlen.
    """
    return {
        "erzeugt_am": datetime.now().isoformat(timespec="seconds"),
        "fahrt": track.zusammenfassung(),
        "akkus": {name: erg.kennzahlen() for name, erg in ergebnisse.items()},
        "wetter": wetter or {},
        "kapazitaet": kapazitaet or {},
        "kleinste_konfiguration": kleinste_konfiguration or {},
    }


def speichere_json(daten: dict, ausgabeordner: str = "output",
                   dateiname: str = "ergebnisse.json") -> str:
    """Schreibt die gesammelten Ergebnisse als JSON.

    Returns:
        Pfad zur erzeugten Datei.
    """
    os.makedirs(ausgabeordner, exist_ok=True)
    pfad = os.path.join(ausgabeordner, dateiname)
    with open(pfad, "w", encoding="utf-8") as datei:
        json.dump(daten, datei, ensure_ascii=False, indent=2, default=str)
    logger.info("Ergebnisse gespeichert: %s", pfad)
    return pfad


def _markdown_tabelle(titel: str, werte: dict) -> str:
    """Baut eine zweispaltige Markdown-Tabelle aus einem Dictionary."""
    zeilen = [f"**{titel}**", "", "| Groesse | Wert |", "| --- | --- |"]
    zeilen += [f"| {k} | {v} |" for k, v in werte.items() if v is not None]
    zeilen.append("")
    return "\n".join(zeilen)


def als_markdown(daten: dict) -> str:
    """Erzeugt den Markdown-Block fuer das README."""
    teile = [
        "_Dieser Abschnitt wird von `main.py` automatisch aus "
        "`output/ergebnisse.json` erzeugt. Bitte nicht von Hand aendern._",
        "",
        f"Letzter Lauf: {daten.get('erzeugt_am', 'unbekannt')}",
        "",
        _markdown_tabelle("Kenngroessen der Fahrt", daten.get("fahrt", {})),
    ]
    for name, kennzahlen in daten.get("akkus", {}).items():
        teile.append(_markdown_tabelle(f"Simulation mit {name}-Akku", kennzahlen))
    if daten.get("kapazitaet"):
        teile.append(_markdown_tabelle("Notwendige Akkukapazitaet",
                                       daten["kapazitaet"]))
    if daten.get("kleinste_konfiguration"):
        teile.append(_markdown_tabelle("Kleinste ausreichende Konfiguration",
                                       daten["kleinste_konfiguration"]))
    if daten.get("wetter"):
        teile.append(_markdown_tabelle("Wetter", daten["wetter"]))
    return "\n".join(teile)


def aktualisiere_readme(daten: dict, readme_pfad: str) -> bool:
    """Traegt die Ergebnisse in den markierten Bereich des README ein.

    Args:
        daten: Ergebnis von `sammle_ergebnisse()`.
        readme_pfad: Pfad zur README-Datei.

    Returns:
        True, wenn das README aktualisiert wurde.
    """
    if not os.path.exists(readme_pfad):
        logger.warning("README nicht gefunden: %s", readme_pfad)
        return False

    with open(readme_pfad, "r", encoding="utf-8") as datei:
        inhalt = datei.read()

    if START_MARKE not in inhalt or ENDE_MARKE not in inhalt:
        logger.warning("Im README fehlen die Marken %s / %s - "
                       "die Ergebnisse wurden nicht eingetragen.",
                       START_MARKE, ENDE_MARKE)
        return False

    vorher = inhalt.split(START_MARKE)[0]
    nachher = inhalt.split(ENDE_MARKE)[1]
    neu = (f"{vorher}{START_MARKE}\n\n{als_markdown(daten)}\n"
           f"{ENDE_MARKE}{nachher}")

    with open(readme_pfad, "w", encoding="utf-8") as datei:
        datei.write(neu)
    logger.info("README aktualisiert: %s", readme_pfad)
    return True
