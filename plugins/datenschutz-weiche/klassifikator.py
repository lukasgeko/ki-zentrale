"""Datenschutz-Klassifikator der KI-Zentrale (ohne Abhängigkeiten, voll testbar).

Stufen:  "rot"  = privat, darf nicht an Cloud-Modelle oder ins Web
         "ok"   = darf in die Cloud (🟢/🟡)
Philosophie: lieber einmal zu vorsichtig (falscher Alarm, Lukas kann mit
"cloud-ok:" bewusst freigeben) als private Daten in die Cloud zu schicken.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Bewusste Freigabe durch Lukas am Anfang der Nachricht
FREIGABE_PRAEFIXE = ("cloud-ok:", "cloud ok:", "freigabe-cloud:")
# Bewusste Markierung als privat
PRIVAT_PRAEFIXE = ("🔒", "privat:", "privat ")

# Zahlen: mit Tausenderpunkt (450.000), lange Zahlen (85000), oder mit Einheit (3,9 %, 450k, 1,2 Mio, 200 €)
_ZAHL = (r"\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?"
         r"|\d{4,}(?:,\d+)?"
         r"|\d+(?:[.,]\d+)?\s?(?:%|prozent\b|k\b|tsd\.?|tausend\b|mio\.?|millionen\b|€|eur\b|euro\b)")

MUSTER_HART = {
    "IBAN": re.compile(r"\b[A-Za-z]{2}\d{2}(?:[\s-]?[A-Za-z0-9]{4}){3,7}(?:[\s-]?[A-Za-z0-9]{1,3})?\b"),
    "Kreditkartennummer": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "Steuer-ID": re.compile(r"\b(?:steuer-?id|steueridentifikationsnummer|idnr)[^\d]{0,12}\d{2}\s?\d{3}\s?\d{3}\s?\d{3}\b", re.I),
    "Sozialversicherungsnummer": re.compile(r"\b\d{2}\s?\d{6}\s?[A-Z]\s?\d{3}\b"),
    "Ausweisnummer": re.compile(r"\b(?:personalausweis|ausweis|reisepass)(?:nummer|-nr\.?|nr\.?)?\W{0,5}[CFGHJKLMNPRTVWXYZ0-9]{9}\b", re.I),
}

# STARK: Themenwort + Zahl in der Nähe genügt (das ist praktisch immer persönlich)
STARK = {
    "Kredit-/Finanzierungsangebot": r"(?:kredit|darlehens?|finanzierungs?|baufinanzierungs?)(?:angebot|konditionen|zusage|vertrag)\w*|\bkonditionen\b|\bzusage\b",
    "Einkommen": r"\b(?:gehalt\w*|lohnabrechnung\w*|gehaltsabrechnung\w*|verdien\w*)",
    "Kontostand/Schulden": r"\b(?:kontostand\w*|kontoauszug\w*|restschuld\w*|schufa\w*)",
}
# WEICH: zählt nur mit Zahl UND (persönlichem Bezug ODER genanntem Kreditgeber)
WEICH = {
    "Kredit/Zins": r"\b(?:kredit\w*|darlehen\w*|sollzins\w*|effektivzins\w*|zins\w*|tilgung\w*|rate\b|raten\b|bereitstellungszins\w*)",
    "Vermögen/Einkommen": r"\b(?:eigenkapital\w*|ek\b|vermögen\w*|ersparnis\w*|erspart\w*|depot\w*|konto\b|konten\b|einkommen\w*|netto\b|brutto\b|schulden\w*)",
}
KREDITGEBER = re.compile(r"\b(?:sparkasse\w*|volksbank\w*|raiffeisen\w*|bank\b|banken\b|kfw\b|ing\b|dkb\b|commerzbank|hypovereinsbank|interhyp|dr\.?\s?klein|bausparkasse\w*)", re.I)
NAEHE = 80  # Zeichen

# Rechenbeispiele mit ausgedachten Zahlen sind nicht privat – außer es ist erkennbar "unseres"
BEISPIEL_RE = re.compile(r"(?:beispiel\w*|angenommen|annahme|fiktiv\w*|hypothetisch\w*|szenario\w*|z\.\s?b\.)", re.I)
PERSOENLICH_RE = re.compile(r"\b(?:mein\w*|unser\w*|papa\w*|mama\w*|vater\w*|mutter\w*|bruder\w*|ich\b|wir\b|uns\b|mir\b|mich\b)", re.I)

_STARK_RE = {k: re.compile(v, re.I) for k, v in STARK.items()}
_WEICH_RE = {k: re.compile(v, re.I) for k, v in WEICH.items()}
_ZAHL_RE = re.compile(_ZAHL, re.I)


def _luhn_ok(ziffern: str) -> bool:
    z = [int(c) for c in ziffern if c.isdigit()]
    if not 13 <= len(z) <= 19:
        return False
    s = 0
    for i, d in enumerate(reversed(z)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return s % 10 == 0


def _iban_ok(kandidat: str) -> bool:
    s = re.sub(r"[\s-]", "", kandidat).upper()
    if not 15 <= len(s) <= 34:
        return False
    if s[:2] == "DE" and len(s) != 22:
        return False
    umgestellt = s[4:] + s[:4]
    try:
        zahl = int("".join(str(int(c, 36)) for c in umgestellt))
    except ValueError:
        return False
    return zahl % 97 == 1


@dataclass
class Ergebnis:
    stufe: str  # "rot" | "ok"
    gruende: list[str] = field(default_factory=list)
    freigegeben: bool = False

    @property
    def ist_privat(self) -> bool:
        return self.stufe == "rot" and not self.freigegeben


def bewerte(text: str | None) -> Ergebnis:
    if not text:
        return Ergebnis("ok")
    t = str(text)
    kopf = t.lstrip().lower()
    freigabe = kopf.startswith(FREIGABE_PRAEFIXE)
    gruende: list[str] = []
    if kopf.startswith(PRIVAT_PRAEFIXE) or t.lstrip().startswith("🔒"):
        gruende.append("von Lukas als privat markiert")

    for m in MUSTER_HART["IBAN"].finditer(t):
        if _iban_ok(m.group(0)):
            gruende.append("IBAN")
            break
    for m in MUSTER_HART["Kreditkartennummer"].finditer(t):
        if _luhn_ok(m.group(0)):
            gruende.append("Kreditkartennummer")
            break
    for name in ("Steuer-ID", "Sozialversicherungsnummer", "Ausweisnummer"):
        if MUSTER_HART[name].search(t):
            gruende.append(name)

    zahlen = [m.start() for m in _ZAHL_RE.finditer(t)]
    persoenlich = bool(PERSOENLICH_RE.search(t))
    nur_beispiel = bool(BEISPIEL_RE.search(t)) and not persoenlich
    if zahlen and not nur_beispiel:
        def nah(rx):
            return any(any(abs(z - m.start()) <= NAEHE for z in zahlen) for m in rx.finditer(t))
        for name, rx in _STARK_RE.items():
            if nah(rx):
                gruende.append(name)
        if persoenlich or KREDITGEBER.search(t):
            for name, rx in _WEICH_RE.items():
                if nah(rx):
                    gruende.append(name)

    gruende = list(dict.fromkeys(gruende))
    if gruende:
        return Ergebnis("rot", gruende, freigegeben=freigabe)
    return Ergebnis("ok")


ERSATZ = {
    "IBAN": "[🔒 IBAN entfernt]",
    "Kreditkartennummer": "[🔒 Kartennummer entfernt]",
}


def schwaerze(text: str) -> tuple[str, list[str]]:
    """Entfernt harte Kennungen (IBAN, Karten-, Steuer-, SV-, Ausweisnummern) aus Werkzeug-Ergebnissen."""
    entfernt: list[str] = []

    def iban(m):
        if _iban_ok(m.group(0)):
            entfernt.append("IBAN")
            return ERSATZ["IBAN"]
        return m.group(0)

    def karte(m):
        if _luhn_ok(m.group(0)):
            entfernt.append("Kreditkartennummer")
            return ERSATZ["Kreditkartennummer"]
        return m.group(0)

    t = MUSTER_HART["IBAN"].sub(iban, text)
    t = MUSTER_HART["Kreditkartennummer"].sub(karte, t)
    for name in ("Steuer-ID", "Sozialversicherungsnummer", "Ausweisnummer"):
        t, n = MUSTER_HART[name].subn(f"[🔒 {name} entfernt]", t)
        if n:
            entfernt.append(name)
    return t, list(dict.fromkeys(entfernt))
