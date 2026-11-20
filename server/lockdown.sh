#!/usr/bin/env bash
# =====================================================================
#  KI-ZENTRALE – Lockdown: Server für das Internet unsichtbar machen
#  ERST ausführen, wenn du dich über Tailscale verbunden hast:
#     ssh lukas@ki-zentrale      (vom Mac, mit Tailscale an)
#  Aufruf:  sudo bash lockdown.sh
#  Notfall-Zugang danach: Contabo-Kundenpanel → "VNC-Konsole".
# =====================================================================
set -Eeuo pipefail
trap 'echo; echo "❌ FEHLER in Zeile $LINENO. Bitte Claude Bescheid geben. Notfall-Zugang: Contabo-Kundenpanel → VNC-Konsole."' ERR
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen."; exit 1; }

echo "▶ Sicherheitsprüfung: Bist du gerade über Tailscale verbunden?"
# sudo entfernt SSH_CONNECTION aus der Umgebung → in den Elternprozessen nachsehen
find_ssh_conn() {
  local pid=$$
  for _ in 1 2 3 4 5 6; do
    if [[ -r /proc/$pid/environ ]]; then
      local v; v="$(tr '\0' '\n' < /proc/$pid/environ | sed -n 's/^SSH_CONNECTION=//p' | head -1)"
      [[ -n "$v" ]] && { echo "$v"; return; }
    fi
    pid="$(ps -o ppid= -p "$pid" | tr -d ' ')"; [[ -z "$pid" || "$pid" == 1 ]] && break
  done
}
tailscale status >/dev/null 2>&1 || { echo "❌ Tailscale läuft nicht. Abbruch."; exit 1; }
CLIENT_IP="$(find_ssh_conn | awk '{print $1}')"
if [[ -z "$CLIENT_IP" ]]; then
  echo "⚠️  Konnte die Verbindungsart nicht automatisch erkennen."
  read -rp "Bist du mit 'ssh lukas@ki-zentrale' (über Tailscale) verbunden? Dann JA tippen: " ans
  [[ "$ans" == "JA" ]] || { echo "Abbruch, nichts verändert."; exit 1; }
  CLIENT_IP="(bestätigt)"
elif [[ ! "$CLIENT_IP" =~ ^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\. ]] && [[ "$CLIENT_IP" != fd7a:115c:a1e0:* ]]; then
  echo "❌ Du bist über das öffentliche Internet verbunden ($CLIENT_IP), nicht über Tailscale."
  echo "   Abbruch, damit du dich nicht aussperrst. Verbinde dich mit: ssh lukas@ki-zentrale"
  exit 1
fi
echo "  ✅ Verbunden über Tailscale ($CLIENT_IP)"

echo "▶ Öffentlichen SSH-Zugang schließen"
ufw delete allow 22/tcp >/dev/null 2>&1 || true
if ufw status | grep -qE '^22/tcp'; then echo "❌ Port 22 ist noch offen – bitte Claude Bescheid geben."; exit 1; fi
mkdir -p /etc/ssh/sshd_config.d
# "00-" damit diese Datei VOR Anbieter-Dateien wie 50-cloud-init.conf gelesen wird (der erste Wert gewinnt)
cat > /etc/ssh/sshd_config.d/00-ki-zentrale.conf <<'EOF'
# Nur noch Tailscale-SSH; klassischer SSH-Dienst ohne Passwort/Root-Login
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
mkdir -p /run/sshd
sshd -t && systemctl try-reload-or-restart ssh.service
ufw status verbose | head -15
echo
echo "✅ LOCKDOWN FERTIG. Der Server hat keine offenen öffentlichen Zugänge mehr"
echo "   (außer dem Tailscale-Verbindungsport, der ohne gültiges Gerät nutzlos ist)."
echo "   Jetzt: 'ki-status' eingeben – unter Firewall darf KEINE Zeile mit 22/tcp stehen."
echo "   Danach Test von außen: Anleitung Schritt 2.5"
