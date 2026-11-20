# CLAUDE.md – Arbeitsregeln für Claude Code im Repo "ki-zentrale"

## Wer ist der Auftraggeber
Lukas: Projektleiter und Product Owner, **absoluter Anfänger in Technik**. Er gibt Ziel und Freigabe, du bist Ingenieur und Ausführender.
- Sprache mit Lukas: **Deutsch**, einfach, ohne Fachjargon. Code, Kommentare und Commit-Nachrichten: Deutsch oder Englisch, aber einheitlich pro Datei.
- Kein Code zum Selbst-Einbauen hinschieben. Du lieferst fertige, getestete Ergebnisse.
- Keine Floskeln. Ergebnis zuerst, dann die Begründung.

## Was das Repo ist
Infrastruktur-als-Code für Lukas' private KI-Plattform: **Hermes Agent** im Docker-Container auf einem Server, nur über **Tailscale** erreichbar.
```
server/    Server-Einrichtung (setup-server.sh, lockdown.sh, setup-backup.sh)
agents/    ein Ordner pro Hermes-Profil: SOUL.md (Persönlichkeit) + profile.yaml (Modell, Werkzeuge)
plugins/   eigene Hermes-Plugins (gmail-entwuerfe, immo-rechner, datenschutz-weiche)
evals/     Prüfungsfragen pro Agent + Prüflauf (pruefen.py)
deploy/    Skripte, die Agenten/Plugins auf den Server bringen
tests/     automatische Tests (pytest)
```
Planungsunterlagen (PRDs, Entscheidungen): `../00_BRAIN.md` bis `../14_BUILD_PLAN.md`. **Vor jeder Sitzung `../00_BRAIN.md` lesen.**

## Unverrückbare Regeln
1. **PRD vor Code:** Neue Bausteine nur mit freigegebener PRD (Problem, Erfolgskriterien, Umfang, Abhängigkeiten, Ablauf, offene Fragen). Sonst: PRD schreiben und auf "Proceed" warten.
2. **Destruktive oder riskante Aktionen** (Löschen, Überschreiben, Server ändern, Pakete installieren, Geld, E-Mails): exakten Plan zeigen (welche Dateien, was ist nicht umkehrbar), anhalten, auf das Wort **"Proceed"** warten.
3. **Nie** eine Sende-Funktion für E-Mails bauen oder aktivieren. Der Gmail-Zugang kann nur Entwürfe anlegen. Ein Test (`tests/test_gmail_kein_senden.py`) bewacht das.
4. **Geheimnisse nie ins Repo:** API-Schlüssel, Passwörter und Tokens liegen nur auf dem Server (`~/ki-zentrale/hermes-data/.env`, Rechte 600) und in Lukas' Passwortmanager. `.gitignore` nicht aufweichen.
5. **Privates bleibt lokal:** 🔴-Daten (Kreditangebote, Einkommen, IBAN, Steuer-ID, Verträge) nur an das Profil `privat` (Ollama). Die Datenschutz-Weiche nie abschalten, ohne dass Lukas zustimmt.
6. **Nichts löschen:** Statt löschen nach `_papierkorb/` verschieben.
7. Widersprich, wenn eine Anweisung technisch, sicherheitlich oder rechtlich nicht aufgeht, und schlage eine bessere Lösung vor. Widersprüche zu früheren Entscheidungen (`00_BRAIN.md`) sofort benennen.

## Modellwahl (siehe ../14_BUILD_PLAN.md)
- Planen/Architektur: Opus. Bauen: `/model opusplan` oder Sonnet. Kleinkram: Haiku.
- Nach 2 gescheiterten Sonnet-Versuchen am selben Fehler: auf Opus eskalieren.
- Limit schonen: gezielt suchen statt ganze Dateien lesen; `/usage` im Blick behalten.

## Arbeitsablauf pro Arbeitspaket
1. `00_BRAIN.md` + passende PRD lesen.
2. Bauen, mit Tests. `python -m pytest -q` muss grün sein.
3. Prüfung anstoßen: neue Sitzung oder Sub-Agent mit **REVIEW.md**, die den Bau nicht kennt.
4. Befunde beheben, Tests grün.
5. Lukas in 3–5 Sätzen berichten: Was ist fertig, was wurde geprüft, was ist offen.
6. Commit (eine Sache pro Commit, aussagekräftige Nachricht), Eintrag im Statuslog von `00_BRAIN.md`.

## Server-Zugriff
- Nur über Tailscale: `ssh lukas@ki-zentrale`. Hermes-Befehle: `docker exec -it hermes hermes …` bzw. `hermes -p <profil> …`.
- Hilfsbefehle auf dem Server: `ki-status`, `notaus`, `ki-start`.
- Hermes-Version ist gepinnt (`~/ki-zentrale/HERMES_VERSION.txt`). Updates nur bewusst: Änderungshinweise lesen, Backup prüfen, dann mit Proceed.

## Fakten, die leicht falsch angenommen werden
- Hermes kann das Claude-**Pro**-Abo **nicht** nutzen → Betrieb läuft über `ANTHROPIC_API_KEY` (Prepaid, Auto-Reload aus).
- Das Hermes-Dashboard lauscht nur auf 127.0.0.1 und ist über `tailscale serve` (HTTPS) im privaten Netz erreichbar. Niemals auf 0.0.0.0 binden.
- Gmail-Berechtigungen von Google erlauben technisch auch Senden. Die Sicherheit kommt allein aus unserem Code ohne Sende-Funktion.
