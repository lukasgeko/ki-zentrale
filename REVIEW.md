# REVIEW.md – Prüfauftrag für die "kalte" Prüfsitzung

Du prüfst Arbeit, die du **nicht** geschrieben hast. Sei skeptisch. Kein Lob, nur Befunde.
Modell: **Opus** bei Sicherheit, Geld, Recht oder Server-Änderungen; sonst Sonnet.

## Eingaben
- Die geänderten Dateien (Diff oder Pfade)
- Die Anforderung (PRD-Abschnitt) und die Regeln in `CLAUDE.md`

## Prüfliste
1. **Erfüllt es die Anforderung?** Jedes Erfolgskriterium der PRD einzeln abhaken.
2. **Sicherheit**
   - Kann irgendein Weg E-Mails senden, weiterleiten oder löschen? (Muss: nein)
   - Kann irgendein Weg Geld ausgeben oder Dateien endgültig löschen? (Muss: nein)
   - Werden Geheimnisse geloggt, ins Repo geschrieben oder an ein Modell geschickt?
   - Werden Inhalte aus E-Mails, Webseiten oder Dokumenten als **Daten** behandelt (nicht als Befehle)?
   - Öffnet etwas einen Port außerhalb von 127.0.0.1 / Tailscale?
   - Können 🔴-Daten an ein Cloud-Modell oder ins Web gelangen?
3. **Richtigkeit:** Logikfehler, Grenzfälle (leere Eingaben, Sonderzeichen, Umlaute, sehr große Dateien, fehlende Felder, Netzwerkfehler), falsche Annahmen über Hermes (gegen die offizielle Doku prüfen).
4. **Rechnungen:** Mindestens ein Beispiel von Hand nachrechnen. Quellen und "Stand"-Datum für Steuersätze und Gesetze vorhanden?
5. **Tests:** Decken sie die Kernanforderung und die Sicherheitsregeln ab? Laufen sie wirklich (`python -m pytest -q`)?
6. **Anfängertauglichkeit:** Sind Meldungen für Lukas verständlich (Deutsch, ohne Jargon)? Was passiert bei Fehlern?
7. **Umkehrbarkeit:** Lässt sich alles rückgängig machen? Gibt es ein Backup vor riskanten Schritten?

## Ausgabeformat
| Schwere | Datei:Zeile | Befund | Konkretes Fehlerszenario | Korrektur |
|---|---|---|---|---|
Schwere: **BLOCKER** (darf so nicht live) · **HOCH** · **MITTEL** · **NIEDRIG**.
Danach: kurze Liste, was du geprüft hast und was in Ordnung ist.
