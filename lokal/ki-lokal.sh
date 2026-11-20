#!/bin/bash
# KI-Zentrale lokal auf dem Mac testen (PRD 16). Läuft mit der alten Mac-Bash 3.2.
# Aufruf: bash lokal/ki-lokal.sh <befehl>
#   einrichten      einmalig: Hermes laden, Login anlegen, Team einspielen, starten
#   start | stopp   Agenten starten / anhalten (stopp gibt den Arbeitsspeicher frei)
#   status          läuft es? Speicherverbrauch?
#   agenten         Team neu einspielen (nach Änderungen im Repo)
#   pruefen [name…] Prüffragen stellen (kostet API-Guthaben, Standard: nur "manager", max 3 $)
#   zuruecksetzen   Testdaten nach _papierkorb verschieben (nichts wird gelöscht)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOKAL="${KI_LOKAL_DIR:-$HOME/ki-lokal}"
DATEN="$LOKAL/hermes-data"
export KI_LOKAL_DIR="$LOKAL"
DC=(docker compose -p ki-lokal -f "$REPO/lokal/docker-compose.lokal.yml")

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '  ✅ %s\n' "$*"; }
warn() { printf '  ⚠️  %s\n' "$*"; }
stop_mit() { printf '\n❌ %s\n' "$*" >&2; exit 1; }

pruefe_docker() {
  command -v docker >/dev/null 2>&1 || stop_mit "Docker ist nicht installiert. Bitte Docker Desktop installieren: https://www.docker.com/products/docker-desktop/"
  docker info >/dev/null 2>&1 || stop_mit "Docker läuft nicht. Bitte das Programm 'Docker Desktop' öffnen, warten bis unten links 'Engine running' steht, dann nochmal."
}

pruefe_arbeitsspeicher() {
  local b gb
  b="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"; gb=$(( b / 1073741824 ))
  if [[ "$gb" -gt 0 ]]; then
    ok "Arbeitsspeicher dieses Macs: ${gb} GB (Hermes darf höchstens 3 GB nutzen)"
    [[ "$gb" -le 8 ]] && warn "Bei 8 GB: andere große Programme (Browser mit vielen Tabs, Spiele) vorher schließen. In Docker Desktop → Einstellungen → Resources → Memory auf 4 GB stellen."
  fi
}

# Schlüssel/Werte in .env setzen, ohne sie irgendwo auszugeben
env_setzen() {
  local k="$1" v="$2" f="$DATEN/.env"
  touch "$f"; chmod 600 "$f"
  grep -v "^${k}=" "$f" > "$f.tmp" || true
  printf '%s=%s\n' "$k" "$v" >> "$f.tmp"
  chmod 600 "$f.tmp"; mv "$f.tmp" "$f"
}
env_hat() { grep -q "^$1=." "$DATEN/.env" 2>/dev/null; }

lade_pin() {
  [[ -s "$LOKAL/HERMES_VERSION.txt" ]] || stop_mit "Noch nicht eingerichtet. Zuerst: bash lokal/ki-lokal.sh einrichten"
  HERMES_PIN="$(cat "$LOKAL/HERMES_VERSION.txt")"; export HERMES_PIN
}

python_wahl() {
  if [[ -n "${KI_LOKAL_PYTHON:-}" ]]; then PY="$KI_LOKAL_PYTHON"; return; fi
  if [[ ! -x "$LOKAL/venv/bin/python" ]]; then
    say "Kleine Hilfsumgebung für Python anlegen (nur PyYAML, ca. 1 MB, nur in $LOKAL/venv)"
    command -v python3 >/dev/null 2>&1 || stop_mit "python3 fehlt. Bitte Claude Code Bescheid geben."
    python3 -m venv "$LOKAL/venv"
    "$LOKAL/venv/bin/python" -m pip install -q pyyaml
  fi
  PY="$LOKAL/venv/bin/python"
}

warte_dashboard() {
  for _ in $(seq 1 "${KI_LOKAL_WARTEN:-30}"); do
    curl -fs -o /dev/null http://127.0.0.1:9119/ && return 0
    sleep 4
  done
  return 1
}

