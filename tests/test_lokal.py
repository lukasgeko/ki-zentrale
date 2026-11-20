"""Tests für lokal/ki-lokal.sh (Mac-Testvariante). Docker wird durch eine Attrappe ersetzt."""
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SKRIPT = REPO / "lokal" / "ki-lokal.sh"
COMPOSE = REPO / "lokal" / "docker-compose.lokal.yml"
TESTKEY = "sk-ant-TESTKEY-nur-fuer-den-test-123"

ATTRAPPE = """#!/bin/bash
echo "$@" >> "$ATTRAPPE_LOG"
[[ "${ATTRAPPE_FAIL:-}" == "$1" ]] && { echo "fehler: $1 absichtlich gescheitert" >&2; exit 1; }
case "$1" in
  info|logs|stats) exit 0 ;;
  pull) exit 0 ;;
  image) echo "nousresearch/hermes-agent@sha256:abc123"; exit 0 ;;
  inspect) echo "ki-lokal"; exit 0 ;;
  ps) echo hermes; exit 0 ;;
  exec)
    if [[ "$*" == *"plugins list"* && -z "${ATTRAPPE_NOPLUGIN:-}" ]]; then echo "datenschutz-weiche  enabled"; fi
    exit 0 ;;
  compose) exit 0 ;;
esac
exit 0
"""

CURL = """#!/bin/bash
[[ -n "${CURL_FAIL:-}" ]] && exit 22
if [[ "$*" == *"/api/status"* ]]; then
  if [[ -n "${CURL_NOAUTH:-}" ]]; then echo '{"auth_required": false}'; else echo '{"auth_required": true, "auth_providers": ["basic"]}'; fi
fi
exit 0
"""


