"""Akkumodell.

Grundlage ist das Modell aus der Uebung "2. Einfuehrung in die OOP":
Der Akku wird als ideale Spannungsquelle mit Innenwiderstand modelliert.

    SoC_(k+1) = SoC_k - I * dt / C_nom
    SoC       = max(0, min(1, SoC))
    U_OC      = U_min + SoC * (U_max - U_min)      (linear, Basismodell)
    U         = U_OC - R_int * I

Erweiterungen dieses Projekts:
* `LiPoAkku` und `NmcAkku` erben von `BatteryPack` und ersetzen die lineare
  Kennlinie durch die in der Angabe gegebenen Messpunkte (Interpolation).
* `ThermischesModell` simuliert die Akkutemperatur; der Innenwiderstand
  steigt bei Kaelte an und verringert dadurch die nutzbare Leistung.
"""

import logging

import numpy as np

from .config import BatteryConfig

logger = logging.getLogger(__name__)


class ThermischesModell:
    """Einfaches Ein-Knoten-Waermemodell des Akkupacks.

    Der Akku erwaermt sich durch die ohmschen Verluste P = I^2 * R_int und
    kuehlt proportional zur Temperaturdifferenz zur Umgebung ab:

        C_th * dT/dt = I^2 * R_int - k * (T - T_umgebung)
    """

    def __init__(self, starttemperatur_c: float = 20.0,
                 waermekapazitaet_j_per_k: float = 45000.0,
                 waermeuebergang_w_per_k: float = 3.0):
        if waermekapazitaet_j_per_k <= 0:
            raise ValueError("Die Waermekapazitaet muss groesser als 0 sein.")
        self.temperatur_c = starttemperatur_c
        self.waermekapazitaet = waermekapazitaet_j_per_k
        self.waermeuebergang = waermeuebergang_w_per_k

    def update(self, verlustleistung_w: float, umgebungstemperatur_c: float,
               dauer_s: float) -> float:
        """Rechnet die Akkutemperatur einen Zeitschritt weiter."""
        if dauer_s <= 0:
            return self.temperatur_c
        netto_w = (verlustleistung_w
                   - self.waermeuebergang * (self.temperatur_c - umgebungstemperatur_c))
        self.temperatur_c += netto_w * dauer_s / self.waermekapazitaet
        return self.temperatur_c

    def __repr__(self) -> str:
        return f"ThermischesModell(T={self.temperatur_c:.1f} C)"