cmd_agenten() {
  pruefe_docker; lade_pin
  docker ps --format '{{.Names}}' | grep -qx hermes || stop_mit "Hermes läuft nicht. Zuerst: bash lokal/ki-lokal.sh start"
  python_wahl
  say "Team einspielen (13 Agenten + Prüfprofile) – erst Probelauf, dann echt"
  export HERMES_DATEN="$DATEN" HERMES_BEFEHL="docker exec -i hermes hermes"
  "$PY" "$REPO/deploy/agenten_einspielen.py" --trocken > "$LOKAL/einspielen-probelauf.txt"
  ok "Probelauf ok (Protokoll: $LOKAL/einspielen-probelauf.txt)"
  "$PY" "$REPO/deploy/agenten_einspielen.py" --ausfuehren
  ok "Team eingespielt"
}

cmd_einrichten() {
  say "1/6 Voraussetzungen"
  pruefe_docker; ok "Docker läuft"; pruefe_arbeitsspeicher
  # shellcheck disable=SC1091
  . "$REPO/server/setup.env"
  mkdir -p "$DATEN/projekte/_papierkorb"; chmod 700 "$LOKAL"
  ok "Ordner für Testdaten: $LOKAL (liegt außerhalb des Repos)"

  say "2/6 Hermes laden und Version festhalten (Download, einige GB – dauert)"
  if [[ -s "$LOKAL/HERMES_VERSION.txt" ]]; then
    ok "Version schon festgehalten"
  else
    docker pull "$HERMES_IMAGE"
    docker image inspect "$HERMES_IMAGE" --format '{{index .RepoDigests 0}}' > "$LOKAL/HERMES_VERSION.txt"
    ok "Version festgehalten: $(cat "$LOKAL/HERMES_VERSION.txt")"
  fi
  lade_pin

  say "3/6 Schlüssel und Login"
  if ! env_hat ANTHROPIC_API_KEY; then
    local k=""
    read -rsp "Anthropic-Schlüssel einfügen (beginnt mit sk-ant-, Eingabe bleibt unsichtbar), dann Enter: " k; echo
    if [[ "$k" == sk-ant-* ]]; then env_setzen ANTHROPIC_API_KEY "$k"; ok "Schlüssel abgelegt (nur für dich lesbar)"
    else stop_mit "Das sieht nicht wie ein Anthropic-Schlüssel aus. Nichts verändert."; fi
    k=""
  else ok "Schlüssel ist schon da"; fi
  if ! env_hat HERMES_DASHBOARD_BASIC_AUTH_PASSWORD; then
    local pw; pw="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-20)"
    env_setzen HERMES_DASHBOARD_BASIC_AUTH_USERNAME lukas
    env_setzen HERMES_DASHBOARD_BASIC_AUTH_PASSWORD "$pw"
    env_setzen HERMES_DASHBOARD_BASIC_AUTH_SECRET "$(openssl rand -base64 32)"
    ( umask 077; printf 'Benutzer: lukas\nPasswort: %s\n' "$pw" > "$LOKAL/dashboard-login.txt" )
    printf '\n🔑 DASHBOARD-LOGIN   Benutzer: lukas   Passwort: %s\n   (steht auch in %s)\n' "$pw" "$LOKAL/dashboard-login.txt"
  else ok "Dashboard-Login ist schon da (siehe $LOKAL/dashboard-login.txt)"; fi

  say "4/6 Grundregeln setzen"
  hc() { "${DC[@]}" run --rm -T -e HERMES_DASHBOARD=0 hermes "$@" >/dev/null; }
  "${DC[@]}" stop hermes >/dev/null 2>&1 || true
  hc config set model.provider anthropic
  hc config set model.default "$CHIEF_MODEL"
  hc config set approvals.mode manual
  hc config set approvals.cron_mode deny
  hc config set approvals.unattended_mode deny
  hc config set approvals.single_query_mode deny
  hc config set auth.adopt_external_logins false
  ok "Modell $CHIEF_MODEL, Freigabe-Modus 'manuell'"
  if [[ -f "$DATEN/SOUL.md" ]]; then cp "$DATEN/SOUL.md" "$DATEN/SOUL.bak-$(date +%F-%H%M)"; fi
  cat "$REPO/agents/manager/SOUL.md" "$REPO/agents/_gemeinsam.md" > "$DATEN/SOUL.md"
  ok "Manager-Persönlichkeit eingespielt"

  say "5/6 Starten"
  "${DC[@]}" up -d
  if warte_dashboard; then ok "Dashboard antwortet: http://127.0.0.1:9119"
  else warn "Dashboard antwortet nicht. Letzte Meldungen:"; docker logs --tail 30 hermes 2>&1 | sed 's/^/     /' || true; fi

  say "6/6 Team einspielen"
  cmd_agenten

  cat <<MSG

🎉 Fertig. Öffne im Browser:  http://127.0.0.1:9119   (Login siehe oben)
   Test-Checkliste: ../17_ANLEITUNG_Lokal_Testen.md
   Wenn du fertig bist:  bash lokal/ki-lokal.sh stopp   (gibt den Arbeitsspeicher frei)
MSG
}

