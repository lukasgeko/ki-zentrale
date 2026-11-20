"""Hermes-Plugin "teamregeln": erzwingt die Rollen auf dem Aufgaben-Board (siehe regeln.py)."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

try:
    from .regeln import pruefe
except ImportError:  # pragma: no cover
    from regeln import pruefe

log = logging.getLogger("teamregeln")
_TEAM_DATEI = Path(__file__).resolve().parent / "team.json"


def _team() -> set[str]:
    try:
        return set(json.loads(_TEAM_DATEI.read_text())["profile"])
    except (OSError, ValueError, KeyError):
        return set()  # ohne Teamliste kann der Manager nichts vergeben (sicher)


def _profil() -> str | None:
    try:
        from hermes_cli.profiles import current_profile_name  # Hermes-intern
        return current_profile_name(None)
    except Exception:  # pragma: no cover - außerhalb von Hermes
        return os.environ.get("HERMES_PROFILE_NAME") or os.environ.get("HERMES_PROFILE")


def vor_werkzeug(tool_name=None, args=None, **kwargs):
    meldung = pruefe(_profil(), tool_name, args, os.environ.get("HERMES_KANBAN_TASK"), _team())
    if meldung:
        log.warning("%s: %s", tool_name, meldung)
        return {"action": "block", "message": meldung}
    return None


def register(ctx):
    ctx.register_hook("pre_tool_call", vor_werkzeug)