class BatteryPack:
    """Basisklasse fuer einen Akkupack (Modell aus der OOP-Uebung).

    Die Bezeichner der Methoden entsprechen der Uebungsangabe
    (`apply_current`, `voltage`, `is_empty`), damit das Modell direkt
    wiederverwendet werden kann.
    """

    name = "Generisch"

    def __init__(self,
                 capacity_nom_Ah: float,
                 internal_resistance_mOhm: float = 80.0,
                 initial_soc: float = 1.0,
                 Vmin: float = 32.0,
                 Vmax: float = 42.0,
                 thermisches_modell: ThermischesModell | None = None,
                 temperaturkoeffizient_ri: float = 0.0,
                 referenztemperatur_c: float = 25.0):
        if capacity_nom_Ah <= 0:
            raise ValueError("Die Nennkapazitaet muss groesser als 0 sein.")
        if not 0.0 <= initial_soc <= 1.0:
            raise ValueError("Der Start-SoC muss zwischen 0 und 1 liegen.")
        if Vmin >= Vmax:
            raise ValueError("Vmin muss kleiner als Vmax sein.")

        self.capacity_nom_Ah = capacity_nom_Ah
        self.capacity_nom_As = capacity_nom_Ah * 3600.0  # Umrechnung in Amperesekunden
        self.internal_resistance = internal_resistance_mOhm / 1000.0  # in Ohm
        self.soc = initial_soc
        self.Vmin = Vmin
        self.Vmax = Vmax

        self.thermisches_modell = thermisches_modell
        self.temperaturkoeffizient_ri = temperaturkoeffizient_ri
        self.referenztemperatur_c = referenztemperatur_c

        # Wird vom Simulator vor jedem Zeitschritt aktualisiert
        self.umgebungstemperatur_c = 20.0

        # Zaehler fuer die Auswertung
        self.entladene_ladung_As = 0.0
        self.geladene_ladung_As = 0.0

    # -- Kennlinie ---------------------------------------------------------
    def open_circuit_voltage(self, soc: float | None = None) -> float:
        """Leerlaufspannung U_OC. Basismodell: linear zwischen Vmin und Vmax."""
        s = self.soc if soc is None else soc
        return self.Vmin + s * (self.Vmax - self.Vmin)

    def aktueller_innenwiderstand(self) -> float:
        """Innenwiderstand in Ohm, ggf. temperaturabhaengig.

        Bei kaltem Akku steigt der Innenwiderstand, dadurch bricht die
        Spannung unter Last staerker ein und es geht mehr Energie verloren.
        """
        if self.thermisches_modell is None or self.temperaturkoeffizient_ri == 0.0:
            return self.internal_resistance
        delta_t = self.referenztemperatur_c - self.thermisches_modell.temperatur_c
        faktor = 1.0 + self.temperaturkoeffizient_ri * delta_t
        return self.internal_resistance * max(faktor, 0.5)

    # -- Kernmethoden aus der Uebung ---------------------------------------
    def voltage(self, current: float = 0.0) -> float:
        """Klemmenspannung unter Last: U = U_OC - R_int * I.

        Args:
            current: Strom in Ampere. Positiv = Entladen, negativ = Laden.
        """
        return self.open_circuit_voltage() - self.aktueller_innenwiderstand() * current

    def moegliche_dauer(self, current: float, duration: float) -> float:
        """Dauer, fuer die der Strom tatsaechlich fliessen kann.

        Wird der Akku innerhalb des Zeitschritts leer (oder beim Laden voll),
        darf nur der entsprechende Bruchteil des Zeitschritts gerechnet
        werden. Sonst wuerde mehr Ladung entnommen bzw. eingespeichert, als
        physikalisch moeglich ist, und die Ladungszaehler waeren zu gross.

        Args:
            current: Strom in Ampere (positiv = Entladen).
            duration: gewuenschte Dauer in Sekunden.

        Returns:
            Die tatsaechlich moegliche Dauer in Sekunden (0 .. duration).
        """
        if duration <= 0 or current == 0.0:
            return max(duration, 0.0)
        if current > 0:
            verfuegbar_As = self.soc * self.capacity_nom_As
            return min(duration, max(verfuegbar_As / current, 0.0))
        aufnehmbar_As = (1.0 - self.soc) * self.capacity_nom_As
        return min(duration, max(aufnehmbar_As / abs(current), 0.0))

    def apply_current(self, current: float, duration: float) -> float:
        """Wendet einen Strom fuer eine Dauer an und aktualisiert den SoC.

        Der Zeitschritt wird gegebenenfalls nur teilweise ausgefuehrt, damit
        weder mehr Ladung entnommen werden kann als vorhanden ist, noch mehr
        geladen werden kann als in den Akku passt.

        Args:
            current: Strom in Ampere. Positiv = Entladen, negativ = Laden.
            duration: Dauer des Zeitschritts in Sekunden.

        Returns:
            Die tatsaechlich verrechnete Dauer in Sekunden. Ist sie kleiner
            als `duration`, war der Akku innerhalb des Schritts leer bzw. voll.

        Raises:
            ValueError: bei negativer Zeitdauer.
        """
        if duration < 0:
            raise ValueError("Die Zeitdauer darf nicht negativ sein.")

        wirksame_dauer = self.moegliche_dauer(current, duration)

        delta_soc = current * wirksame_dauer / self.capacity_nom_As
        neuer_soc = self.soc - delta_soc
        # Begrenzung laut Angabe: 0 <= SoC <= 1 (jetzt nur noch Rundungsschutz)
        self.soc = max(0.0, min(1.0, neuer_soc))

        # Die Zaehler duerfen nur die tatsaechlich geflossene Ladung enthalten
        if current > 0:
            self.entladene_ladung_As += current * wirksame_dauer
        elif current < 0:
            self.geladene_ladung_As += -current * wirksame_dauer

        # Waermeentwicklung durch ohmsche Verluste. Waehrend der Reststrecke
        # des Zeitschritts fliesst kein Strom, der Akku kuehlt aber weiter ab.
        if self.thermisches_modell is not None:
            verlust_w = current ** 2 * self.aktueller_innenwiderstand()
            self.thermisches_modell.update(verlust_w, self.umgebungstemperatur_c,
                                           wirksame_dauer)
            rest = duration - wirksame_dauer
            if rest > 0:
                self.thermisches_modell.update(0.0, self.umgebungstemperatur_c, rest)
        return wirksame_dauer

    def strom_fuer_leistung(self, leistung_w: float) -> float:
        """Loest P = (U_OC - R_i * I) * I nach dem Strom I auf.

        Der Motorstrom I = T / Km ist *nicht* der Batteriestrom. Der
        Batteriestrom ergibt sich aus der elektrischen Leistung, die der Akku
        an den Klemmen abgeben (bzw. aufnehmen) muss. Aus

            P = U * I  und  U = U_OC - R_i * I

        folgt die quadratische Gleichung

            R_i * I^2 - U_OC * I + P = 0

        mit der physikalisch sinnvollen (betragskleineren) Loesung

            I = (U_OC - sqrt(U_OC^2 - 4 * R_i * P)) / (2 * R_i)

        Args:
            leistung_w: geforderte Klemmenleistung in W
                (positiv = Entladen, negativ = Laden).

        Returns:
            Strom in Ampere, positiv beim Entladen.
        """
        u_oc = self.open_circuit_voltage()
        r_i = self.aktueller_innenwiderstand()
        if r_i <= 0.0:
            return leistung_w / u_oc

        diskriminante = u_oc ** 2 - 4.0 * r_i * leistung_w
        if diskriminante < 0.0:
            # Mehr als P_max = U_OC^2 / (4*R_i) kann der Akku nicht liefern.
            # Der Strom im Leistungsmaximum ist I = U_OC / (2*R_i).
            p_max = u_oc ** 2 / (4.0 * r_i)
            logger.debug("Geforderte Leistung %.0f W liegt ueber dem Maximum "
                         "von %.0f W - Strom wird begrenzt.", leistung_w, p_max)
            return u_oc / (2.0 * r_i)
        return (u_oc - np.sqrt(diskriminante)) / (2.0 * r_i)

    def is_empty(self) -> bool:
        """True, wenn der Akku leer ist (SoC = 0)."""
        return self.soc <= 0.0

    def is_full(self) -> bool:
        """True, wenn der Akku voll ist (SoC = 1)."""
        return self.soc >= 1.0

    # -- Hilfsgroessen -----------------------------------------------------
    @property
    def temperatur_c(self) -> float:
        if self.thermisches_modell is None:
            return float("nan")
        return self.thermisches_modell.temperatur_c

    @property
    def energieinhalt_wh(self) -> float:
        """Grobe Abschaetzung der noch gespeicherten Energie in Wh."""
        return self.soc * self.capacity_nom_Ah * self.open_circuit_voltage()

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}(SoC={self.soc * 100:.1f}%, "
                f"V={self.voltage():.2f} V)")


