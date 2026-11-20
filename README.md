# KI-Zentrale

Lukas' private KI-Plattform: ein Team aus KI-Agenten auf einem eigenen Server, erreichbar nur über ein privates Netz (Tailscale), vom Handy und vom Laptop.

## Was hier drin ist
| Ordner | Inhalt | Stand |
|---|---|---|
| `server/` | Server-Einrichtung, Lockdown, nächtliches Backup | ✅ unabhängig geprüft (16 Befunde eingearbeitet), noch nicht auf echtem Server gelaufen |
| `agents/` | 10 Agenten: Persönlichkeit (`SOUL.md`) + Rechte (`profile.yaml`); `_gemeinsam.md` = Regeln für alle | ✅ Entwurf fertig, Fachcheck durch Lukas offen |
| `plugins/gmail-entwuerfe/` | Gmail-Zugang **ohne** Senden/Löschen (nur suchen, lesen, labeln, archivieren, Entwürfe) | ✅ getestet mit Attrappe |
| `plugins/datenschutz-weiche/` | 🟢🟡🔴-Ampel: hält private Daten von Cloud-KI und Web fern | ✅ getestet |
| `plugins/immo-rechner/` | Kaufnebenkosten, Annuität, Rendite, Verkauf, Sensitivität, AfA | ✅ getestet (von Hand nachgerechnet) |
| `evals/` | 121 Prüfungsfragen + automatischer Prüflauf (`pruefen.py`) | ✅ Trockenlauf getestet |
| `deploy/` | Spielt Agenten + Plugins in Hermes ein (pro Profil, Prüf-Zwillinge mit Test-Postfach) | ⚠️ in Testordner erprobt; erster echter Lauf mit Claude Code |
| `lokal/` | **Testvariante für den Mac** (Docker, nur 127.0.0.1, 8-GB-Speicherlimit): `bash lokal/ki-lokal.sh einrichten` | ✅ mit Docker-Attrappe getestet, erster echter Start auf dem Mac offen |
| `tests/` | 206 automatische Tests: `python3 -m pytest -q` | ✅ alle grün |

Zwei unabhängige Sicherheitsprüfungen (Opus, ohne Vorwissen) wurden durchgeführt; alle BLOCKER- und HOCH-Befunde sind behoben und mit Tests abgesichert.

## Das Team
| Agent | Aufgabe | KI-Modell |
|---|---|---|
| manager | Einziger Ansprechpartner, plant, verteilt, koordiniert | Claude Sonnet 5.5 |
| posteingang | Gmail sortieren/suchen/Entwürfe | Claude Haiku 5.5 |
| alltag | Erinnerungen, Einkaufsliste | Claude Haiku 5.5 |
| recherche | Web-Recherche mit Quellen | Claude Sonnet 5.5 |
| immo-projekt | Projektsteuerung | Claude Sonnet 5.5 |
| immo-markt | Grundstück, Planungsrecht, Markt | Claude Sonnet 5.5 |
| immo-bewertung | Wirtschaftlichkeit (Beispielzahlen) | Claude Sonnet 5.5 |
| immo-recht | Recht & Steuern (Recherche, keine Beratung) | Claude Sonnet 5.5 |
| immo-dokumente | Exposé, Bankmappe, Briefe (Entwürfe) | Claude Sonnet 5.5 |
| privat | 🔴 echte private Zahlen, kein Internet | lokal (Ollama, z. B. Qwen3 14B) |

## Sicherheitsprinzipien
1. Kein Agent kann E-Mails senden, Geld ausgeben oder endgültig löschen. Das ist technisch ausgeschlossen, nicht nur verboten.
2. Riskante Befehle brauchen Lukas' Freigabe (`approvals.mode: manual`).
3. Private Daten (🔴) bleiben auf Lukas' eigenem Rechner.
4. Der Server ist aus dem Internet unsichtbar (nur Tailscale).
5. Jeder Agent hat nur die Werkzeuge, die er braucht.

Regeln für Claude Code: `CLAUDE.md` · Prüfauftrag: `REVIEW.md` · Planung: `../00_BRAIN.md` ff.
