"""Hermes-Plugin "datenschutz-weiche".

Wird NUR in Profilen mit Cloud-Modell aktiviert (alle außer `privat`).
1. pre_llm_call: 🔴-Nachricht von Lukas → Turn wird gestoppt, bevor irgendetwas an die Cloud geht.
2. pre_tool_call: 🔴-Inhalte in Web-Suchen/Übergaben an andere Profile → blockiert
   (Ausnahme: Übergabe an das Profil `privat`).
3. transform_tool_result: harte Kennungen (IBAN, Kartennummern …) in Werkzeug-Ergebnissen
   (z. B. E-Mails) werden geschwärzt, bevor das Cloud-Modell sie sieht.
"""
from __future__ import annotations

import json
import logging

try:  # Paketimport (Hermes) oder direkter Import (Tests)
    from .klassifikator import bewerte, schwaerze
except ImportError:  # pragma: no cover
    from klassifikator import bewerte, schwaerze

log = logging.getLogger("datenschutz-weiche")

PRIVAT_PROFIL = "privat"
WEB_WERKZEUGE = {"web_search", "web_extract", "browser_exec", "browser_cdp", "x_search"}
UEBERGABE_WERKZEUGE = {"delegate_task"}

MELDUNG_TURN = (
    "🔒 Das sieht privat aus ({gruende}). Ich schicke das nicht an die Cloud-KI.\n"
    "→ Ich gebe es an die lokale KI (Profil `privat`) weiter. Wenn das ein Fehlalarm ist, "
    "schreib deine Nachricht noch einmal mit `cloud-ok:` am Anfang."
)
MELDUNG_WERKZEUG = (
    "BLOCKIERT durch Datenschutz-Weiche: Die Eingabe für '{tool}' enthält private Daten ({gruende}). "
    "Private Daten dürfen nicht ins Web oder an Cloud-Agenten. Nutze das Profil 'privat' oder entferne die Daten."
)


def _text_aus_args(args) -> str:
    try:
        return json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(args)


def _geht_an_privat(args) -> bool:
    def walk(x):
        if isinstance(x, dict):
            return any(walk(v) for v in x.values())
        if isinstance(x, list):
            return any(walk(v) for v in x)
        return isinstance(x, str) and x.strip().lower() == PRIVAT_PROFIL
    return walk(args)


def vor_llm(user_message=None, **kwargs):
    e = bewerte(user_message if isinstance(user_message, str) else _text_aus_args(user_message))
    if e.ist_privat:
        log.warning("Turn gestoppt: %s", ", ".join(e.gruende))
        return {"action": "block", "message": MELDUNG_TURN.format(gruende=", ".join(e.gruende))}
    return None


def vor_werkzeug(tool_name=None, args=None, **kwargs):
    if tool_name not in WEB_WERKZEUGE | UEBERGABE_WERKZEUGE:
        return None
    if tool_name in UEBERGABE_WERKZEUGE and _geht_an_privat(args):
        return None
    e = bewerte(_text_aus_args(args))
    if e.stufe == "rot":  # Werkzeuge: keine Freigabe per Präfix
        log.warning("Werkzeug %s blockiert: %s", tool_name, ", ".join(e.gruende))
        return {"action": "block", "message": MELDUNG_WERKZEUG.format(tool=tool_name, gruende=", ".join(e.gruende))}
    return None


def nach_werkzeug(result=None, tool_name=None, **kwargs):
    if not isinstance(result, str) or not result:
        return None
    neu, entfernt = schwaerze(result)
    if entfernt:
        log.info("In Ergebnis von %s geschwärzt: %s", tool_name, ", ".join(entfernt))
        return neu
    return None


def register(ctx):
    ctx.register_hook("pre_llm_call", vor_llm)
    ctx.register_hook("pre_tool_call", vor_werkzeug)
    ctx.register_hook("transform_tool_result", nach_werkzeug)
