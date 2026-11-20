"""Hermes-Plugin "immo-rechner": stellt die Rechner als Werkzeuge bereit."""
from __future__ import annotations

import json

try:
    from . import rechner as r
except ImportError:  # pragma: no cover
    import rechner as r

Z = {"type": "number"}


def _werkzeug(fn):
    def handler(params, **kwargs):
        try:
            return json.dumps({"ok": True, "ergebnis": fn(**(params or {}))}, ensure_ascii=False, default=str)
        except (r.EingabeFehler, TypeError) as e:
            return json.dumps({"ok": False, "fehler": str(e)}, ensure_ascii=False)
    return handler


WERKZEUGE = [
    ("immo_kaufnebenkosten", r.kaufnebenkosten, "Kaufnebenkosten (Grunderwerbsteuer je Bundesland, Notar/Grundbuch, Makler).",
     {"kaufpreis": Z, "bundesland": {"type": "string", "description": "Kürzel, z. B. BY"},
      "notar_grundbuch_satz": {**Z, "description": "Standard 0.02"}, "makler_satz": {**Z, "description": "Standard 0"}}, ["kaufpreis", "bundesland"]),
    ("immo_annuitaet", r.annuitaet, "Annuitätendarlehen: Monatsrate, Tilgungsplan, Restschuld nach Zinsbindung.",
     {"darlehen": Z, "sollzins": {**Z, "description": "z. B. 0.039"}, "anfangstilgung": {**Z, "description": "z. B. 0.02"},
      "monatsrate": Z, "zinsbindung_jahre": {"type": "integer"}, "sondertilgung_pro_jahr": Z}, ["darlehen", "sollzins"]),
    ("immo_rendite", r.rendite, "Brutto-/Nettomietrendite und Kaufpreisfaktor.",
     {"gesamtinvestition": Z, "jahreskaltmiete": Z, "nicht_umlagefaehige_kosten_jahr": Z, "leerstand_quote": Z},
     ["gesamtinvestition", "jahreskaltmiete"]),
    ("immo_verkauf", r.verkauf, "Projektgewinn und Marge bei Verkauf.",
     {"gesamtkosten": Z, "verkaufserloes": Z, "vertriebskosten_satz": Z}, ["gesamtkosten", "verkaufserloes"]),
    ("immo_eigenkapitalrendite", r.eigenkapitalrendite, "Eigenkapitalrendite.",
     {"eigenkapital": Z, "jahresueberschuss_nach_zinsen": Z}, ["eigenkapital", "jahresueberschuss_nach_zinsen"]),
    ("immo_sensitivitaet_vermietung", r.sensitivitaet_vermietung,
     "Szenarien Vermietung: Basis, Zins +1 %-Punkt, Baukosten +15 %, Miete −10 %, alles zusammen.",
     {"grundstueck_inkl_nebenkosten": Z, "baukosten": Z, "jahreskaltmiete": Z, "nicht_umlagefaehige_kosten_jahr": Z,
      "eigenkapital": Z, "sollzins": Z, "anfangstilgung": Z},
     ["grundstueck_inkl_nebenkosten", "baukosten", "jahreskaltmiete", "nicht_umlagefaehige_kosten_jahr", "eigenkapital", "sollzins"]),
    ("immo_afa", r.afa, "AfA-Überblick: linear 3 % oder degressiv 5 % vom Restwert.",
     {"gebaeudewert": Z, "methode": {"type": "string", "enum": ["linear3", "degressiv5"]}, "jahre": {"type": "integer"}},
     ["gebaeudewert"]),
]


def register(ctx):
    for name, fn, beschreibung, props, pflicht in WERKZEUGE:
        ctx.register_tool(name=name, toolset="immo_rechner",
                          schema={"name": name, "description": beschreibung + " Zeige dem Nutzer immer die 'annahmen'.",
                                  "parameters": {"type": "object", "properties": props, "required": pflicht}},
                          handler=_werkzeug(fn))
