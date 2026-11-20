#!/usr/bin/env bash
# =====================================================================
#  KI-ZENTRALE – Server-Grundeinrichtung (Phase 1)
#  Ziel: Ubuntu 24.04 LTS, frisch installiert, als root ausführen.
#  Aufruf:  bash setup-server.sh
#  Das Skript kann gefahrlos mehrfach laufen (idempotent).
#
#  Was es tut:
#   1. System aktualisieren + automatische Sicherheitsupdates
#   2. Eigenen Benutzer anlegen (nicht als root arbeiten)
#   3. Tailscale (privates Netz) + Tailscale-SSH
#   4. Firewall: alles zu, nur Tailscale (+ SSH bis zum Lockdown)
#   5. Docker installieren
#   6. Hermes Agent im Container (Sandbox) + Dashboard nur intern
#   7. Dashboard per HTTPS im privaten Netz erreichbar machen
#   8. Notaus-Befehl "notaus" + Status-Befehl "ki-status"
#  Aufruf aus dem Repo-Ordner: bash /root/ki-zentrale/server/setup-server.sh
#  Was es NICHT tut: nichts löschen, nichts kaufen, keine E-Mails,
#  keine öffentlichen Ports außer SSH (wird in lockdown.sh geschlossen).
# =====================================================================
set -Eeuo pipefail

LOG=/var/log/ki-zentrale-setup.log
exec > >(tee -a "$LOG") 2>&1
trap 'echo; echo "❌ FEHLER in Zeile $LINENO. Das Skript hat angehalten. Bitte die letzten 30 Zeilen aus $LOG an Claude schicken. Danach kann es gefahrlos erneut gestartet werden."' ERR

say()  { echo; echo "▶ $*"; }
ok()   { echo "  ✅ $*"; }
warn() { echo "  ⚠️  $*"; }