class KennlinienAkku(BatteryPack):
    """Akku mit gemessener OCV-SoC-Kennlinie statt linearem Verlauf.

    Die Stuetzstellen stehen in den Klassenattributen `SOC_PUNKTE` und
    `UOC_PUNKTE`; zwischen ihnen wird linear interpoliert.
    """

    SOC_PUNKTE: list[float] = []
    UOC_PUNKTE: list[float] = []

    def open_circuit_voltage(self, soc: float | None = None) -> float:
        s = self.soc if soc is None else soc
        s = max(0.0, min(1.0, s))
        return float(np.interp(s, self.SOC_PUNKTE, self.UOC_PUNKTE))


class LiPoAkku(KennlinienAkku):
    """LiPo-Akku laut Angabe: 10SxP, 8 mOhm pro Zelle."""

    name = "LiPo"
    INNENWIDERSTAND_ZELLE_MOHM = 8.0
    SOC_PUNKTE = [0.00, 0.04, 0.09, 0.13, 0.17, 0.21, 0.26,
                  0.30, 0.40, 0.52, 0.64, 0.76, 0.88, 1.00]
    UOC_PUNKTE = [32.00, 35.87, 36.85, 37.56, 37.87, 38.28, 38.81,
                  39.05, 39.55, 40.27, 40.70, 41.16, 41.65, 42.00]


class NmcAkku(KennlinienAkku):
    """NMC-Akku laut Angabe: 10SxP, 7 mOhm pro Zelle."""

    name = "NMC"
    INNENWIDERSTAND_ZELLE_MOHM = 7.0
    SOC_PUNKTE = [0.00, 0.04, 0.09, 0.13, 0.17, 0.21, 0.26,
                  0.30, 0.40, 0.52, 0.64, 0.76, 0.88, 1.00]
    UOC_PUNKTE = [32.00, 32.61, 33.17, 33.85, 34.24, 34.66, 35.39,
                  35.65, 36.65, 37.64, 38.91, 40.14, 41.08, 42.00]


