#!/usr/bin/env python3
"""Spielt Agenten-Profile und Plugins aus dem Repo in Hermes ein (Phase 2/3).

STATUS: Entwurf, gegen die Hermes-Doku geschrieben, aber noch NICHT gegen einen laufenden Server
getestet. Erster echter Lauf gemeinsam mit Claude Code, erst mit --trocken, dann mit --ausfuehren.

Was passiert pro Agent (agents/<name>/):
  1. Profil anlegen (falls nicht vorhanden) + Prüf-Zwilling "<name>-pruef" für den Prüflauf
  2. SOUL.md = agents/<name>/SOUL.md + agents/_gemeinsam.md
  3. Modell/Provider setzen, nicht erlaubte Werkzeug-Gruppen abschalten, Plugins freischalten
Der Agent "manager" ist das Standard-Profil ("default").

Aufruf auf dem Server (Repo liegt in ~/ki-zentrale-repo, Daten in ~/ki-zentrale/hermes-data):
  python3 deploy/agenten_einspielen.py --trocken          # zeigt nur, was passieren würde
  python3 deploy/agenten_einspielen.py --ausfuehren       # führt aus (vorher Backup!)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
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
    # in toolsets.py vorhanden, nicht in der Doku-Tabelle (kalte Prüfung)
    "bot_room", "onboarding", "context_engine", "discord", "discord_admin", "feishu_doc", "feishu_drive",
]
# Vor dem ersten echten Lauf mit `hermes tools list` abgleichen: unbekannte Gruppen ergänzen.


BOARDS = ["immobilienprojekt", "alltag", "pruefung"]
TEAM_NAMEN: list[str] = []


def pruef_soul(text: str, namen: list[str]) -> str:
    """Prüf-Zwillinge sprechen nur mit Prüf-Zwillingen und arbeiten auf dem Board 'pruefung'.
    Profilnamen werden als ganze Namen ersetzt (nicht in Pfaden wie projekte/x/privat/ und nicht
    als Teil längerer Namen wie pruefer-streng)."""
    for n in sorted(namen, key=len, reverse=True):
        if n == "default":
            continue
        text = re.sub(rf"(?<![\w/-]){re.escape(n)}(?![\w/-])", f"{n}-pruef", text)
    text = re.sub(r"(['\"`])default(['\"`])", r"\g<1>manager-pruef\g<2>", text)
    text = text.replace("assignee: default", "assignee: manager-pruef")
    text = re.sub(r'board: "(immobilienprojekt|alltag)"', 'board: "pruefung"', text)
    return text + ("\n\n## PRÜFMODUS\nDu bist ein Prüf-Zwilling. Bei JEDEM Board-Werkzeug (kanban_*) gilt "
                   "board='pruefung'. Der Manager heißt hier `manager-pruef`, die Prüfer `pruefer-pruef` und "
                   "`pruefer-streng-pruef`.\n")


def profile() -> list[dict]:
    out = []
    for d in sorted((REPO / "agents").iterdir()):
        if d.is_dir():
            p = yaml.safe_load((d / "profile.yaml").read_text())
            p["soul"] = (d / "SOUL.md").read_text() + (REPO / "agents" / "_gemeinsam.md").read_text()
            out.append(p)
    TEAM_NAMEN[:] = sorted({"default" if x["name"] == "manager" else x["name"] for x in out})
    return out


def m_lokal(p: dict) -> bool:
    return p["modell"]["provider"] == "ollama"


def hermes_name(agent: str, pruef: bool) -> str:
    if agent == "manager":
        return "manager-pruef" if pruef else "default"
    return f"{agent}-pruef" if pruef else agent


def schritte(p: dict, pruef: bool) -> list[tuple[str, object]]:
    name = hermes_name(p["name"], pruef)
    pfx = [] if name == "default" else ["-p", name]
    home = profil_home(name)
    aus = sorted(set(ALLE_TOOLSETS) - set(p["toolsets"]))
    s: list[tuple[str, object]] = []
    if name != "default" and not home.exists():
        create = ["profile", "create", name, "--description", p["beschreibung"]]
        if m_lokal(p):
            # Lokales Profil bekommt KEINE Cloud-Schlüssel: so kann es auch versehentlich nie in die Cloud ausweichen
            create.append("--no-credentials")
        s.append(("befehl", create))
    s.append(("datei", (home / "SOUL.md", pruef_soul(p["soul"], TEAM_NAMEN) if pruef else p["soul"])))
    m = p["modell"]
    s.append(("befehl", pfx + ["config", "set", "model.provider", "custom" if m["provider"] == "ollama" else m["provider"]]))
    s.append(("befehl", pfx + ["config", "set", "model.default", m["model"]]))
    if m["provider"] == "ollama":
        s.append(("befehl", pfx + ["config", "set", "model.base_url", OLLAMA_URL]))
    s.append(("befehl", pfx + ["config", "set", "agent.disabled_toolsets", json.dumps(aus)]))
    s.append(("befehl", pfx + ["config", "set", "plugins.enabled", json.dumps(p["plugins"])]))
    if p["name"] == "manager":
        s.append(("befehl", pfx + ["config", "set", "kanban.auto_decompose", "false"]))
    for k, v in (("approvals.mode", "manual"), ("approvals.cron_mode", "deny"),
                 ("approvals.unattended_mode", "deny"), ("approvals.single_query_mode", "deny")):
        s.append(("befehl", pfx + ["config", "set", k, v]))
    return s


def profil_home(name: str) -> Path:
    return DATEN if name == "default" else DATEN / "profiles" / name


def plugins_kopieren(p: dict, name: str, pruef: bool, trocken: bool) -> None:
    """Hermes sucht Plugins im Ordner des jeweiligen Profils → in JEDES Profil kopieren."""
    ziel = profil_home(name) / "plugins"
    stempel = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for pl_name in p["plugins"]:
        quelle = REPO / "plugins" / pl_name
        print(f"  📦 Plugin {pl_name} → {ziel / pl_name}{'  (TESTMODUS)' if pruef and pl_name == 'gmail-entwuerfe' else ''}")
        if trocken:
            continue
        ziel.mkdir(parents=True, exist_ok=True)
        if (ziel / pl_name).exists():  # nichts löschen: alte Fassung mit Zeitstempel beiseitelegen
            alt = ziel.parent / "plugins-alt"
            alt.mkdir(exist_ok=True)
            shutil.move(str(ziel / pl_name), str(alt / f"{pl_name}-{stempel}"))
        shutil.copytree(quelle, ziel / pl_name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if pl_name == "teamregeln":
            (ziel / pl_name / "team.json").write_text(json.dumps({"profile": TEAM_NAMEN}, ensure_ascii=False))
        if pruef and pl_name == "gmail-entwuerfe":
            (ziel / pl_name / "TESTMODUS").write_text("Prüfprofil: simuliertes Postfach, nie das echte Konto.\n")


def pruefe_privat_ohne_schluessel(trocken: bool) -> int:
    env = profil_home("privat") / ".env"
    if trocken or not env.exists():
        return 0
    treffer = [z.split("=", 1)[0] for z in env.read_text().splitlines() if re.match(r"^[A-Z_]*(API_KEY|TOKEN)=.+", z)]
    if treffer:
        print(f"  ❌ Profil privat enthält Cloud-Schlüssel ({', '.join(treffer)}). Bitte mit Claude entfernen (Proceed nötig).")
        return 1
    print("  ✅ Profil privat hat keine Cloud-Schlüssel")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--trocken", action="store_true")
    g.add_argument("--ausfuehren", action="store_true")
    ap.add_argument("--agent", action="append", help="nur diese Agenten")
    ap.add_argument("--ohne-pruefprofile", action="store_true")
    a = ap.parse_args(argv)

    fehler = 0
    for b in BOARDS:  # einmalig; ein bereits vorhandenes Board meldet nur einen Hinweis
        cmd = shlex.split(HERMES) + ["kanban", "boards", "create", b]
        print("  $ " + " ".join(shlex.quote(c) for c in cmd))
        if not a.trocken:
            subprocess.run(cmd, capture_output=True, text=True)
    for p in profile():
        if a.agent and p["name"] not in a.agent:
            continue
        for pruef in ([False] if a.ohne_pruefprofile else [False, True]):
            name = hermes_name(p["name"], pruef)
            print(f"▶ {name}")
            erst_anlegen = [s for s in schritte(p, pruef) if s[0] == "befehl" and s[1][:2] == ["profile", "create"]]
            rest = [s for s in schritte(p, pruef) if s not in erst_anlegen]
            for art, inhalt in erst_anlegen:
                cmd = shlex.split(HERMES) + list(inhalt)
                print("  $ " + " ".join(shlex.quote(c) for c in cmd))
                if not a.trocken and subprocess.run(cmd).returncode != 0:
                    fehler += 1
            plugins_kopieren(p, name, pruef, a.trocken)
            for art, inhalt in rest:
                if art == "datei":
                    pfad, text = inhalt
                    print(f"  📝 {pfad}")
                    if not a.trocken:
                        pfad.parent.mkdir(parents=True, exist_ok=True)
                        if pfad.exists():
                            shutil.copy2(pfad, pfad.with_name(f"SOUL.bak-{dt.datetime.now():%Y%m%d-%H%M%S}.md"))
                        pfad.write_text(text)
                else:
                    cmd = shlex.split(HERMES) + list(inhalt)
                    print("  $ " + " ".join(shlex.quote(c) for c in cmd))
                    if not a.trocken:
                        r = subprocess.run(cmd, capture_output=True, text=True)
                        if r.returncode != 0:
                            fehler += 1
                            print(f"    ❌ {r.stderr.strip()[-300:]}")
    fehler += pruefe_privat_ohne_schluessel(a.trocken)
    if not a.trocken:
        print("\nDanach: 1) Hermes neu starten (cd ~/ki-zentrale && docker compose restart)")
        print("        2) je Profil prüfen: hermes -p <name> plugins list  → alle Plugins 'enabled'? Sonst STOPP.")
        print("        3) Prüflauf: python3 evals/pruefen.py --alle")
    print("\nHinweis: Board-Einrichtung (einmalig) siehe Ausgabe oben; Auto-Zerlegung ist aus.")
    print(f"\n{'Probelauf' if a.trocken else 'Fertig'}: {fehler} Fehler.")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
