#!/bin/bash
# KI-Zentrale lokal auf dem Mac testen (PRD 16). Läuft mit der alten Mac-Bash 3.2.
# Aufruf: bash lokal/ki-lokal.sh <befehl>
#   einrichten      einmalig: Hermes laden, Login anlegen, Team einspielen, starten
#   start | stopp   Agenten starten / anhalten (stopp gibt den Arbeitsspeicher frei)
#   status          läuft es? Speicherverbrauch?
#   agenten         Team neu einspielen (nach Änderungen im Repo)
#   pruefen [name…] Prüffragen stellen (kostet API-Guthaben, Standard: nur "manager", max 3 $)
#   zuruecksetzen   Testdaten nach _papierkorb verschieben (nichts wird gelöscht)
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOKAL="${KI_LOKAL_DIR:-$HOME/ki-lokal}"
DATEN="$LOKAL/hermes-data"
export KI_LOKAL_DIR="$LOKAL"
HERMES_UID="$(id -u)"; HERMES_GID="$(id -g)"; export HERMES_UID HERMES_GID
SCHRITT="Start"
trap 'printf "\n❌ Abgebrochen im Schritt: %s\n   Nichts wurde gelöscht. Nach dem Beheben einfach nochmal starten (bereits Erledigtes wird übersprungen).\n   Bitte die Meldung oben kopieren und an Claude Code geben (ohne Schlüssel/Passwort).\n" "$SCHRITT" >&2' ERR
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
    if [[ "$gb" -le 8 ]]; then
      warn "Bei 8 GB: andere große Programme (Browser mit vielen Tabs, Spiele) vorher schließen. In Docker Desktop → Einstellungen → Resources → Memory auf 4 GB stellen."
    fi
  fi
}

# Schlüssel/Werte in .env setzen, ohne sie irgendwo auszugeben
env_setzen() {
  local k="$1" v="$2" f="$DATEN/.env"
  ( umask 077
    touch "$f"
    grep -v "^${k}=" "$f" > "$f.tmp" || true
    printf '%s=%s\n' "$k" "$v" >> "$f.tmp"
    chmod 600 "$f.tmp"; mv "$f.tmp" "$f" )
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
    xcode-select -p >/dev/null 2>&1 || stop_mit "Auf diesem Mac fehlen die Apple-Entwicklerwerkzeuge (gebraucht für Python, ca. 1–2 GB, kostenlos). Bitte im Terminal 'xcode-select --install' eingeben, die Installation abwarten und danach diesen Befehl nochmal starten."
    command -v python3 >/dev/null 2>&1 || stop_mit "python3 fehlt. Bitte Claude Code Bescheid geben."
    python3 -m venv "$LOKAL/venv"
    "$LOKAL/venv/bin/python" -m pip install -q pyyaml
  fi
  PY="$LOKAL/venv/bin/python"
}

warte_dashboard() {
  for _ in $(seq 1 "${KI_LOKAL_WARTEN:-30}"); do
    if curl -fs -o /dev/null http://127.0.0.1:9119/; then return 0; fi
    sleep 4
  done
  return 1
}
login_aktiv() {
  curl -fs http://127.0.0.1:9119/api/status 2>/dev/null | grep -Eq '"auth_required"[[:space:]]*:[[:space:]]*true'
}
pruefe_containername() {
  local p
  if docker ps -a --format '{{.Names}}' | grep -qx hermes; then
    p="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' hermes 2>/dev/null || true)"
    [[ "$p" == "ki-lokal" ]] || stop_mit "Auf diesem Mac gibt es schon einen anderen Container namens 'hermes'. Bitte in Docker Desktop (Reiter Containers) anschauen und mir Bescheid geben, bevor er angefasst wird."
  fi
}

