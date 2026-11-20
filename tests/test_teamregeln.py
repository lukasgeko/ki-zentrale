"""Teamregeln: wer darf auf dem Aufgaben-Board was?"""
import importlib.util, json, pathlib, sys
import pytest

BASIS = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "teamregeln"
sys.path.insert(0, str(BASIS))
import regeln as r  # noqa: E402

TEAM = {"default", "posteingang", "alltag", "recherche", "immo-projekt", "immo-markt", "immo-bewertung",
        "immo-recht", "immo-dokumente", "privat", "pruefer", "pruefer-streng"}
KARTE = "Ziel: x\nEingaben: y\nAkzeptanzkriterien:\n- a\nFrist: ohne\nAmpel: 🟢\nRisiko: normal\nPrüfer: pruefer"


def p(profil, tool, args=None, eigene="t_1"):
    return r.pruefe(profil, tool, args or {}, eigene, TEAM)


def test_manager_vergibt_an_spezialisten():
    assert p("default", "kanban_create", {"assignee": "immo-markt", "title": "t", "body": KARTE}, None) is None


def test_manager_braucht_akzeptanzkriterien():
    assert "Akzeptanzkriterien" in p("default", "kanban_create", {"assignee": "recherche", "body": "mach mal"}, None)


def test_manager_unbekanntes_profil():
    assert "Unbekanntes Profil" in p("default", "kanban_create", {"assignee": "hacker", "body": KARTE}, None)


@pytest.mark.parametrize("spez", ["recherche", "immo-dokumente", "posteingang", "pruefer"])
def test_spezialist_vergibt_nicht_direkt(spez):
    assert "Anfrage an den Manager" in p(spez, "kanban_create", {"assignee": "immo-markt", "body": KARTE})


def test_spezialist_darf_anfrage_an_manager():
    assert p("immo-dokumente", "kanban_create", {"assignee": "default", "title": "Anfrage: Zahlen"}) is None


@pytest.mark.parametrize("spez", ["recherche", "immo-bewertung", "alltag", None, "", "custom"])
def test_spezialist_schliesst_nicht_selbst_ab(spez):
    assert "kanban_request_review" in p(spez, "kanban_complete", {"summary": "fertig"})


def test_unbekanntes_profil_ist_spezialist():
    assert r.rolle(None) == "spezialist" and r.rolle("irgendwas") == "spezialist"


def test_pruefer_schliesst_ab_und_fordert_aenderungen():
    assert p("pruefer", "kanban_complete", {"summary": "Abgenommen"}) is None
    assert p("pruefer-streng", "kanban_request_changes", {"reason": "1. …"}) is None


def test_nur_pruefer_fordern_aenderungen():
    assert p("immo-recht", "kanban_request_changes", {"reason": "x"})


@pytest.mark.parametrize("rev,ok", [("pruefer", True), ("pruefer-streng", True), ("default", False),
                                    ("immo-recht", False), ("", False), ("pruefer-pruef", False)])
def test_review_nur_an_pruefer(rev, ok):
    assert (p("immo-recht", "kanban_request_review", {"summary": "s", "reviewer": rev}) is None) == ok


def test_privat_wird_von_lukas_geprueft():
    assert "Lukas" in p("privat", "kanban_complete", {"summary": "x"})
    assert "Lukas" in p("privat", "kanban_request_review", {"summary": "x", "reviewer": "pruefer"})
    assert p("privat", "kanban_block", {"kind": "needs_input", "reason": "Lukas prüfen: Ergebnis in …"}) is None


def test_nur_eigene_karte():
    assert "eigene Karte" in p("pruefer", "kanban_complete", {"task_id": "t_99"}, eigene="t_1")
    assert p("pruefer", "kanban_complete", {"task_id": "t_1"}, eigene="t_1") is None
    assert p("immo-markt", "kanban_complete", {"task_id": "t_5"}, eigene=None)


def test_link_und_unblock_nur_manager():
    assert p("immo-projekt", "kanban_link", {"parent_id": "a", "child_id": "b"})
    assert p("default", "kanban_link", {"parent_id": "a", "child_id": "b"}, None) is None


def test_pruef_welt_getrennt():
    # Prüf-Manager vergibt nur an Prüf-Zwillinge
    assert p("manager-pruef", "kanban_create", {"assignee": "recherche-pruef", "body": KARTE, "board": "pruefung"}, None) is None
    assert "Board" in p("manager-pruef", "kanban_create", {"assignee": "recherche-pruef", "body": KARTE}, None)
    assert "Prüf-Profile" in p("manager-pruef", "kanban_create", {"assignee": "recherche", "body": KARTE, "board": "pruefung"}, None)
    assert "nur für Prüfläufe" in p("default", "kanban_create", {"assignee": "recherche", "body": KARTE, "board": "pruefung"}, None)
    assert "Prüf-Profile" in p("default", "kanban_create", {"assignee": "recherche-pruef", "body": KARTE}, None)
    assert p("recherche-pruef", "kanban_request_review", {"summary": "s", "reviewer": "pruefer-pruef"}) is None


def test_andere_werkzeuge_unberuehrt():
    assert p("recherche", "web_search", {"query": "x"}) is None
    assert p("recherche", "kanban_show", {}) is None and p("recherche", "kanban_comment", {"task_id": "t", "body": "x"}) is None


def test_plugin_hook_mit_teamdatei(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("tplug", BASIS / "__init__.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    monkeypatch.setattr(m, "_TEAM_DATEI", tmp_path / "team.json")
    monkeypatch.setattr(m, "_profil", lambda: "default")
    # ohne Teamliste: Manager kann nichts vergeben (fail-closed)
    assert m.vor_werkzeug(tool_name="kanban_create", args={"assignee": "recherche", "body": KARTE})["action"] == "block"
    (tmp_path / "team.json").write_text(json.dumps({"profile": sorted(TEAM)}))
    assert m.vor_werkzeug(tool_name="kanban_create", args={"assignee": "recherche", "body": KARTE}) is None
