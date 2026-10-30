# Häufig gestellte Fragen

Kurze Antworten auf die am häufigsten gestellten Fragen. Wenn deine Frage hier nicht dabei ist, klicke auf den **Feedback**-Link in der Fußzeile und frag uns auf Discord.

## Wie mache ich die Änderungen von Smart Citizen rückgängig?

Ganz einfach, und jederzeit. Smart Citizen bearbeitet niemals die ursprünglichen Dateien des Spiels direkt, daher ist die Rückkehr zum Original nur einen Klick entfernt:

- **Symbolleiste → Mehr → Lokalisierung leeren** löscht die von Smart Citizen geschriebene benutzerdefinierte `global.ini`. Das Spiel greift sofort wieder auf seinen integrierten Text zurück. Deine Bearbeitungen gehen dabei nicht verloren, sie bleiben in der App gespeichert und du kannst sie jederzeit erneut anwenden.
- Möchtest du lieber nur eine Version zurückgehen statt alles? **Symbolleiste → Mehr → Sicherung wiederherstellen** setzt die Spieldatei auf eine Sicherung mit Zeitstempel zurück (Smart Citizen bewahrt die letzten 5 auf und erstellt bei jedem Anwenden eine neue).

Deine persönlichen Bearbeitungen liegen in `user.ini` in deinem Smart-Citizen-Datenordner, getrennt vom Spiel, sodass das Leeren der Spieldatei sie niemals berührt.

## Werde ich für die Nutzung von Smart Citizen gebannt?

Smart Citizen bearbeitet nur Lokalisierungstext (die Worte, die dir das Spiel zeigt), es greift nicht in die Spiellogik ein, verschafft dir keinen Vorteil und kommuniziert nicht mit CIGs Servern. Unsere Änderungen **sollten** unbedenklich sein.

Das optionale **Smart Citizen Overlay** (Overlay-Tab) funktioniert genauso, ohne ins Spiel einzugreifen. Es zeichnet gewöhnliche Fenster über das Spiel, liest Pixel von deinem Bildschirm, wie es ein Screenshot-Werkzeug tut, und liest die Datei `Game.log` des Spiels. Es injiziert nie etwas ins Spiel und hakt sich nie darin ein, öffnet nie den Spielprozess, liest nie dessen Speicher und sendet nie Tastatur- oder Mauseingaben. Legst du ein Tastenkürzel für die Schublade fest, meldet es genau diese eine Tastenkombination bei Windows an, auf dem üblichen Weg, auf dem ein Programm ein Tastenkürzel anfordert. Star Citizen hält angemeldete Tastenkürzel anderer Programme zurück, solange es den Fokus hat, deshalb empfängt das Overlay, solange ein Tastenkürzel gesetzt ist, auch die Roheingabe der Tastatur (Raw Input), den lesenden Weg, auf dem Windows ein Programm im Hintergrund über Tastendrücke informiert. Das ist kein Tastatur-Hook: Es hält keine Taste auf, ändert oder sendet keine, zeichnet nichts auf und reagiert nur auf deine Kombination. CIG hat sich zu Overlays dieser Art bisher nicht geäußert, daher gilt auch hier der Hinweis zur Nutzung auf eigenes Risiko weiter unten.

CIG hat Community-Lokalisierung öffentlich unterstützt. Ihr Beitrag [Community Localization Update](https://robertsspaceindustries.com/spectrum/community/SC/forum/1/thread/star-citizen-community-localization-update) legt die offizielle Unterstützung für von Spielern erstellte Übersetzungen dar, die unserem Verständnis nach ausdrücklich die Art von Lokalisierungsbearbeitung erlaubt, die Smart Citizen vornimmt.

Bekannte Streamer betreiben ähnliche Lokalisierungsprojekte offen und öffentlich, und keinem von ihnen wurde gesagt, damit aufzuhören.

Trotzdem: die Art und Weise, wie du Smart Citizen nutzt, geschieht auf eigenes Risiko. Unsere Änderungen sollten unbedenklich sein, aber für alles, was du selbst tust, haftest du und deine Mitspieler für eventuell entstehende Schäden. Wenn du dir bei einer Änderung unsicher bist, halte sie kosmetisch und bewahre eine Sicherung auf.

## Welche Dateien verändert Smart Citizen?

Nur eine, und nur wenn du auf **Erweiterungen anwenden** klickst:

- `StarCitizen\<Kanal>\data\Localization\<Sprache>\global.ini` — die Lokalisierungsdatei des Spiels für den Kanal (LIVE, PTU usw.) und die Sprache, die du ausgewählt hast. Smart Citizen sichert zuerst die vorhandene Datei und schreibt dann das zusammengeführte Ergebnis.
- Es stellt außerdem sicher, dass `g_language` in deiner `user.cfg` festgelegt ist, damit das Spiel die richtige Lokalisierung lädt. Nichts anderes in deiner Spielinstallation wird berührt.

Alles, was Smart Citizen für den eigenen Gebrauch erzeugt (der Quellen-Cache, Erweiterungsdateien, Sicherungen, deine `user.ini`), liegt in deinem Smart-Citizen-Datenordner, nicht im Spiel.

## Warum sagt Windows, diese App sei unbekannt?

Weil Smart Citizen noch nicht code-signiert ist. Windows SmartScreen und Smart App Control markieren jede neue App eines Herausgebers, für den sie kein hinterlegtes Signaturzertifikat haben, selbst eine völlig sichere. Es ist eine „das haben wir noch nie gesehen“-Warnung, keine „das ist gefährlich“-Warnung.

So führst du sie aus: klicke bei der SmartScreen-Meldung auf **Weitere Informationen → Trotzdem ausführen**. Wenn Smart App Control sie komplett blockiert, kannst du die App über deren Eingabeaufforderung zulassen oder Smart App Control vorübergehend deaktivieren, installieren und wieder aktivieren.

Code-Signierung steht auf unserer Roadmap, wodurch diese Warnung verschwinden wird. Bis dahin lade Smart Citizen nur von unseren offiziellen GitHub-Releases herunter, damit du sicher sein kannst, den echten Build zu haben.
