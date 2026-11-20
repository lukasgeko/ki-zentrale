#!/usr/bin/env bash
# shellcheck disable=SC1090
# =====================================================================
#  KI-ZENTRALE – Nächtliches, verschlüsseltes Backup (restic → Backblaze B2)
#  Aufruf (auf dem Server):  sudo bash setup-backup.sh
#  Fragt nach: B2-Key-ID, B2-Application-Key, Bucket-Name.
#  Erzeugt ein Backup-Passwort → MUSS in deinen Passwortmanager!
#  Ohne dieses Passwort ist das Backup wertlos (Verschlüsselung).
# =====================================================================
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen."; exit 1; }
SERVER_USER="${SUDO_USER:-lukas}"
USER_HOME="$(getent passwd "$SERVER_USER" | cut -d: -f6)"
HDIR="$USER_HOME/ki-zentrale"
CONF=/etc/ki-backup.env

if [[ ! -f "$CONF" ]]; then
  read -rp "B2 keyID: " B2_ID
  read -rsp "B2 applicationKey (unsichtbar): " B2_KEY; echo
  read -rp "B2 Bucket-Name: " B2_BUCKET
  PW="$(openssl rand -base64 30 | tr -d '/+=' | cut -c1-32)"
  umask 077
  cat > "$CONF.neu" <<EOF
B2_ACCOUNT_ID=$B2_ID
B2_ACCOUNT_KEY=$B2_KEY
RESTIC_REPOSITORY=b2:$B2_BUCKET:ki-zentrale
RESTIC_PASSWORD=$PW
EOF
  # Zugangsdaten erst prüfen, dann dauerhaft speichern (bei Tippfehler: einfach neu starten)
  set -a; . "$CONF.neu"; set +a
  if ! restic snapshots >/dev/null 2>&1 && ! restic init; then
    rm -f "$CONF.neu"
    echo "❌ Verbindung zu Backblaze fehlgeschlagen. Bitte keyID, applicationKey und Bucket-Namen prüfen und das Skript erneut starten."
    exit 1
  fi
  mv "$CONF.neu" "$CONF"
  echo
  echo "🔑 BACKUP-PASSWORT (jetzt in den Passwortmanager kopieren!):"
  echo "    $PW"
  echo
  read -rp "Gespeichert? Dann Enter drücken… " _
fi
set -a; . "$CONF"; set +a

cat > /usr/local/bin/ki-backup <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
set -a; . $CONF; set +a
# Datenbanken konsistent sichern: Agenten kurz anhalten (ca. 1 Minute, nachts)
# Nur wieder starten, was vorher lief (ein "notaus" bleibt also bestehen)
cd "$HDIR"
WAR_AKTIV="\$(docker compose ps -q --status running hermes)"
docker compose stop -t 30
trap '[[ -n "\$WAR_AKTIV" ]] && cd "$HDIR" && docker compose up -d' EXIT
restic backup "$HDIR" --tag nightly --exclude "$HDIR/hermes-data/cache"
# Aufbewahrung: 7 Tage, 4 Wochen, 6 Monate. "forget" entfernt nur ALTE Sicherungsstände
# nach dieser festen Regel – deine Dateien werden nie gelöscht.
restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
restic check --read-data-subset=5%
EOF
chmod 700 /usr/local/bin/ki-backup

cat > /etc/systemd/system/ki-backup.service <<'EOF'
[Unit]
Description=KI-Zentrale nächtliches Backup
After=network-online.target docker.service
Wants=network-online.target
[Service]
Type=oneshot
Environment=HOME=/root
ExecStart=/usr/local/bin/ki-backup
EOF
cat > /etc/systemd/system/ki-backup.timer <<'EOF'
[Unit]
Description=KI-Zentrale Backup jede Nacht 03:30
[Timer]
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=15m
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now ki-backup.timer

echo "▶ Erstes Backup läuft jetzt…"
/usr/local/bin/ki-backup
echo
echo "▶ Wiederherstellungstest (in einen Testordner, nichts wird überschrieben)…"
TEST=/tmp/restore-test-$$
restic restore latest --target "$TEST" --include "$HDIR/docker-compose.yml"
if cmp -s "$HDIR/docker-compose.yml" "$TEST$HDIR/docker-compose.yml"; then
  echo "✅ Wiederherstellung funktioniert."
else
  echo "❌ Wiederherstellungstest fehlgeschlagen – bitte Claude Bescheid geben."
fi
echo "   (Testordner $TEST kann bleiben; er wird beim nächsten Neustart automatisch geleert.)"
echo "✅ Backup eingerichtet: jede Nacht 03:30, verschlüsselt, 6 Monate Historie."