cmd_start() {
  pruefe_docker; lade_pin; "${DC[@]}" up -d
  if warte_dashboard; then ok "Läuft: http://127.0.0.1:9119"; else warn "Dashboard antwortet (noch) nicht – 'status' ansehen"; fi
}
cmd_stopp()  { pruefe_docker; lade_pin; "${DC[@]}" stop; ok "Angehalten. Daten bleiben erhalten."; }
cmd_status() {
  pruefe_docker; lade_pin
  "${DC[@]}" ps
  if curl -fs -o /dev/null http://127.0.0.1:9119/; then ok "Dashboard erreichbar"; else warn "Dashboard nicht erreichbar"; fi
  docker stats --no-stream --format 'Speicher: {{.MemUsage}}' hermes 2>/dev/null || true
}

cmd_pruefen() {
  pruefe_docker; lade_pin; python_wahl
  env_hat ANTHROPIC_API_KEY || stop_mit "Kein Anthropic-Schlüssel hinterlegt."
  ANTHROPIC_API_KEY="$(grep '^ANTHROPIC_API_KEY=' "$DATEN/.env" | cut -d= -f2-)"; export ANTHROPIC_API_KEY
  local args=() a
  if [[ $# -eq 0 ]]; then args=(--agent manager); else for a in "$@"; do args+=(--agent "$a"); done; fi
  "$PY" "$REPO/evals/pruefen.py" "${args[@]}" --max-usd "${KI_LOKAL_MAX_USD:-3}"
}

cmd_zuruecksetzen() {
  pruefe_docker; lade_pin
  printf 'Alle lokalen Testdaten (Gespräche, Karten, Profile) werden nach %s/_papierkorb verschoben.\nDer Schlüssel geht mit. Zum Bestätigen JA tippen: ' "$LOKAL"
  local a=""; read -r a
  [[ "$a" == "JA" ]] || stop_mit "Abgebrochen, nichts verändert."
  "${DC[@]}" down >/dev/null 2>&1 || true
  mkdir -p "$LOKAL/_papierkorb"
  mv "$DATEN" "$LOKAL/_papierkorb/hermes-data-$(date +%F-%H%M%S)"
  ok "Verschoben. Neu anfangen mit: bash lokal/ki-lokal.sh einrichten"
}

case "${1:-}" in
  einrichten) cmd_einrichten ;;
  start) cmd_start ;;
  stopp) cmd_stopp ;;
  status) cmd_status ;;
  agenten) cmd_agenten ;;
  pruefen) shift; cmd_pruefen "$@" ;;
  zuruecksetzen) cmd_zuruecksetzen ;;
  *) sed -n 2,10p "${BASH_SOURCE[0]}"; exit 1 ;;
esac
