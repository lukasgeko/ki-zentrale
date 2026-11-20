import importlib.util, pathlib, sys
import pytest

BASIS = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "datenschutz-weiche"
sys.path.insert(0, str(BASIS))
import klassifikator as k  # noqa: E402

spec = importlib.util.spec_from_file_location("weiche", BASIS / "__init__.py")
weiche = importlib.util.module_from_spec(spec); spec.loader.exec_module(weiche)

ROT = [
    "Mein Kreditangebot: 450.000 € zu 3,9 % effektiv, 10 Jahre fest.",
    "Die Sparkasse hat uns Konditionen geschickt: 3,75 % auf 800.000 Euro",
    "Mein Gehalt ist 5.200 € brutto",
    "Überweise an DE89 3704 0044 0532 0130 00 bitte",
    "IBAN: DE89370400440532013000",
    "Schreib das Eigenkapital von Papa (180.000 €) in die Datei",
    "Kontostand aktuell 23.400,50 €",
    "Meine Steuer-ID ist 12 345 678 901",
    "Karte 4111 1111 1111 1111 läuft ab",
    "🔒 Wie mache ich das am besten?",
    "privat: was denkst du über X",
    "Beispiel mit unserem Darlehensangebot: 3,9 % auf 500.000 €",
]
OK = [
    "Wie hoch ist die Grunderwerbsteuer in Bayern? 3,5 %?",
    "Der Bodenrichtwert ist 3.000 €/m² bei WGFZ 1,0.",
    "Wie hoch sind die Bauzinsen aktuell?",
    "Rechne die Kaufnebenkosten für 2.000.000 € Grundstückspreis in Bayern.",
    "Rechenbeispiel Eigenkapitalrendite: 2 Mio. EK, Jahresüberschuss nach Zinsen 90.000 €.",
    "Annuität: 1 Mio. € Darlehen, 4 % Sollzins, 2 % Anfangstilgung. Monatsrate?",
    "Ruf mich unter 0151 23456789 an",           # Telefonnummer ≠ Karte (Luhn)
    "Bestellnummer DE12 ABCD 1234 5678 9012 34", # ungültige IBAN-Prüfziffer
    "",
    None,
]

@pytest.mark.parametrize("text", ROT)
def test_rot(text):
    assert k.bewerte(text).ist_privat, text

@pytest.mark.parametrize("text", OK)
def test_ok(text):
    assert not k.bewerte(text).ist_privat, text

def test_freigabe_praefix():
    e = k.bewerte("cloud-ok: Mein Kreditangebot: 450.000 € zu 3,9 %")
    assert e.stufe == "rot" and e.freigegeben and not e.ist_privat

def test_hook_blockt_turn():
    r = weiche.vor_llm(user_message="Mein Gehalt ist 5.200 € netto")
    assert r and r["action"] == "block" and "privat" in r["message"]

def test_hook_laesst_normale_nachricht():
    assert weiche.vor_llm(user_message="Wie ist das Wetter?") is None

def test_websuche_mit_privaten_daten_blockiert():
    r = weiche.vor_werkzeug(tool_name="web_search", args={"query": "Kreditangebot 450.000 € 3,9 % gut?"})
    assert r and r["action"] == "block"

def test_websuche_freigabe_praefix_hilft_nicht():
    r = weiche.vor_werkzeug(tool_name="web_search", args={"query": "cloud-ok: IBAN DE89370400440532013000"})
    assert r and r["action"] == "block"

def test_uebergabe_an_privat_erlaubt():
    args = {"goal": "Vergleiche mein Kreditangebot 450.000 € zu 3,9 %", "profile": "privat"}
    assert weiche.vor_werkzeug(tool_name="delegate_task", args=args) is None

def test_uebergabe_an_cloud_agent_blockiert():
    args = {"goal": "Vergleiche mein Kreditangebot 450.000 € zu 3,9 %", "profile": "recherche"}
    assert weiche.vor_werkzeug(tool_name="delegate_task", args=args)["action"] == "block"

def test_andere_werkzeuge_unberuehrt():
    assert weiche.vor_werkzeug(tool_name="read_file", args={"path": "IBAN DE89370400440532013000"}) is None

def test_schwaerzen_in_mail():
    text = "Bitte zahlen auf DE89 3704 0044 0532 0130 00, Steuer-ID 12 345 678 901. Gruß"
    neu = weiche.nach_werkzeug(result=text, tool_name="gmail_nachricht_lesen")
    assert "DE89" not in neu and "12 345 678 901" not in neu and "🔒" in neu

def test_schwaerzen_nichts_zu_tun():
    assert weiche.nach_werkzeug(result="Hallo Lukas, Termin am Dienstag.", tool_name="x") is None
