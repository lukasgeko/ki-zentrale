"""Teamregeln der KI-Zentrale (reine Logik, ohne Hermes-Abhängigkeit, voll testbar).

Rollen ergeben sich aus dem Profilnamen:
  manager  = Profil "default" (Lukas' Ansprechpartner)
  pruefer  = "pruefer", "pruefer-streng"
  lokal    = "privat"
  sonst    = Spezialist
Unbekanntes oder nicht ermittelbares Profil → wird wie ein Spezialist behandelt (sicherste Rolle).
Prüf-Zwillinge "<name>-pruef" haben dieselbe Rolle wie "<name>".
"""
from __future__ import annotations

MANAGER = "default"
PRUEFER = {"pruefer", "pruefer-streng"}
LOKAL = {"privat"}
NUR_MANAGER = {"kanban_link", "kanban_unblock"}
PRUEF_BOARD = "pruefung"


def basisname(profil: str | None) -> str:
    p = (profil or "").strip()
    if p.endswith("-pruef"):
        p = p[: -len("-pruef")]
    return "default" if p in ("manager", "default") else p


def rolle(profil: str | None) -> str:
    b = basisname(profil)
    if b == MANAGER:
        return "manager"
    if b in PRUEFER:
        return "pruefer"
    if b in LOKAL:
        return "lokal"
    return "spezialist"


def pruefe(profil: str | None, tool: str, args: dict | None, eigene_karte: str | None,
           team: set[str]) -> str | None:
    """Gibt eine Blockier-Meldung zurück oder None (erlaubt)."""
    if not tool or not tool.startswith("kanban_"):
        return None
    args = args if isinstance(args, dict) else {}
    r = rolle(profil)
    pruef_modus = bool(profil and profil.endswith("-pruef"))

    def falsche_welt(name: str) -> bool:
        # Prüf-Zwillinge arbeiten nur mit Prüf-Zwillingen, echte Profile nur mit echten
        return bool(name) and (name.endswith("-pruef") != pruef_modus)

    # Abschließen/Änderungen anfordern betrifft immer nur die EIGENE Karte
    if tool in ("kanban_complete", "kanban_request_changes", "kanban_request_review", "kanban_block"):
        tid = args.get("task_id")
        if tid and eigene_karte and tid != eigene_karte:
            return f"BLOCKIERT (Teamregeln): '{tool}' ist nur für die eigene Karte erlaubt."
        if tid and not eigene_karte and r != "manager":
            return f"BLOCKIERT (Teamregeln): '{tool}' ist nur innerhalb der eigenen Karte erlaubt."

    if tool in NUR_MANAGER and r != "manager":
        return "BLOCKIERT (Teamregeln): Nur der Manager verknüpft oder entsperrt Karten. Stell eine Anfrage an den Manager."

    if tool == "kanban_create":
        ziel = str(args.get("assignee", "")).strip()
        board = str(args.get("board", "") or "").strip()
        if pruef_modus and board != PRUEF_BOARD:
            return f"BLOCKIERT (Teamregeln): Prüf-Profile arbeiten nur auf dem Board '{PRUEF_BOARD}' (board='{PRUEF_BOARD}' angeben)."
        if not pruef_modus and board == PRUEF_BOARD:
            return f"BLOCKIERT (Teamregeln): Das Board '{PRUEF_BOARD}' ist nur für Prüfläufe."
        if falsche_welt(ziel) and not (not pruef_modus and ziel == "default"):
            return "BLOCKIERT (Teamregeln): Prüf-Profile und echte Profile dürfen sich keine Karten geben."
        if r != "manager":
            if basisname(ziel) != "default":
                return ("BLOCKIERT (Teamregeln): Du vergibst keine Aufgaben an andere Agenten. "
                        "Lege eine Anfrage an den Manager an: assignee='default', Titel 'Anfrage: …'.")
            return None
        if basisname(ziel) not in team:
            return f"BLOCKIERT (Teamregeln): Unbekanntes Profil '{ziel}'. Erlaubt: {', '.join(sorted(team))}."
        body = str(args.get("body", ""))
        if basisname(ziel) not in ("default",) and "akzeptanz" not in body.lower():
            return ("BLOCKIERT (Teamregeln): Jede Karte braucht Akzeptanzkriterien. "
                    "Bitte den Kartentext nach Vorlage ergänzen (Ziel, Eingaben, Akzeptanzkriterien, Frist, Ampel, Risiko, Prüfer).")
        return None

    if tool == "kanban_complete":
        if r in ("pruefer", "manager"):
            return None
        if r == "lokal":
            return ("BLOCKIERT (Teamregeln): Deine Ergebnisse prüft Lukas selbst. Nutze kanban_block mit kind "
                    "'needs_input' und 'Lukas prüfen: Ergebnis in <datei>'.")
        return ("BLOCKIERT (Teamregeln): Du schließt Karten nicht selbst ab. Nutze kanban_request_review mit "
                "reviewer='pruefer' oder 'pruefer-streng' (laut Karte; im Zweifel 'pruefer-streng').")

    if tool == "kanban_request_review":
        if r == "lokal":
            return ("BLOCKIERT (Teamregeln): Cloud-Prüfer dürfen private Ergebnisse nicht sehen. "
                    "Nutze kanban_block mit kind 'needs_input' und 'Lukas prüfen: …'.")
        rev_roh = str(args.get("reviewer", "")).strip()
        reviewer = basisname(rev_roh)
        if reviewer not in PRUEFER or falsche_welt(rev_roh):
            return "BLOCKIERT (Teamregeln): reviewer muss 'pruefer' oder 'pruefer-streng' sein."
        if r == "pruefer":
            return "BLOCKIERT (Teamregeln): Prüfer schließen ab oder fordern Änderungen an, sie geben nicht weiter."
        return None

    if tool == "kanban_request_changes" and r != "pruefer":
        return "BLOCKIERT (Teamregeln): Nur Prüfer fordern Änderungen an."
    return None
