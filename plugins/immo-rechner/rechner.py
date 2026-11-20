"""Immobilien-Rechner der KI-Zentrale (reines Python, voll getestet).

Alle Beträge in Euro, Sätze als Dezimalzahl (0.035 = 3,5 %).
Jedes Ergebnis enthält "annahmen", damit Agenten sie anzeigen können.
Keine Steuer- oder Finanzberatung.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

STAND = "2026-11"

# Grunderwerbsteuer nach Bundesland. Quelle: Ländersätze laut Fachportalen (u. a. steuerberater-tabak.com,
# smart-rechner.de, finanz-tools.de), Stand 2026. Vor Verwendung in echten Entscheidungen prüfen.
GRUNDERWERBSTEUER = {
    "BW": 0.050, "BY": 0.035, "BE": 0.060, "BB": 0.065, "HB": 0.055, "HH": 0.055, "HE": 0.060, "MV": 0.060,
    "NI": 0.050, "NW": 0.065, "RP": 0.050, "SL": 0.065, "SN": 0.055, "ST": 0.050, "SH": 0.065, "TH": 0.050,
}
HINWEIS = "Keine Steuer-/Finanzberatung – bitte mit Steuerberater bzw. Bank prüfen."


class EingabeFehler(ValueError):
    pass


def _pos(name: str, wert: float, null_ok: bool = False) -> float:
    if isinstance(wert, bool):
        raise EingabeFehler(f"'{name}' muss eine Zahl sein.")
    try:
        w = float(wert)
    except (TypeError, ValueError):
        raise EingabeFehler(f"'{name}' muss eine Zahl sein.")
    if not math.isfinite(w):
        raise EingabeFehler(f"'{name}' ist keine gültige Zahl.")
    if w < 0 or (w == 0 and not null_ok):
        raise EingabeFehler(f"'{name}' muss größer als 0 sein (ist {wert}). Bitte Eingabe prüfen.")
    return w


def _satz(name: str, wert: float, max_satz: float = 1.0) -> float:
    w = _pos(name, wert, null_ok=True)
    if w > max_satz:
        raise EingabeFehler(f"'{name}' = {wert} wirkt unplausibel. Sätze bitte als Dezimalzahl angeben (3,5 % = 0.035).")
    return w


def _jahre(name: str, wert, maximum: int = 50) -> int:
    w = _pos(name, wert)
    if int(w) != w or not 1 <= w <= maximum:
        raise EingabeFehler(f"'{name}' muss eine ganze Zahl zwischen 1 und {maximum} sein (ist {wert}).")
    return int(w)


def r2(x: float) -> float:
    return round(x + 0.0, 2)


# ---------------------------------------------------------------- Kaufnebenkosten
def kaufnebenkosten(kaufpreis: float, bundesland: str, notar_grundbuch_satz: float = 0.02,
                    makler_satz: float = 0.0) -> dict:
    kp = _pos("kaufpreis", kaufpreis)
    if not isinstance(bundesland, str):
        raise EingabeFehler("'bundesland' muss ein Kürzel wie 'BY' sein.")
    bl = bundesland.upper().strip()
    if bl not in GRUNDERWERBSTEUER:
        raise EingabeFehler(f"Unbekanntes Bundesland '{bundesland}'. Kürzel: {', '.join(GRUNDERWERBSTEUER)}")
    grest = kp * GRUNDERWERBSTEUER[bl]
    notar = kp * _satz("notar_grundbuch_satz", notar_grundbuch_satz, 0.05)
    makler = kp * _satz("makler_satz", makler_satz, 0.08)
    summe = grest + notar + makler
    return {
        "grunderwerbsteuer": r2(grest), "notar_und_grundbuch": r2(notar), "makler": r2(makler),
        "nebenkosten_gesamt": r2(summe), "nebenkosten_quote": round(summe / kp, 4),
        "gesamtkosten_erwerb": r2(kp + summe),
        "annahmen": {"kaufpreis": kp, "bundesland": bl,
                     "grunderwerbsteuersatz": GRUNDERWERBSTEUER[bl], "grunderwerbsteuer_stand": STAND,
                     "notar_grundbuch_satz": notar_grundbuch_satz, "makler_satz": makler_satz},
        "hinweis": "Notar/Grundbuch ist eine Annahme (typisch ca. 1,5–2 %). " + HINWEIS,
    }


# ---------------------------------------------------------------- Annuitätendarlehen
def annuitaet(darlehen: float, sollzins: float, anfangstilgung: float | None = None,
              monatsrate: float | None = None, zinsbindung_jahre: int = 10,
              sondertilgung_pro_jahr: float = 0.0) -> dict:
    """Monatliche Raten, Zinsen monatlich (Sollzins/12). Sondertilgung jeweils zum Jahresende."""
    p = _pos("darlehen", darlehen)
    z = _satz("sollzins", sollzins, 0.25)
    if (anfangstilgung is None) == (monatsrate is None):
        raise EingabeFehler("Bitte genau EINES angeben: anfangstilgung ODER monatsrate.")
    if monatsrate is None:
        rate = p * (z + _satz("anfangstilgung", anfangstilgung, 0.5)) / 12
    else:
        rate = _pos("monatsrate", monatsrate)
    if rate <= p * z / 12:
        raise EingabeFehler("Die Rate deckt nicht einmal die Zinsen – das Darlehen würde nie getilgt.")
    jahre = _jahre("zinsbindung_jahre", zinsbindung_jahre)
    st = _pos("sondertilgung_pro_jahr", sondertilgung_pro_jahr, null_ok=True)
    i = z / 12
    rest = p
    plan, zinsen_summe = [], 0.0
    for jahr in range(1, jahre + 1):
        zj = tj = 0.0
        for _ in range(12):
            if rest <= 0:
                break
            zins = rest * i
            tilg = min(rate - zins, rest)
            rest -= tilg; zj += zins; tj += tilg
        sonder = min(st, rest); rest -= sonder
        zinsen_summe += zj
        plan.append({"jahr": jahr, "zinsen": r2(zj), "tilgung": r2(tj + sonder), "sondertilgung": r2(sonder),
                     "restschuld": r2(max(rest, 0.0))})
        if rest <= 0:
            break
    # Gesamtlaufzeit bis Volltilgung (gleicher Zins angenommen)
    r_tmp, monate = p, 0
    while r_tmp > 0.005 and monate < 12 * 100:
        r_tmp -= rate - r_tmp * i; monate += 1
    return {
        "monatsrate": r2(rate), "jahresrate": r2(rate * 12),
        "restschuld_nach_zinsbindung": r2(max(rest, 0.0)), "zinsen_in_zinsbindung": r2(zinsen_summe),
        "laufzeit_bis_volltilgung_jahre": round(monate / 12, 1) if monate < 1200 else None,
        "tilgungsplan": plan,
        "annahmen": {"darlehen": p, "sollzins": z, "anfangstilgung": anfangstilgung, "zinsbindung_jahre": jahre,
                     "sondertilgung_pro_jahr": st,
                     "methode": "monatliche Rate, Zins = Sollzins/12; Volltilgung bei gleichbleibendem Zins (Annahme)"},
        "hinweis": "Effektivzins kann höher sein (Gebühren, Bereitstellungszinsen). " + HINWEIS,
    }


# ---------------------------------------------------------------- Rendite
def rendite(gesamtinvestition: float, jahreskaltmiete: float, nicht_umlagefaehige_kosten_jahr: float = 0.0,
            leerstand_quote: float = 0.0) -> dict:
    inv = _pos("gesamtinvestition", gesamtinvestition)
    miete = _pos("jahreskaltmiete", jahreskaltmiete)
    kosten = _pos("nicht_umlagefaehige_kosten_jahr", nicht_umlagefaehige_kosten_jahr, null_ok=True)
    lq = _satz("leerstand_quote", leerstand_quote, 0.5)
    netto_ertrag = miete * (1 - lq) - kosten
    return {
        "bruttomietrendite": round(miete / inv, 4), "nettomietrendite": round(netto_ertrag / inv, 4),
        "kaufpreisfaktor": round(inv / miete, 2), "netto_ertrag_jahr": r2(netto_ertrag),
        "annahmen": {"gesamtinvestition_inkl_nebenkosten": inv, "jahreskaltmiete": miete,
                     "nicht_umlagefaehige_kosten_jahr": kosten, "leerstand_quote": lq},
        "hinweis": "Nettomietrendite vor Finanzierung und Steuern. " + HINWEIS,
    }


def eigenkapitalrendite(eigenkapital: float, jahresueberschuss_nach_zinsen: float) -> dict:
    ek = _pos("eigenkapital", eigenkapital)
    if isinstance(jahresueberschuss_nach_zinsen, bool):
        raise EingabeFehler("'jahresueberschuss_nach_zinsen' muss eine Zahl sein.")
    try:
        u = float(jahresueberschuss_nach_zinsen)
    except (TypeError, ValueError):
        raise EingabeFehler("'jahresueberschuss_nach_zinsen' muss eine Zahl sein.")
    if not math.isfinite(u):
        raise EingabeFehler("'jahresueberschuss_nach_zinsen' ist keine gültige Zahl.")
    return {"eigenkapitalrendite": round(u / ek, 4),
            "annahmen": {"eigenkapital": ek, "jahresueberschuss_nach_zinsen": u}, "hinweis": HINWEIS}


# ---------------------------------------------------------------- Verkauf (Bauträger-Logik)
def verkauf(gesamtkosten: float, verkaufserloes: float, vertriebskosten_satz: float = 0.03) -> dict:
    k = _pos("gesamtkosten", gesamtkosten)
    e = _pos("verkaufserloes", verkaufserloes)
    vk = e * _satz("vertriebskosten_satz", vertriebskosten_satz, 0.2)
    gewinn = e - k - vk
    return {"vertriebskosten": r2(vk), "projektgewinn_vor_steuern": r2(gewinn),
            "marge_auf_erloes": round(gewinn / e, 4), "marge_auf_kosten": round(gewinn / k, 4),
            "annahmen": {"gesamtkosten": k, "verkaufserloes": e, "vertriebskosten_satz": vertriebskosten_satz},
            "hinweis": "Vor Steuern. Bei 'bauen und verkaufen' droht gewerblicher Grundstückshandel "
                       "(Gewerbesteuer, Drei-Objekt-Grenze). " + HINWEIS}


# ---------------------------------------------------------------- Sensitivität Vermietung
@dataclass
class VermietungBasis:
    grundstueck_inkl_nebenkosten: float
    baukosten: float
    jahreskaltmiete: float
    nicht_umlagefaehige_kosten_jahr: float
    eigenkapital: float
    sollzins: float
    anfangstilgung: float = 0.02


def _vermietung(b: VermietungBasis) -> dict:
    inv = b.grundstueck_inkl_nebenkosten + b.baukosten
    darlehen = max(inv - b.eigenkapital, 0.0)
    zinsen = darlehen * b.sollzins
    tilgung = darlehen * b.anfangstilgung
    ueberschuss = b.jahreskaltmiete - b.nicht_umlagefaehige_kosten_jahr - zinsen
    return {"gesamtinvestition": r2(inv), "darlehen": r2(darlehen),
            "nettomietrendite": round((b.jahreskaltmiete - b.nicht_umlagefaehige_kosten_jahr) / inv, 4),
            "ueberschuss_nach_zinsen_jahr": r2(ueberschuss),
            "cashflow_nach_kapitaldienst_jahr": r2(ueberschuss - tilgung),
            "eigenkapitalrendite": round(ueberschuss / b.eigenkapital, 4) if b.eigenkapital > 0 else None}


def sensitivitaet_vermietung(grundstueck_inkl_nebenkosten: float, baukosten: float, jahreskaltmiete: float,
                             nicht_umlagefaehige_kosten_jahr: float, eigenkapital: float, sollzins: float,
                             anfangstilgung: float = 0.02) -> dict:
    b = VermietungBasis(_pos("grundstueck_inkl_nebenkosten", grundstueck_inkl_nebenkosten), _pos("baukosten", baukosten),
                        _pos("jahreskaltmiete", jahreskaltmiete),
                        _pos("nicht_umlagefaehige_kosten_jahr", nicht_umlagefaehige_kosten_jahr, null_ok=True),
                        _pos("eigenkapital", eigenkapital, null_ok=True), _satz("sollzins", sollzins, 0.25),
                        _satz("anfangstilgung", anfangstilgung, 0.5))
    szen = {
        "basis": b,
        "zins_plus_1_prozentpunkt": VermietungBasis(**{**b.__dict__, "sollzins": b.sollzins + 0.01}),
        "baukosten_plus_15_prozent": VermietungBasis(**{**b.__dict__, "baukosten": b.baukosten * 1.15}),
        "miete_minus_10_prozent": VermietungBasis(**{**b.__dict__, "jahreskaltmiete": b.jahreskaltmiete * 0.9}),
        "alles_zusammen_pessimistisch": VermietungBasis(**{**b.__dict__, "sollzins": b.sollzins + 0.01,
                                                           "baukosten": b.baukosten * 1.15,
                                                           "jahreskaltmiete": b.jahreskaltmiete * 0.9}),
    }
    return {"szenarien": {k: _vermietung(v) for k, v in szen.items()},
            "annahmen": {**b.__dict__, "vereinfachung": "Zinsen auf volles Darlehen im 1. Jahr, ohne Steuern/AfA"},
            "hinweis": HINWEIS}


# ---------------------------------------------------------------- AfA (nur Überblick)
def afa(gebaeudewert: float, methode: str = "linear3", jahre: int = 10) -> dict:
    """linear3: 3 % p. a. (Fertigstellung nach 2022, § 7 Abs. 4 EStG);
    degressiv5: 5 % vom Restwert (§ 7 Abs. 5a EStG, Baubeginn 01.10.2023–30.09.2029), Wechsel zu linear möglich."""
    g = _pos("gebaeudewert", gebaeudewert)
    n = _jahre("jahre", jahre, 100)
    plan, rest = [], g
    for j in range(1, n + 1):
        betrag = g * 0.03 if methode == "linear3" else rest * 0.05 if methode == "degressiv5" else None
        if betrag is None:
            raise EingabeFehler("methode muss 'linear3' oder 'degressiv5' sein.")
        betrag = min(betrag, rest); rest -= betrag
        plan.append({"jahr": j, "afa": r2(betrag), "restwert": r2(rest)})
    return {"plan": plan, "summe": r2(g - rest),
            "annahmen": {"gebaeudewert_ohne_grundstueck": g, "methode": methode, "stand": STAND,
                         "voraussetzung_degressiv": "Baubeginn 01.10.2023–30.09.2029, vermietete Wohnung"},
            "hinweis": "Ganzjährige Beträge (im ersten Jahr zeitanteilig!). Sonder-AfA § 7b nicht enthalten. " + HINWEIS}
