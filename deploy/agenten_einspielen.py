#!/usr/bin/env python3
"""Spielt Agenten-Profile und Plugins aus dem Repo in Hermes ein (Phase 2/3).

STATUS: Entwurf, gegen die Hermes-Doku geschrieben, aber noch NICHT gegen einen laufenden Server
getestet. Erster echter Lauf gemeinsam mit Claude Code, erst mit --trocken, dann mit --ausfuehren.

Was passiert pro Agent (agents/<name>/):
  1. Profil anlegen (falls nicht vorhanden) + Prüf-Zwilling "<name>-pruef" für den Prüflauf
  2. SOUL.md = agents/<name>/SOUL.md + agents/_gemeinsam.md
  3. Modell/Provider setzen, nicht erlaubte Werkzeug-Gruppen abschalten, Plugins freischalten
Der Agent "chef" ist das Standard-Profil ("default").

Aufruf auf dem Server (Repo liegt in ~/ki-zentrale-repo, Daten in ~/ki-zentrale/hermes-data):
  python3 deploy/agenten_einspielen.py --trocken          # zeigt nur, was passieren würde
  python3 deploy/agenten_einspielen.py --ausfuehren       # führt aus (vorher Backup!)
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
DATEN = Path(os.environ.get("HERMES_DATEN", Path.home() / "ki-zentrale" / "hermes-data"))
HERMES = os.environ.get("HERMES_BEFEHL", "docker exec -i hermes hermes")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ki-pc:11434/v1")  # Tailscale-Name des PCs (Phase 3)

# Alle Werkzeug-Gruppen laut Hermes-Doku (toolsets-reference). Alles, was ein Profil nicht
# ausdrücklich erlaubt, wird abgeschaltet ("Least Privilege").
ALLE_TOOLSETS = [
    "browser", "clarify", "code_execution", "connections", "cronjob", "delegation", "file", "computer_use",
    "image_gen", "video_gen", "kanban", "memory", "desktop_ui", "project", "catalog", "safe", "search",
    "session_search", "skills", "terminal", "todo", "tts", "vision", "video", "web", "x_search",
    "gmail_entwuerfe", "immo_rechner",
]


def profile() -> list[dict]:
    out = []
    for d in sorted((REPO / "agents").iterdir()):
        if d.is_dir():
            p = yaml.safe_load((d / "profile.yaml").read_text())
            p["soul"] = (d / "SOUL.md").read_text() + (REPO / "agents" / "_gemeinsam.md").read_text()
            out.append(p)
    return out


def m_lokal(p: dict) -> bool:
    return p["modell"]["provider"] == "ollama"


def hermes_name(agent: str, pruef: bool) -> str:
    if agent == "chef":
        return "chef-pruef" if pruef else "default"
    return f"{agent}-pruef" if pruef else agent


def schritte(p: dict, pruef: bool) -> list[tuple[str, object]]:
    name = hermes_name(p["name"], pruef)
    pfx = [] if name == "default" else ["-p", name]
    home = DATEN if name == "default" else DATEN / "profiles" / name
    aus = sorted(set(ALLE_TOOLSETS) - set(p["toolsets"]))
    s: list[tuple[str, object]] = []
    if name != "default" and not home.exists():
        create = ["profile", "create", name, "--description", p["beschreibung"]]
        if m_lokal(p):
            # Lokales Profil bekommt KEINE Cloud-Schlüssel: so kann es auch versehentlich nie in die Cloud ausweichen
            create.append("--no-credentials")
        s.append(("befehl", create))
    s.append(("datei", (home / "SOUL.md", p["soul"])))
    m = p["modell"]
    s.append(("befehl", pfx + ["config", "set", "model.provider", "custom" if m["provider"] == "ollama" else m["provider"]]))
    s.append(("befehl", pfx + ["config", "set", "model.default", m["model"]]))
    if m["provider"] == "ollama":
        s.append(("befehl", pfx + ["config", "set", "model.base_url", OLLAMA_URL]))
    s.append(("befehl", pfx + ["config", "set", "agent.disabled_toolsets", json.dumps(aus)]))
    s.append(("befehl", pfx + ["config", "set", "plugins.enabled", json.dumps(p["plugins"])]))
    for k, v in (("approvals.mode", "manual"), ("approvals.cron_mode", "deny"),
                 ("approvals.unattended_mode", "deny"), ("approvals.single_query_mode", "deny")):
        s.append(("befehl", pfx + ["config", "set", k, v]))
    return s


def plugins_kopieren(trocken: bool) -> None:
    ziel = DATEN / "plugins"
    for pl in sorted((REPO / "plugins").iterdir()):
        if pl.is_dir():
            print(f"  📦 Plugin {pl.name} → {ziel / pl.name}")
            if not trocken:
                ziel.mkdir(parents=True, exist_ok=True)
                if (ziel / pl.name).exists():
                    shutil.move(str(ziel / pl.name), str(ziel / f".{pl.name}.alt"))  # nichts löschen
                shutil.copytree(pl, ziel / pl.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--trocken", action="store_true")
    g.add_argument("--ausfuehren", action="store_true")
    ap.add_argument("--agent", action="append", help="nur diese Agenten")
    ap.add_argument("--ohne-pruefprofile", action="store_true")
    a = ap.parse_args(argv)

    plugins_kopieren(a.trocken)
    fehler = 0
    for p in profile():
        if a.agent and p["name"] not in a.agent:
            continue
        for pruef in ([False] if a.ohne_pruefprofile else [False, True]):
            print(f"▶ {hermes_name(p['name'], pruef)}")
            for art, inhalt in schritte(p, pruef):
                if art == "datei":
                    pfad, text = inhalt
                    print(f"  📝 {pfad}")
                    if not a.trocken:
                        pfad.parent.mkdir(parents=True, exist_ok=True)
                        if pfad.exists():
                            shutil.copy2(pfad, pfad.with_suffix(".md.bak"))
                        pfad.write_text(text)
                else:
                    cmd = shlex.split(HERMES) + list(inhalt)
                    print("  $ " + " ".join(shlex.quote(c) for c in cmd))
                    if not a.trocken:
                        r = subprocess.run(cmd, capture_output=True, text=True)
                        if r.returncode != 0:
                            fehler += 1
                            print(f"    ❌ {r.stderr.strip()[-300:]}")
    if not a.trocken:
        print("\nDanach: Hermes neu starten (cd ~/ki-zentrale && docker compose restart) und Prüflauf starten.")
    print(f"\n{'Probelauf' if a.trocken else 'Fertig'}: {fehler} Fehler.")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
