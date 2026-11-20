"""Teamregeln der KI-Zentrale (reine Logik, ohne Hermes-Abhängigkeit, voll testbar).

Rollen ergeben sich aus dem Profilnamen:
  manager  = Profil "default" (Lukas' Ansprechpartner)
  pruefer  = "pruefer", "pruefer-streng"
  lokal    = "privat"
  sonst    = Spezialist
Unbekanntes oder nicht ermittelbares Profil → Spezialist (sicherste Rolle).
Prüf-Zwillinge "<name>-pruef" haben dieselbe Rolle wie "<name>", leben aber nur auf dem Board "pruefung".

`karte(task_id)` liefert (assignee, text) einer Karte oder None, wenn sie nicht lesbar ist.
Ist eine Karte nicht lesbar, wird im Zweifel blockiert ("fail closed").
"""
from __future__ import annotations

from typing import Callable, Optional

MANAGER = "default"
PRUEFER = {"pruefer", "pruefer-streng"}
LOKAL = {"privat"}
PRUEF_BOARD = "pruefung"
KartenLeser = Callable[[str], Optional[tuple]]


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


def _ist_kritisch(text: str) -> bool:
    t = (text or "").lower()
    return "pruefer-streng" in t or "risiko: kritisch" in t


def pruefe(profil: str | None, tool: str, args: dict | None, eigene_karte: str | None,
           team: set[str], board_env: str | None = None, karte: KartenLeser | None = None) -> str | None:
    """Gibt eine Blockier-Meldung zurück oder None (erlaubt)."""
    if not tool or not tool.startswith("kanban_"):
        return None
    args = args if isinstance(args, dict) else {}
    r = rolle(profil)
    pm = bool(profil and profil.endswith("-pruef"))
    sfx = "-pruef" if pm else ""
    mgr = "manager-pruef" if pm else "default"
    lese = karte or (lambda _tid: None)

    def falsche_welt(name: str) -> bool:
        return bool(name) and name.endswith("-pruef") != pm

    # --- 1. Board-Trennung für ALLE Board-Werkzeuge ---
    board = str(args.get("board") or board_env or "").strip().lower()
    if pm and board != PRUEF_BOARD:
        return f"BLOCKIERT (Teamregeln): Prüf-Profile arbeiten nur auf dem Board '{PRUEF_BOARD}' (board='{PRUEF_BOARD}' angeben)."
    if not pm and board == PRUEF_BOARD:
        return f"BLOCKIERT (Teamregeln): Das Board '{PRUEF_BOARD}' ist nur für Prüfläufe."

    tid = str(args.get("task_id") or "").strip() or None
    ziel_karte = tid or eigene_karte

    def manager_eigene_anfrage() -> bool:
        k = lese(tid) if tid else None
        return r == "manager" and k is not None and basisname(k[0]) == "default"

    # --- 2. Statuswechsel nur an der eigenen Karte ---
    if tool in ("kanban_complete", "kanban_request_changes", "kanban_request_review", "kanban_block"):
        if eigene_karte is None and tid is not None and tool != "kanban_block" and not (
                tool == "kanban_complete" and manager_eigene_anfrage()):
            return ("BLOCKIERT (Teamregeln): Fremde Karten werden nicht abgeschlossen oder zur Prüfung gegeben – "
                    "das macht nur der jeweilige Bearbeiter bzw. Prüfer.")
        if tid and eigene_karte and tid != eigene_karte:
            return f"BLOCKIERT (Teamregeln): '{tool}' ist nur für die eigene Karte erlaubt."
        if tool == "kanban_block" and eigene_karte is None and tid and r != "manager":
            return "BLOCKIERT (Teamregeln): Nur eigene Karten blockieren."

    # --- 3. Verknüpfen / Entsperren ---
    if tool == "kanban_link":
        if r == "manager":
            return None
        if eigene_karte and str(args.get("child_id", "")) == eigene_karte:
            return None  # eigene Karte von einer Anfrage abhängig machen
        return "BLOCKIERT (Teamregeln): Du darfst nur deine eigene Karte (child_id) von einer Anfrage abhängig machen."
    if tool == "kanban_unblock":
        if r != "manager":
            return "BLOCKIERT (Teamregeln): Nur der Manager entsperrt Karten."
        k = lese(tid) if tid else None
        if k is None or basisname(k[0]) in LOKAL:
            return ("BLOCKIERT (Teamregeln): Diese Karte gibt nur Lukas im Dashboard frei "
                    "(private Ergebnisse oder nicht lesbare Karte).")
        return None

    # --- 4. Karten anlegen ---
    if tool == "kanban_create":
        ziel = str(args.get("assignee", "")).strip()
        if falsche_welt(ziel):
            return "BLOCKIERT (Teamregeln): Prüf-Profile und echte Profile dürfen sich keine Karten geben."
        if r != "manager":
            if basisname(ziel) != "default":
                return ("BLOCKIERT (Teamregeln): Du vergibst keine Aufgaben an andere Agenten. "
                        f"Lege eine Anfrage an den Manager an: assignee='{mgr}', Titel 'Anfrage: …'.")
            return None
        if basisname(ziel) not in team:
            return f"BLOCKIERT (Teamregeln): Unbekanntes Profil '{ziel}'."
        if basisname(ziel) in PRUEFER:
            return ("BLOCKIERT (Teamregeln): Prüfer bekommen keine Facharbeit. Vergib die Karte an einen Spezialisten; "
                    "geprüft wird über kanban_request_review.")
        if basisname(ziel) != "default" and "akzeptanz" not in str(args.get("body", "")).lower():
            return ("BLOCKIERT (Teamregeln): Jede Karte braucht Akzeptanzkriterien. Bitte den Kartentext nach Vorlage "
                    "ergänzen (Ziel, Eingaben, Akzeptanzkriterien, Frist, Ampel, Risiko, Prüfer).")
        return None

    # --- 5. Kommentare des lokalen Profils nur an der eigenen Karte ---
    if tool == "kanban_comment" and r == "lokal" and (not eigene_karte or ziel_karte != eigene_karte):
        return "BLOCKIERT (Teamregeln): Das Profil privat kommentiert nur die eigene Karte."

    # --- 6. Abschließen ---
    if tool == "kanban_complete":
        k = lese(ziel_karte) if ziel_karte else None
        if k is not None and basisname(k[0]) in LOKAL:
            return "BLOCKIERT (Teamregeln): Private Karten schließt nur Lukas im Dashboard ab."
        if r == "pruefer":
            return None
        if r == "manager":
            return None if (eigene_karte or manager_eigene_anfrage()) else \
                "BLOCKIERT (Teamregeln): Der Manager schließt nur seine eigenen Anfrage-Karten ab."
        if r == "lokal":
            return ("BLOCKIERT (Teamregeln): Deine Ergebnisse prüft Lukas selbst. Nutze kanban_block mit kind "
                    "'needs_input' und 'Lukas prüfen: Ergebnis in <datei>'.")
        return (f"BLOCKIERT (Teamregeln): Du schließt Karten nicht selbst ab. Nutze kanban_request_review mit "
                f"reviewer='pruefer{sfx}' oder 'pruefer-streng{sfx}' (laut Karte; im Zweifel 'pruefer-streng{sfx}').")

    # --- 7. Prüfung anfordern ---
    if tool == "kanban_request_review":
        if r == "lokal":
            return ("BLOCKIERT (Teamregeln): Cloud-Prüfer dürfen private Ergebnisse nicht sehen. "
                    "Nutze kanban_block mit kind 'needs_input' und 'Lukas prüfen: …'.")
        if r == "pruefer":
            return "BLOCKIERT (Teamregeln): Prüfer schließen ab, fordern Änderungen an oder eskalieren per kanban_block."
        rev_roh = str(args.get("reviewer", "")).strip()
        reviewer = basisname(rev_roh)
        if reviewer not in PRUEFER or falsche_welt(rev_roh):
            return f"BLOCKIERT (Teamregeln): reviewer muss 'pruefer{sfx}' oder 'pruefer-streng{sfx}' sein."
        k = lese(ziel_karte) if ziel_karte else None
        if k is not None and basisname(k[0]) in LOKAL:
            return "BLOCKIERT (Teamregeln): Private Karten prüft nur Lukas."
        streng_noetig = k is None or _ist_kritisch(k[1])  # nicht lesbar → im Zweifel streng
        if streng_noetig and reviewer != "pruefer-streng":
            return (f"BLOCKIERT (Teamregeln): Diese Karte ist kritisch (oder nicht lesbar) – "
                    f"reviewer='pruefer-streng{sfx}' verwenden.")
        return None

    if tool == "kanban_request_changes" and r != "pruefer":
        return "BLOCKIERT (Teamregeln): Nur Prüfer fordern Änderungen an."
    return None