@pytest.fixture
def umgebung(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    d = bin_ / "docker"
    d.write_text(ATTRAPPE)
    d.chmod(0o755)
    c = bin_ / "curl"
    c.write_text(CURL)
    c.chmod(0o755)
    env = dict(os.environ)
    env.update(
        PATH=f"{bin_}:{os.environ['PATH']}",
        HOME=str(tmp_path / "home"),
        KI_LOKAL_DIR=str(tmp_path / "lokal"),
        KI_LOKAL_PYTHON=sys.executable,
        KI_LOKAL_WARTEN="1",
        ATTRAPPE_LOG=str(tmp_path / "docker.log"),
    )
    (tmp_path / "home").mkdir()
    return env, tmp_path


def lauf(env, *args, eingabe=""):
    return subprocess.run(["bash", str(SKRIPT), *args], env=env, input=eingabe, text=True,
                          capture_output=True, timeout=120)


def test_compose_nur_lokal_erreichbar_und_begrenzt():
    c = yaml.safe_load(COMPOSE.read_text())["services"]["hermes"]
    assert c["ports"] == ["127.0.0.1:9119:9119"]
    assert "network_mode" not in c
    assert c["mem_limit"] == "3g"
    assert c["restart"] == "no"


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck fehlt")
def test_shellcheck_sauber():
    r = subprocess.run(["shellcheck", str(SKRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_einrichten_legt_alles_an_und_zeigt_schluessel_nie(umgebung):
    env, tmp = umgebung
    r = lauf(env, "einrichten", eingabe=TESTKEY + "\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert TESTKEY not in r.stdout + r.stderr
    lokal = tmp / "lokal"
    envdatei = lokal / "hermes-data" / ".env"
    assert stat.S_IMODE(envdatei.stat().st_mode) == 0o600
    text = envdatei.read_text()
    assert f"ANTHROPIC_API_KEY={TESTKEY}" in text
    assert "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=" in text
    assert stat.S_IMODE((lokal / "dashboard-login.txt").stat().st_mode) == 0o600
    assert (lokal / "HERMES_VERSION.txt").read_text().strip().startswith("nousresearch/hermes-agent@sha256:")
    assert (lokal / "hermes-data" / "SOUL.md").exists()
    log = (tmp / "docker.log").read_text()
    assert "config set approvals.mode manual" in log
    assert "config set approvals.unattended_mode deny" in log
    # Team wurde in die Datenordner eingespielt (Plugins pro Profil)
    assert (lokal / "hermes-data" / "plugins" / "datenschutz-weiche").exists()
    assert (lokal / "hermes-data" / "profiles" / "recherche" / "plugins" / "teamregeln" / "team.json").exists()
    assert TESTKEY not in log, "Schlüssel darf nie in Docker-Argumenten stehen"
    assert "restart hermes" in log


def test_einrichten_zweimal_ist_harmlos_und_fragt_nicht_nochmal(umgebung):
    env, tmp = umgebung
    assert lauf(env, "einrichten", eingabe=TESTKEY + "\n").returncode == 0
    pw1 = (tmp / "lokal" / "dashboard-login.txt").read_text()
    r = lauf(env, "einrichten", eingabe="")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp / "lokal" / "dashboard-login.txt").read_text() == pw1


def test_falscher_schluessel_bricht_ab_ohne_zu_schreiben(umgebung):
    env, tmp = umgebung
    r = lauf(env, "einrichten", eingabe="irgendwas\n")
    assert r.returncode != 0
    assert "nicht wie ein Anthropic-Schlüssel" in r.stdout + r.stderr
    envdatei = tmp / "lokal" / "hermes-data" / ".env"
    assert not envdatei.exists() or "ANTHROPIC_API_KEY=irgendwas" not in envdatei.read_text()


def test_zuruecksetzen_verschiebt_statt_zu_loeschen(umgebung):
    env, tmp = umgebung
    lauf(env, "einrichten", eingabe=TESTKEY + "\n")
    r = lauf(env, "zuruecksetzen", eingabe="nein\n")
    assert r.returncode != 0 and (tmp / "lokal" / "hermes-data").exists()
    r = lauf(env, "zuruecksetzen", eingabe="JA\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tmp / "lokal" / "hermes-data").exists()
    verschoben = list((tmp / "lokal" / "_papierkorb").glob("hermes-data-*"))
    assert len(verschoben) == 1 and (verschoben[0] / ".env").exists()


def test_ohne_docker_klare_meldung(umgebung):
    env, tmp = umgebung
    (tmp / "bin" / "docker").unlink()
    env["PATH"] = str(tmp / "bin") + ":/usr/bin:/bin"
    if shutil.which("docker", path=env["PATH"]):
        pytest.skip("echtes docker im PATH")
    r = lauf(env, "einrichten")
    assert r.returncode != 0 and "Docker Desktop" in r.stdout + r.stderr


def test_mehr_als_8gb_bricht_nicht_stumm_ab(umgebung):
    env, tmp = umgebung
    sysctl = tmp / "bin" / "sysctl"
    sysctl.write_text("#!/bin/bash\necho 17179869184\n")
    sysctl.chmod(0o755)
    r = lauf(env, "einrichten", eingabe=TESTKEY + "\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "16 GB" in r.stdout and "Fertig" in r.stdout


def test_pull_scheitert_deutsche_meldung(umgebung):
    env, tmp = umgebung
    env["ATTRAPPE_FAIL"] = "pull"
    r = lauf(env, "einrichten", eingabe=TESTKEY + "\n")
    assert r.returncode != 0
    assert "Abgebrochen im Schritt: 2/6 Hermes laden" in r.stderr


def test_dashboard_antwortet_nicht_ist_nicht_fertig(umgebung):
    env, tmp = umgebung
    env["CURL_FAIL"] = "1"
    r = lauf(env, "einrichten", eingabe=TESTKEY + "\n")
    assert r.returncode != 0
    assert "NICHT fertig" in r.stderr and "Fertig." not in r.stdout


def test_dashboard_ohne_login_wird_abgelehnt(umgebung):
    env, tmp = umgebung
    env["CURL_NOAUTH"] = "1"
    r = lauf(env, "einrichten", eingabe=TESTKEY + "\n")
    assert r.returncode != 0 and "verlangt kein Login" in r.stderr


def test_weiche_nicht_aktiv_stoppt(umgebung):
    env, tmp = umgebung
    env["ATTRAPPE_NOPLUGIN"] = "1"
    r = lauf(env, "einrichten", eingabe=TESTKEY + "\n")
    assert r.returncode != 0 and "Datenschutz-Weiche" in r.stderr and "NICHT" in r.stderr


def test_einspielen_fehler_wird_gemeldet(umgebung):
    env, tmp = umgebung
    env["ATTRAPPE_FAIL"] = "exec"
    r = lauf(env, "einrichten", eingabe=TESTKEY + "\n")
    assert r.returncode != 0


def test_login_datei_fehlt_wird_neu_angelegt(umgebung):
    env, tmp = umgebung
    assert lauf(env, "einrichten", eingabe=TESTKEY + "\n").returncode == 0
    (tmp / "lokal" / "dashboard-login.txt").unlink()
    r = lauf(env, "einrichten")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp / "lokal" / "dashboard-login.txt").exists()


def test_start_stopp_status(umgebung):
    env, tmp = umgebung
    assert lauf(env, "einrichten", eingabe=TESTKEY + "\n").returncode == 0
    for befehl in ("start", "stopp", "status"):
        r = lauf(env, befehl)
        assert r.returncode == 0, (befehl, r.stdout, r.stderr)


def test_ohne_einrichtung_klare_meldung(umgebung):
    env, tmp = umgebung
    r = lauf(env, "start")
    assert r.returncode != 0 and "einrichten" in r.stdout + r.stderr