def erzeuge_akku(typ: str, cfg: BatteryConfig,
                 starttemperatur_c: float = 20.0,
                 thermik_aktiv: bool = True) -> BatteryPack:
    """Factory-Funktion: erzeugt einen fertig konfigurierten Akku.

    Der Pack besteht aus `zellen_seriell` x `zellen_parallel` Zellen:
    * Kapazitaet   = Zellkapazitaet * Anzahl paralleler Zellen
    * Innenwiderst.= R_Zelle * seriell / parallel
    * Spannungen   = Zellspannung * Anzahl serieller Zellen (32 V bis 42 V)

    Args:
        typ: "lipo" oder "nmc".

    Raises:
        ValueError: bei unbekanntem Akkutyp.
    """
    klassen = {"lipo": LiPoAkku, "nmc": NmcAkku}
    schluessel = typ.lower().strip()
    if schluessel not in klassen:
        raise ValueError(f"Unbekannter Akkutyp '{typ}'. Erlaubt: {list(klassen)}")

    klasse = klassen[schluessel]
    kapazitaet_ah = cfg.zellkapazitaet_ah * cfg.zellen_parallel
    r_pack_mohm = (klasse.INNENWIDERSTAND_ZELLE_MOHM
                   * cfg.zellen_seriell / cfg.zellen_parallel)

    thermik = None
    if thermik_aktiv:
        thermik = ThermischesModell(
            starttemperatur_c=starttemperatur_c,
            waermekapazitaet_j_per_k=cfg.waermekapazitaet_j_per_k,
            waermeuebergang_w_per_k=cfg.waermeuebergang_w_per_k,
        )

    akku = klasse(
        capacity_nom_Ah=kapazitaet_ah,
        internal_resistance_mOhm=r_pack_mohm,
        initial_soc=cfg.start_soc,
        Vmin=3.2 * cfg.zellen_seriell,
        Vmax=4.2 * cfg.zellen_seriell,
        thermisches_modell=thermik,
        temperaturkoeffizient_ri=cfg.temperaturkoeffizient_ri if thermik_aktiv else 0.0,
        referenztemperatur_c=cfg.referenztemperatur_c,
    )
    logger.info("Akku erzeugt: %s, %.1f Ah, R_i = %.1f mOhm",
                klasse.name, kapazitaet_ah, r_pack_mohm)
    return akku


class Bremswiderstand:
    """Nimmt Energie auf, die der Akku nicht mehr aufnehmen kann.

    Beim Bergabfahren rekuperiert der Motor. Ist der Akku voll oder der
    Ladestrom zu hoch, muss die ueberschuessige Energie in einem
    Bremswiderstand in Waerme umgewandelt werden.
    """

    def __init__(self, max_ladestrom_a: float = 15.0):
        self.max_ladestrom_a = max_ladestrom_a
        self.dissipierte_energie_wh = 0.0
        self.aktivierungen = 0

    def begrenze_ladestrom(self, strom_a: float, akku: BatteryPack,
                           spannung_v: float, dauer_s: float) -> float:
        """Begrenzt den Ladestrom und protokolliert die dissipierte Energie.

        Args:
            strom_a: gewuenschter Strom (negativ = Laden).
            akku: der Akkupack (fuer die Abfrage `is_full`).
            spannung_v: aktuelle Klemmenspannung in V.
            dauer_s: Dauer des Zeitschritts in s.

        Returns:
            Den tatsaechlich in den Akku fliessenden Strom in Ampere.
        """
        if strom_a >= 0:
            return strom_a  # Entladen -> Bremswiderstand nicht beteiligt

        moeglicher_strom = strom_a
        if akku.is_full():
            moeglicher_strom = 0.0
        elif abs(strom_a) > self.max_ladestrom_a:
            moeglicher_strom = -self.max_ladestrom_a

        ueberschuss_a = abs(strom_a) - abs(moeglicher_strom)
        if ueberschuss_a > 0:
            self.aktivierungen += 1
            self.dissipierte_energie_wh += ueberschuss_a * spannung_v * dauer_s / 3600.0
        return moeglicher_strom

    def nimm_energie_auf(self, energie_wh: float) -> None:
        """Nimmt Energie auf, die der Akku nicht speichern konnte.

        Wird verwendet, wenn der Akku *waehrend* eines Zeitschritts voll wird:
        die Restenergie des Schritts muss dann im Bremswiderstand in Waerme
        umgesetzt werden.
        """
        if energie_wh <= 0:
            return
        self.aktivierungen += 1
        self.dissipierte_energie_wh += energie_wh

    def __repr__(self) -> str:
        return (f"Bremswiderstand(dissipiert={self.dissipierte_energie_wh:.1f} Wh, "
                f"{self.aktivierungen} Aktivierungen)")