pruefe_weiche_aktiv() {
  # Pflicht-Check: ist die Datenschutz-Weiche im Manager-Profil wirklich eingeschaltet? Sonst STOPP.
  [[ "${KI_LOKAL_PLUGINCHECK:-an}" == "aus" ]] && return 0
  if docker exec -i hermes hermes plugins list 2>/dev/null | grep -i "datenschutz-weiche" | grep -qi "enabled"; then
    ok "Datenschutz-Weiche ist im Manager-Profil aktiv"
  else
    stop_mit "Die Datenschutz-Weiche ist im Manager-Profil NICHT als 'enabled' zu sehen. Bitte so nicht weitertesten (Testfall 4 wäre sonst wertlos). Mit 'docker exec -i hermes hermes plugins list' ansehen und mir die Ausgabe geben."
  fi
}

cmd_agenten() {
  SCHRITT="Team einspielen"
  pruefe_docker; lade_pin
  docker ps --format '{{.Names}}' | grep -qx hermes || stop_mit "Hermes läuft nicht. Zuerst: bash lokal/ki-lokal.sh start"
  python_wahl
  say "Team einspielen (13 Agenten + Prüfprofile) – erst Probelauf, dann echt"
  export HERMES_DATEN="$DATEN" HERMES_BEFEHL="docker exec -i hermes hermes"
  "$PY" "$REPO/deploy/agenten_einspielen.py" --trocken > "$LOKAL/einspielen-probelauf.txt" 2>&1 \
    || { tail -n 20 "$LOKAL/einspielen-probelauf.txt" | sed 's/^/     /'; stop_mit "Der Probelauf meldet Fehler (Protokoll: $LOKAL/einspielen-probelauf.txt). Nichts wurde verändert."; }
  ok "Probelauf ok"
  "$PY" "$REPO/deploy/agenten_einspielen.py" --ausfuehren > "$LOKAL/einspielen.log" 2>&1 \
    || { tail -n 25 "$LOKAL/einspielen.log" | sed 's/^/     /'; stop_mit "Beim Einspielen sind Fehler aufgetreten (Protokoll: $LOKAL/einspielen.log)."; }
  ok "Team eingespielt (Protokoll: $LOKAL/einspielen.log)"
  "${DC[@]}" restart hermes >/dev/null
  warte_dashboard || stop_mit "Hermes antwortet nach dem Neustart nicht. Mit 'bash lokal/ki-lokal.sh status' ansehen."
  pruefe_weiche_aktiv
}

