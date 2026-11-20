"""Rechner-Tests mit von Hand nachgerechneten Beispielen."""
import importlib.util, json, pathlib, sys
import pytest

BASIS = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "immo-rechner"
sys.path.insert(0, str(BASIS))
import rechner as r  # noqa: E402


def restschuld_formel(p, z, rate, monate):
    i = z / 12
    q = (1 + i) ** monate
    return p * q - rate * (q - 1) / i


def test_kaufnebenkosten_bayern():
    e = r.kaufnebenkosten(2_000_000, "BY")
    assert e["grunderwerbsteuer"] == 70_000.00          # 3,5 %
    assert e["notar_und_grundbuch"] == 40_000.00        # 2 % Annahme
    assert e["nebenkosten_gesamt"] == 110_000.00
    assert e["gesamtkosten_erwerb"] == 2_110_000.00


def test_kaufnebenkosten_nrw_mit_makler():
    e = r.kaufnebenkosten(300_000, "nw", notar_grundbuch_satz=0.015, makler_satz=0.0357)
    assert e["grunderwerbsteuer"] == 19_500.00          # 6,5 %
    assert e["makler"] == pytest.approx(10_710.00)


def test_alle_16_bundeslaender():
    assert len(r.GRUNDERWERBSTEUER) == 16
    assert all(0.035 <= v <= 0.065 for v in r.GRUNDERWERBSTEUER.values())


def test_annuitaet_rate_1mio():
    assert r.annuitaet(1_000_000, 0.04, anfangstilgung=0.02)["monatsrate"] == 5_000.00


def test_annuitaet_restschuld_gegen_formel():
    e = r.annuitaet(500_000, 0.04, anfangstilgung=0.02, zinsbindung_jahre=10)
    assert e["monatsrate"] == 2_500.00
    erwartet = restschuld_formel(500_000, 0.04, 2_500, 120)   # ≈ 377.300 €
    assert e["restschuld_nach_zinsbindung"] == pytest.approx(erwartet, abs=0.05)
    assert 377_000 < e["restschuld_nach_zinsbindung"] < 377_600
    assert len(e["tilgungsplan"]) == 10
    # Zinsen + Tilgung = Summe der Raten
    s = sum(j["zinsen"] + j["tilgung"] for j in e["tilgungsplan"])
    assert s == pytest.approx(2_500 * 120, abs=1)


def test_annuitaet_mit_sondertilgung_senkt_restschuld():
    ohne = r.annuitaet(500_000, 0.04, anfangstilgung=0.02)["restschuld_nach_zinsbindung"]
    mit = r.annuitaet(500_000, 0.04, anfangstilgung=0.02, sondertilgung_pro_jahr=10_000)["restschuld_nach_zinsbindung"]
    assert mit < ohne - 100_000


def test_annuitaet_laufzeit_plausibel():
    e = r.annuitaet(500_000, 0.04, anfangstilgung=0.02)
    assert 27 < e["laufzeit_bis_volltilgung_jahre"] < 29     # bekannte Faustregel ~28 Jahre


def test_annuitaet_rate_zu_klein():
    with pytest.raises(r.EingabeFehler):
        r.annuitaet(500_000, 0.04, monatsrate=1_000)


def test_annuitaet_genau_eins():
    with pytest.raises(r.EingabeFehler):
        r.annuitaet(500_000, 0.04)


def test_rendite():
    e = r.rendite(6_000_000, 240_000)
    assert e["bruttomietrendite"] == 0.04 and e["kaufpreisfaktor"] == 25.0
    e = r.rendite(6_000_000, 240_000, nicht_umlagefaehige_kosten_jahr=30_000)
    assert e["nettomietrendite"] == 0.035


def test_verkauf():
    e = r.verkauf(7_000_000, 9_000_000, 0.03)
    assert e["vertriebskosten"] == 270_000.00
    assert e["projektgewinn_vor_steuern"] == 1_730_000.00
    assert e["marge_auf_erloes"] == pytest.approx(0.1922, abs=1e-4)


def test_eigenkapitalrendite():
    assert r.eigenkapitalrendite(2_000_000, 90_000)["eigenkapitalrendite"] == 0.045


def test_sensitivitaet_richtung():
    e = r.sensitivitaet_vermietung(2_100_000, 4_000_000, 240_000, 30_000, 1_800_000, 0.04)
    s = e["szenarien"]
    basis = s["basis"]
    assert basis["darlehen"] == 4_300_000.00
    assert basis["ueberschuss_nach_zinsen_jahr"] == 240_000 - 30_000 - 172_000
    for k in ("zins_plus_1_prozentpunkt", "baukosten_plus_15_prozent", "miete_minus_10_prozent"):
        assert s[k]["ueberschuss_nach_zinsen_jahr"] < basis["ueberschuss_nach_zinsen_jahr"]
    assert s["alles_zusammen_pessimistisch"]["ueberschuss_nach_zinsen_jahr"] == min(
        x["ueberschuss_nach_zinsen_jahr"] for x in s.values())


def test_afa():
    lin = r.afa(400_000, "linear3", 3)
    assert lin["plan"][0]["afa"] == 12_000.00
    deg = r.afa(100_000, "degressiv5", 2)
    assert [p["afa"] for p in deg["plan"]] == [5_000.00, 4_750.00]


@pytest.mark.parametrize("fn,args", [
    (r.kaufnebenkosten, (0,)), (r.kaufnebenkosten, (100_000, "XX")), (r.rendite, (0, 1000)),
    (r.kaufnebenkosten, (100_000, "BY", 2.0)),  # 200 % → Tippfehler (2 statt 0.02)
    (r.annuitaet, (100_000, 3.9, 0.02)),        # 390 % Zins → Tippfehler
])
def test_unplausible_eingaben(fn, args):
    with pytest.raises(r.EingabeFehler):
        fn(*args)


def test_plugin_antwortet_mit_json_und_fehlermeldung():
    spec = importlib.util.spec_from_file_location("iplug", BASIS / "__init__.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    reg = {}
    class Ctx:
        def register_tool(self, name, handler, **kw): reg[name] = handler
    mod.register(Ctx())
    assert len(reg) == 7
    ok = json.loads(reg["immo_kaufnebenkosten"]({"kaufpreis": 1_000_000}))
    assert ok["ok"] and ok["ergebnis"]["grunderwerbsteuer"] == 35_000
    fehler = json.loads(reg["immo_rendite"]({"gesamtinvestition": 0, "jahreskaltmiete": 1}))
    assert not fehler["ok"] and "größer als 0" in fehler["fehler"]
