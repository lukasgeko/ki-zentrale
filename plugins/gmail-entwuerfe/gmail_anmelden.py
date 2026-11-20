#!/usr/bin/env python3
"""Einmalige Gmail-Anmeldung (auf dem MAC ausführen, nicht auf dem Server).

Ablauf: Browser öffnet sich → Google-Konto wählen → Zugriff erlauben → fertig.
Ergebnis: Datei gmail-token.json, die danach sicher auf den Server kopiert wird
(Anleitung Phase 2). Nur Python-Standardbibliothek, PKCE, Loopback-Adresse.

Aufruf:  python3 gmail_anmelden.py <pfad/zu/client_secret.json>
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/gmail.modify"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"


def main():
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(1)
    cfg = json.load(open(sys.argv[1]))
    cfg = cfg.get("installed") or cfg.get("web") or cfg
    cid, csec = cfg["client_id"], cfg["client_secret"]
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    ergebnis = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ergebnis.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write("<h2>Fertig. Du kannst dieses Fenster schließen.</h2>".encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}"
    t = threading.Thread(target=srv.handle_request, daemon=True); t.start()
    url = AUTH + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Browser öffnet sich. Falls nicht, diesen Link öffnen:\n", url)
    webbrowser.open(url)
    t.join(timeout=300)
    if ergebnis.get("state") != state or "code" not in ergebnis:
        print("❌ Anmeldung abgebrochen oder fehlgeschlagen."); sys.exit(1)
    body = urllib.parse.urlencode({"code": ergebnis["code"], "client_id": cid, "client_secret": csec,
                                   "redirect_uri": redirect, "grant_type": "authorization_code",
                                   "code_verifier": verifier}).encode()
    try:
        j = json.load(urllib.request.urlopen(urllib.request.Request(TOKEN, data=body), timeout=30))
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"❌ Google hat die Anmeldung abgelehnt ({e}). Bitte erneut versuchen."); sys.exit(1)
    if "refresh_token" not in j:
        print("❌ Google hat keinen Dauer-Schlüssel geliefert. Bitte erneut versuchen."); sys.exit(1)
    if SCOPE not in j.get("scope", ""):
        print("❌ Falsche Berechtigung erteilt."); sys.exit(1)
    ziel = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "gmail-token.json")
    fd = os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"client_id": cid, "client_secret": csec, "refresh_token": j["refresh_token"]}, f)
    os.chmod(ziel, 0o600)
    print(f"✅ Gespeichert: {ziel}  (geheim! nicht teilen, nicht ins Repo)")


if __name__ == "__main__":
    main()
