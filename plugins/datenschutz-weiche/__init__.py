"""Hermes-Plugin "datenschutz-weiche".

Wird NUR in Profilen mit Cloud-Modell aktiviert (alle außer `privat`).
1. pre_llm_call: 🔴-Nachricht von Lukas → Turn wird gestoppt, bevor irgendetwas an die Cloud geht
   (laut Hermes-Quelltext bleibt die Nachricht dann auch aus Verlauf, Kompression und Gedächtnis heraus).
2. pre_tool_call:
   a) Zugriff auf Geheimnisse (secrets/, .env, Token-Dateien) → für ALLE Werkzeuge blockiert.
   b) 🔴-Inhalte in Werkzeug-Eingaben → blockiert, außer bei rein lokalen Werkzeugen (Erlaubnisliste).
      Übergaben an andere Agenten (delegate_task) mit 🔴 werden IMMER blockiert.
3. transform_tool_result: Werkzeug-Ergebnisse (Mails, Dateien) mit 🔴-Inhalt werden durch einen Hinweis
   ersetzt, bevor das Cloud-Modell sie sieht; harte Kennungen (IBAN …) werden immer geschwärzt.
Bekannte Grenze: Bilder werden nicht inhaltlich geprüft (siehe 00_BRAIN.md, Entscheidung offen).
"""
from __future__ import annotations

import json
import logging
import re

try:  # Paketimport (Hermes) oder direkter Import (Tests)
    from .klassifikator import bewerte, schwaerze
except ImportError:  # pragma: no cover
    from klassifikator import bewerte, schwaerze

log = logging.getLogger("datenschutz-weiche")

# Werkzeuge, deren Eingaben den Rechner nicht verlassen bzw. nur in Lukas' eigenes Gmail gehen.
LOKAL_ERLAUBT = {
    "read_file", "write_file", "patch", "search_files", "todo_list", "clarify", "session_search",
    "gmail_suchen", "gmail_lesen", "gmail_labels", "gmail_label_setzen", "gmail_archivieren", "gmail_entwurf_anlegen",
}
LOKAL_PRAEFIXE = ("immo_",)
GEHEIM_RE = re.compile(r"(?:^|[/\\\s\"'])(?:secrets?[/\\]|\.env\b|[\w-]*token[\w-]*\.json|client_secret[\w-]*\.json|auth\.json)", re.I)

# Reine Kennungen werden in Ergebnissen geschwärzt statt den ganzen Inhalt zurückzuhalten
HARTE_KENNUNGEN = {"IBAN", "Kreditkartennummer", "Steuer-ID", "Sozialversicherungsnummer", "Ausweisnummer",
                   "von Lukas als privat markiert"}

MELDUNG_TURN = (
    "🔒 Das sieht privat aus ({gruende}). Ich schicke das nicht an die Cloud-KI.\n"
    "→ Bitte öffne das Profil **privat** (im Dashboard oben links das Profil wechseln) und stelle die Frage dort. "
    "Das läuft auf deiner lokalen KI.\n"
    "Wenn das ein Fehlalarm ist: Nachricht noch einmal mit `cloud-ok:` am Anfang senden."
)
MELDUNG_WERKZEUG = (
    "BLOCKIERT durch Datenschutz-Weiche: Die Eingabe für '{tool}' enthält private Daten ({gruende}). "
    "Private Daten dürfen nicht ins Web, nicht ins Gedächtnis und nicht an andere Agenten. "
    "Sag Lukas, er soll die Aufgabe im Profil 'privat' stellen."
)
MELDUNG_GEHEIM = "BLOCKIERT: Zugriff auf Geheimnisse (Schlüssel, Tokens, .env) ist für Agenten gesperrt."
MELDUNG_ERGEBNIS = ("[🔒 Dieser Inhalt enthält private Daten ({gruende}) und wird der Cloud-KI nicht gezeigt. "
                    "Lukas kann ihn im Profil 'privat' öffnen.]")


def _text(x) -> str:
    if isinstance(x, str):
        # JSON-Zeichenketten mit \\u-Escapes lesbar machen, damit Muster greifen
        try:
            return json.dumps(json.loads(x), ensure_ascii=False)
        except (ValueError, TypeError):
            return x
    try:
        return json.dumps(x, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(x)


def _ist_lokal(tool: str | None) -> bool:
    return bool(tool) and (tool in LOKAL_ERLAUBT or tool.startswith(LOKAL_PRAEFIXE))


def vor_llm(user_message=None, **kwargs):
    if isinstance(user_message, list):  # mehrteilige Nachricht (Text + Bilder): nur Textteile prüfbar
        text = " ".join(t.get("text", "") for t in user_message if isinstance(t, dict))
    else:
        text = user_message if isinstance(user_message, str) else _text(user_message)
    e = bewerte(text)
    if e.ist_privat:
        log.warning("Turn gestoppt: %s", ", ".join(e.gruende))
        return {"action": "block", "message": MELDUNG_TURN.format(gruende=", ".join(e.gruende))}
    return None


def vor_werkzeug(tool_name=None, args=None, **kwargs):
    text = _text(args)
    if GEHEIM_RE.search(text):
        log.warning("Geheimnis-Zugriff blockiert: %s", tool_name)
        return {"action": "block", "message": MELDUNG_GEHEIM}
    if _ist_lokal(tool_name):
        return None
    e = bewerte(text)
    if e.stufe == "rot":  # Werkzeuge: keine Freigabe per "cloud-ok:"
        log.warning("Werkzeug %s blockiert: %s", tool_name, ", ".join(e.gruende))
        return {"action": "block", "message": MELDUNG_WERKZEUG.format(tool=tool_name, gruende=", ".join(e.gruende))}
    return None


def nach_werkzeug(result=None, tool_name=None, **kwargs):
    if not isinstance(result, str) or not result:
        return None
    lesbar = _text(result)
    e = bewerte(lesbar)
    themen = [g for g in e.gruende if g not in HARTE_KENNUNGEN]
    if themen:
        log.info("Ergebnis von %s zurückgehalten: %s", tool_name, ", ".join(e.gruende))
        return MELDUNG_ERGEBNIS.format(gruende=", ".join(themen))
    neu, entfernt = schwaerze(lesbar)
    if entfernt:
        log.info("In Ergebnis von %s geschwärzt: %s", tool_name, ", ".join(entfernt))
        return neu
    return None


def register(ctx):
    ctx.register_hook("pre_llm_call", vor_llm)
    ctx.register_hook("pre_tool_call", vor_werkzeug)
    ctx.register_hook("transform_tool_result", nach_werkzeug)