# ---------- 0. Voraussetzungen ----------
say "0/8 Voraussetzungen prüfen"
[[ $EUID -eq 0 ]] || { echo "Bitte als root ausführen."; exit 1; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$SCRIPT_DIR/setup.env" ]] || { echo "setup.env fehlt neben dem Skript."; exit 1; }
# shellcheck source=/dev/null
source "$SCRIPT_DIR/setup.env"
. /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || warn "Getestet für Ubuntu 24.04 – gefunden: ${PRETTY_NAME:-?}. Fahre fort."
# Schlüssel abfragen (unsichtbare Eingabe, werden nirgends auf deinem Mac gespeichert)
TS_AUTHKEY=""; ANTHROPIC_API_KEY=""
if ! tailscale status >/dev/null 2>&1; then
  read -rsp "Tailscale-Schlüssel einfügen (beginnt mit tskey-auth-, Eingabe bleibt unsichtbar), dann Enter: " TS_AUTHKEY; echo
  [[ "$TS_AUTHKEY" == tskey-auth-* ]] || { echo "Das sieht nicht wie ein Tailscale-Schlüssel aus. Abbruch, nichts verändert."; exit 1; }
fi
if [[ ! -f "$(getent passwd "$SERVER_USER" | cut -d: -f6 2>/dev/null)/ki-zentrale/hermes-data/.env" ]]; then
  read -rsp "Anthropic-Schlüssel einfügen (beginnt mit sk-ant-, unsichtbar; leer lassen = später), dann Enter: " ANTHROPIC_API_KEY; echo
  if [[ -n "$ANTHROPIC_API_KEY" && "$ANTHROPIC_API_KEY" != sk-ant-* ]]; then
    echo "Das sieht nicht wie ein Anthropic-Schlüssel aus. Abbruch, nichts verändert."; exit 1
  fi
fi
[[ "$SERVER_USER" =~ ^[a-z][a-z0-9_-]{1,30}$ ]] || { echo "SERVER_USER ungültig."; exit 1; }
ok "Voraussetzungen erfüllt"

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
LOCKDOWN_DATEI=/etc/ssh/sshd_config.d/00-ki-zentrale.conf

# ---------- 1. System ----------
say "1/8 System aktualisieren (dauert ein paar Minuten)"
apt-get update -q
apt-get -y -q -o Dpkg::Options::=--force-confold upgrade
apt-get -y -q install ca-certificates curl gnupg ufw unattended-upgrades restic jq git htop
timedatectl set-timezone "$TIMEZONE" || true
hostnamectl set-hostname "$SERVER_HOSTNAME" || true
grep -q "^127.0.1.1 $SERVER_HOSTNAME\$" /etc/hosts || { sed -i '/^127.0.1.1/d' /etc/hosts; echo "127.0.1.1 $SERVER_HOSTNAME" >> /etc/hosts; }
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
# Sicherheits-Updates des Kernels brauchen einen Neustart: nachts um 04:30, nur wenn nötig.
# Alle Dienste starten danach von selbst wieder.
cat >/etc/apt/apt.conf.d/52ki-zentrale-reboot <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
EOF
# Swap (Reserve-Arbeitsspeicher), falls keiner vorhanden
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
ok "System aktuell, automatische Sicherheitsupdates aktiv"

# ---------- 2. Benutzer ----------
say "2/8 Benutzer '$SERVER_USER' anlegen"
if ! id "$SERVER_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$SERVER_USER"
fi
usermod -aG sudo "$SERVER_USER"
# sudo ohne Passwort nur, weil Login ausschließlich über Tailscale-SSH läuft
echo "$SERVER_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$SERVER_USER"
chmod 440 "/etc/sudoers.d/90-$SERVER_USER"
visudo -cf "/etc/sudoers.d/90-$SERVER_USER" >/dev/null
USER_HOME="$(getent passwd "$SERVER_USER" | cut -d: -f6)"
ok "Benutzer bereit ($USER_HOME)"

# ---------- 3. Tailscale ----------
say "3/8 Tailscale (privates Netz) einrichten"
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled
if ! tailscale status >/dev/null 2>&1; then
  tailscale up --authkey="$TS_AUTHKEY" --ssh --hostname="$SERVER_HOSTNAME"
else
  tailscale set --ssh --hostname="$SERVER_HOSTNAME"
fi
TS_IP="$(tailscale ip -4 | head -1)"
TS_DNS="$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')"
unset TS_AUTHKEY
ok "Tailscale aktiv: $TS_IP  ($TS_DNS)"

# ---------- 4. Firewall ----------
say "4/8 Firewall: alles zu außer privatem Netz"
# Kein "ufw reset": ein erneuter Lauf darf den Lockdown nicht rückgängig machen
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0 comment 'privates Netz'
ufw allow 41641/udp comment 'Tailscale Direktverbindung'
if [[ -f "$LOCKDOWN_DATEI" ]]; then
  ok "Lockdown bereits aktiv – öffentlicher SSH-Zugang bleibt geschlossen"
else
  ufw allow 22/tcp comment 'SSH – wird in lockdown.sh geschlossen'
fi
ufw --force enable
ok "Firewall aktiv"

# ---------- 5. Docker ----------
say "5/8 Docker installieren"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get -y -q install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
usermod -aG docker "$SERVER_USER"
# Docker darf keine Ports an der Firewall vorbei öffnen: wir nutzen nur network_mode host + 127.0.0.1
ok "Docker $(docker --version | awk '{print $3}' | tr -d ,)"

# ---------- 6. Hermes Agent ----------
say "6/8 Hermes Agent im Container einrichten"
HDIR="$USER_HOME/ki-zentrale"
install -d -o "$SERVER_USER" -g "$SERVER_USER" "$HDIR" "$HDIR/hermes-data" "$HDIR/hermes-data/projekte" "$HDIR/hermes-data/projekte/_papierkorb"
# Version festhalten: beim ersten Lauf die aktuelle "stable"-Version holen und ihre exakte Kennung (Digest)
# notieren. Danach wird immer genau diese Version genutzt – Updates nur bewusst (siehe CLAUDE.md).
if [[ -s "$HDIR/HERMES_VERSION.txt" ]]; then
  HERMES_PIN="$(cat "$HDIR/HERMES_VERSION.txt")"
  ok "Hermes-Version ist festgehalten: $HERMES_PIN"
else
  docker pull "$HERMES_IMAGE"
  HERMES_PIN="$(docker image inspect "$HERMES_IMAGE" --format '{{index .RepoDigests 0}}')"
  echo "$HERMES_PIN" > "$HDIR/HERMES_VERSION.txt"; chown "$SERVER_USER:$SERVER_USER" "$HDIR/HERMES_VERSION.txt"
  ok "Hermes-Version festgehalten: $HERMES_PIN"
fi
HUID="$(id -u "$SERVER_USER")"; HGID="$(id -g "$SERVER_USER")"
cat > "$HDIR/docker-compose.yml" <<EOF
# KI-Zentrale – Hermes Agent (Sandbox-Container)
# Dashboard lauscht NUR auf 127.0.0.1 → von außen unsichtbar.
# Zugriff ausschließlich über Tailscale (tailscale serve).
services:
  hermes:
    image: ${HERMES_PIN}
    container_name: hermes
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./hermes-data:/opt/data
    environment:
      - HERMES_UID=${HUID}
      - HERMES_GID=${HGID}
      - HERMES_DASHBOARD=1
      - HERMES_DASHBOARD_HOST=127.0.0.1
      - HERMES_DASHBOARD_PORT=9119
      - HERMES_DASHBOARD_PUBLIC_URL=https://${TS_DNS}
      - TZ=${TIMEZONE}
    mem_limit: 5g
    command: ["gateway", "run"]
    logging:
      driver: json-file
      options: { max-size: "20m", max-file: "5" }
EOF
chown "$SERVER_USER:$SERVER_USER" "$HDIR/docker-compose.yml"
cd "$HDIR"
docker compose pull -q
# Bei erneutem Lauf: laufende Agenten kurz anhalten, damit nie zwei Instanzen auf dieselben Daten zugreifen
docker compose stop hermes >/dev/null 2>&1 || true

# --- Ersteinrichtung: Anthropic-Schlüssel sicher ablegen, Grundregeln setzen ---
HENV="$HDIR/hermes-data/.env"
if [[ "${ANTHROPIC_API_KEY:-}" == sk-ant-* ]]; then
  touch "$HENV"; chmod 600 "$HENV"; chown "$SERVER_USER:$SERVER_USER" "$HENV"
  grep -q '^ANTHROPIC_API_KEY=' "$HENV" && sed -i '/^ANTHROPIC_API_KEY=/d' "$HENV"
  echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" >> "$HENV"
  unset ANTHROPIC_API_KEY
  ok "Anthropic-Schlüssel sicher abgelegt (nur für Hermes lesbar)"
elif ! grep -q '^ANTHROPIC_API_KEY=sk-ant-' "$HENV" 2>/dev/null; then
  warn "Kein Anthropic-Schlüssel eingegeben – kann später im Dashboard unter 'API Keys' eingetragen werden."
fi
# Dashboard-Login (Hermes verlangt ihn, sobald es über eine Netzwerk-Adresse erreichbar ist).
# Zweite Schutzschicht zusätzlich zu Tailscale.
touch "$HENV"; chmod 600 "$HENV"; chown "$SERVER_USER:$SERVER_USER" "$HENV"
if ! grep -q '^HERMES_DASHBOARD_BASIC_AUTH_USERNAME=' "$HENV"; then
  DASH_PW="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-20)"
  { echo "HERMES_DASHBOARD_BASIC_AUTH_USERNAME=$SERVER_USER"
    echo "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=$DASH_PW"
    echo "HERMES_DASHBOARD_BASIC_AUTH_SECRET=$(openssl rand -base64 32)"; } >> "$HENV"
  # Direkt aufs Terminal, damit das Passwort NICHT im Protokoll landet
  printf '\n🔑 DASHBOARD-LOGIN   Benutzer: %s   Passwort: %s\n   → JETZT in den Passwortmanager kopieren!\n' "$SERVER_USER" "$DASH_PW" > /dev/tty
  read -rp "Gespeichert? Dann Enter drücken… " _ < /dev/tty
  unset DASH_PW
  ok "Dashboard-Login angelegt"
fi

hc() { docker compose run --rm -T -e HERMES_DASHBOARD=0 hermes "$@" >/dev/null; }
hc config set model.provider anthropic
hc config set model.default "$CHIEF_MODEL"
hc config set approvals.mode manual          # JEDER riskante Befehl braucht deine Freigabe
hc config set approvals.cron_mode deny       # Zeitgesteuerte Jobs dürfen nie riskant handeln
hc config set approvals.unattended_mode deny
hc config set approvals.single_query_mode deny
hc config set auth.adopt_external_logins false
ok "Grundregeln gesetzt: Modell $CHIEF_MODEL, Freigabe-Modus 'manuell'"

# Persönlichkeit des Managers (SOUL.md) einspielen – vorherige Fassung wird mit Zeitstempel gesichert
MANAGER_SOUL="$SCRIPT_DIR/../agents/manager/SOUL.md"; GEMEINSAM="$SCRIPT_DIR/../agents/_gemeinsam.md"
if [[ -f "$MANAGER_SOUL" && -f "$GEMEINSAM" ]]; then
  [[ -f "$HDIR/hermes-data/SOUL.md" ]] && cp "$HDIR/hermes-data/SOUL.md" "$HDIR/hermes-data/SOUL.bak-$(date +%F-%H%M)"
  cat "$MANAGER_SOUL" "$GEMEINSAM" > "$HDIR/hermes-data/SOUL.md"
  chown "$SERVER_USER:$SERVER_USER" "$HDIR/hermes-data/SOUL.md"; chmod 644 "$HDIR/hermes-data/SOUL.md"
  ok "Manager-Persönlichkeit (SOUL.md) eingespielt"
else
  warn "agents/manager/SOUL.md nicht gefunden – Hermes nutzt vorerst seine Standard-Persönlichkeit."
fi

docker compose up -d
ok "Hermes gestartet"

# ---------- 7. Dashboard im privaten Netz ----------
say "7/8 Dashboard per HTTPS im privaten Netz freigeben"
for _ in $(seq 1 30); do
  curl -fs -o /dev/null http://127.0.0.1:9119/ && break
  sleep 4
done
DASH_OK=0
if curl -fs -o /dev/null http://127.0.0.1:9119/; then
  AUTH="$(curl -fs http://127.0.0.1:9119/api/status 2>/dev/null | jq -c '[.auth_required, .auth_providers]' 2>/dev/null || echo '?')"
  echo "  ℹ️  Dashboard-Schutz: $AUTH (erwartet: [true,[\"basic\"]])"
  if timeout 20 tailscale serve --bg --https=443 http://127.0.0.1:9119 >/dev/null 2>&1; then
    ok "Dashboard: https://$TS_DNS  (nur aus deinem privaten Netz, mit Login)"
    DASH_OK=1
  else
    warn "HTTPS im Tailscale-Admin ist noch nicht aktiv (Anleitung 1.4). Danach auf dem Server: sudo tailscale serve --bg --https=443 http://127.0.0.1:9119"
  fi
else
  warn "Das Dashboard antwortet nicht. Bitte Claude Bescheid geben (Anleitung: Hilfe 'Dashboard nicht erreichbar')."
  docker logs --tail 30 hermes 2>&1 | sed 's/^/     /' || true
fi

# ---------- 8. Hilfsbefehle ----------
say "8/8 Hilfsbefehle installieren"
cat > /usr/local/bin/notaus <<EOF
#!/usr/bin/env bash
# NOTAUS: stoppt sofort alle Agenten. Nichts wird gelöscht.
cd "$HDIR" && sudo docker compose stop && echo "🛑 Alle Agenten gestoppt. Wieder starten mit: ki-start"
EOF
cat > /usr/local/bin/ki-start <<EOF
#!/usr/bin/env bash
cd "$HDIR" && sudo docker compose up -d && echo "▶ Agenten laufen wieder."
EOF
cat > /usr/local/bin/ki-status <<'EOF'
#!/usr/bin/env bash
echo "== Agenten ==";      sudo docker ps --format '{{.Names}}: {{.Status}}'
echo "== Privates Netz =="; tailscale status --self=true --peers=false 2>/dev/null | head -1
echo "== Firewall ==";     sudo ufw status | head -8
echo "== Speicher ==";     df -h / | tail -1; free -h | sed -n 2p
echo "== Backup =="
if systemctl list-unit-files ki-backup.timer >/dev/null 2>&1 && systemctl is-enabled ki-backup.timer >/dev/null 2>&1; then
  systemctl show ki-backup.service -p Result -p ExecMainExitTimestamp | sed 's/^Result=success/Ergebnis: ✅ erfolgreich/; s/^Result=/Ergebnis: ❌ /; s/^ExecMainExitTimestamp=/Zuletzt: /'
  systemctl list-timers ki-backup.timer --no-pager | sed -n 2p
else
  echo "noch nicht eingerichtet"
fi
EOF
chmod 755 /usr/local/bin/notaus /usr/local/bin/ki-start /usr/local/bin/ki-status
ok "Befehle: ki-status · notaus · ki-start"

echo
echo "=================================================================="
if [[ $DASH_OK -eq 1 ]]; then echo " ✅ GRUNDEINRICHTUNG FERTIG"; else echo " ⚠️  GRUNDEINRICHTUNG FERTIG – aber das Dashboard ist noch nicht erreichbar (siehe Warnung oben)"; fi
echo "    Server im privaten Netz:  $TS_DNS  ($TS_IP)"
echo "    Nächster Schritt: Anleitung Teil 2 (Test über Tailscale, dann lockdown.sh)"
echo "    Protokoll: $LOG"
echo "=================================================================="