cmd_einrichten() {
  SCHRITT="1/6 Voraussetzungen"
  say "1/6 Voraussetzungen"
  pruefe_docker; ok "Docker läuft"; pruefe_arbeitsspeicher
  # shellcheck disable=SC1091
  . "$REPO/server/setup.env"
  ( umask 077; mkdir -p "$DATEN/projekte/_papierkorb" ); chmod 700 "$LOKAL"
  tmutil addexclusion "$LOKAL" >/dev/null 2>&1 || true   # Schlüssel nicht in Time-Machine-Backups
  ok "Ordner für Testdaten: $LOKAL (liegt außerhalb des Repos, nicht in Time Machine)"

  SCHRITT="2/6 Hermes laden"
  say "2/6 Hermes laden und Version festhalten (Download, einige GB – dauert)"
  if [[ -s "$LOKAL/HERMES_VERSION.txt" ]]; then
    ok "Version schon festgehalten"
  else
    docker pull "$HERMES_IMAGE"
    docker image inspect "$HERMES_IMAGE" --format '{{index .RepoDigests 0}}' > "$LOKAL/HERMES_VERSION.txt"
    ok "Version festgehalten: $(cat "$LOKAL/HERMES_VERSION.txt")"
  fi
  lade_pin

  SCHRITT="3/6 Schlüssel und Login"
  say "3/6 Schlüssel und Login"
  if ! env_hat ANTHROPIC_API_KEY; then
    local k=""
    read -rsp "Anthropic-Schlüssel einfügen (beginnt mit sk-ant-, Eingabe bleibt unsichtbar), dann Enter: " k; echo
    if [[ "$k" == sk-ant-* ]]; then env_setzen ANTHROPIC_API_KEY "$k"; ok "Schlüssel abgelegt (nur für dich lesbar)"
    else stop_mit "Das sieht nicht wie ein Anthropic-Schlüssel aus. Nichts verändert."; fi
    k=""
  else ok "Schlüssel ist schon da"; fi
  if [[ -s "$LOKAL/dashboard-login.txt" ]] && env_hat HERMES_DASHBOARD_BASIC_AUTH_PASSWORD; then
    ok "Dashboard-Login ist schon da (siehe $LOKAL/dashboard-login.txt)"
  else
    local pw; pw="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-20)"
    ( umask 077; printf 'Benutzer: lukas\nPasswort: %s\n' "$pw" > "$LOKAL/dashboard-login.txt" )
    env_setzen HERMES_DASHBOARD_BASIC_AUTH_USERNAME lukas
    env_setzen HERMES_DASHBOARD_BASIC_AUTH_PASSWORD "$pw"
    env_setzen HERMES_DASHBOARD_BASIC_AUTH_SECRET "$(openssl rand -base64 32)"
    ok "Dashboard-Login angelegt (am Ende wird es nochmal angezeigt)"
  fi

  SCHRITT="4/6 Persönlichkeit des Managers"
  say "4/6 Manager-Persönlichkeit"
  pruefe_containername
  if [[ -f "$DATEN/SOUL.md" ]]; then cp "$DATEN/SOUL.md" "$DATEN/SOUL.bak-$(date +%F-%H%M%S)"; fi
  cat "$REPO/agents/manager/SOUL.md" "$REPO/agents/_gemeinsam.md" > "$DATEN/SOUL.md"
  ok "Manager-Persönlichkeit eingespielt"

  SCHRITT="5/6 Starten und Grundregeln"
  say "5/6 Starten und Grundregeln setzen"
  "${DC[@]}" up -d
  warte_dashboard || { docker logs --tail 30 hermes 2>&1 | sed 's/^/     /' || true; stop_mit "NICHT fertig: Das Dashboard antwortet nicht. Meldungen siehe oben. Meist hilft: Docker Desktop prüfen (genug Speicher?) und den Befehl nochmal starten."; }
  login_aktiv || stop_mit "NICHT fertig: Das Dashboard verlangt kein Login. Aus Sicherheitsgründen bitte nicht benutzen: 'bash lokal/ki-lokal.sh stopp' und mir Bescheid geben."
  ok "Dashboard antwortet und verlangt ein Login"
  local kv
  for kv in "model.provider anthropic" "model.default $CHIEF_MODEL" "approvals.mode manual" "approvals.cron_mode deny" \
            "approvals.unattended_mode deny" "approvals.single_query_mode deny" "auth.adopt_external_logins false"; do
    # shellcheck disable=SC2086
    docker exec -i hermes hermes config set $kv >/dev/null
  done
  ok "Modell $CHIEF_MODEL, Freigabe-Modus 'manuell'"

  SCHRITT="6/6 Team einspielen"
  say "6/6 Team einspielen"
  cmd_agenten

  cat <<MSG

🎉 Fertig. Öffne im Browser:  http://127.0.0.1:9119
$(cat "$LOKAL/dashboard-login.txt")
   (Login steht auch in $LOKAL/dashboard-login.txt)
   Test-Checkliste: 17_ANLEITUNG_Lokal_Testen.md, Teil C
   Wenn du fertig bist:  bash lokal/ki-lokal.sh stopp   (gibt den Arbeitsspeicher frei)
MSG
}

cmd_start() {
  SCHRITT="Starten"
  pruefe_docker; lade_pin; pruefe_containername; "${DC[@]}" up -d
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
  echo "Hinweis: 'max ${KI_LOKAL_MAX_USD:-3} \$' ist eine SCHÄTZUNG (0,08 \$ pro Frage). Die echte Bremse ist das Ausgabenlimit in der Anthropic-Konsole."
  "$PY" "$REPO/evals/pruefen.py" "${args[@]}" --max-usd "${KI_LOKAL_MAX_USD:-3}"
  echo "Offene Karten auf dem Prüf-Board (arbeiten im Hintergrund weiter und kosten Guthaben):"
  docker exec -i hermes hermes kanban --board pruefung list 2>/dev/null | head -20 || true
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
