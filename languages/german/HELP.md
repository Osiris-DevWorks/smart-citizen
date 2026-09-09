# Smart Citizen — Schnellstartanleitung

## Erste Einrichtung

Beim Start lädt Smart Citizen alle Anpassungen aus deiner vorherigen Sitzung neu und prüft deine Star-Citizen-Installation — der Installer trägt diesen Pfad bereits vor, aber du kannst ihn im **Konfiguration**-Tab ändern. Alle Standard-Lokalisierungs- und DataForge-Daten stammen **direkt aus deiner installierten `Data.p4k`** (keine Downloads, keine Community-Spiegelserver), daher ist eine einmalige Extraktion nach der Installation oder nach jedem Spiel-Patch erforderlich.

## Einfacher & erweiterter Modus

Smart Citizen öffnet sich in einem von zwei Modi, und du kannst jederzeit wechseln.

- Der **einfache Modus** ist ein Zwei-Knopf-Bildschirm: ein Knopf, **Erweiterungen anwenden**, führt die gesamte Kette mit deinen aktuellen Einstellungen aus (extrahieren, erstellen, anwenden, wobei zuerst eine Sicherung deiner Spieldatei erstellt wird); der andere wechselt zum **erweiterten Modus**. Das ist der schnelle Weg, wenn du nur die Erweiterungen angewendet haben möchtest und keine Strings von Hand bearbeiten musst.
- Der **erweiterte Modus** ist die vollständige App: die String-Tabelle, Filter, der Erweiterungen-Tab, der Konfiguration-Tab und alles andere in dieser Anleitung.

Wähle deinen Standard bei der Installation, oder wechsle innerhalb der App zwischen ihnen. Der einfache Modus verwendet die Einstellungen, die du zuletzt im erweiterten Modus gespeichert hast.

## 1. Basis-Lokalisierung aus Data.p4k extrahieren

Öffne den **Konfiguration**-Tab und klicke auf **Aus Data.p4k extrahieren**. Dies entpackt die Standard-`global.ini` sowie die vom Erweiterungsgenerator verwendeten DataForge-Entitäts-XMLs — Schiffe, Komponenten, Waffen, Missionen, Baupläne usw.

Nach Abschluss der Extraktion wird die extrahierte `base.ini` automatisch in die Tabelle geladen — zusammengeführt mit allen Erweiterungsdateien und deinen gespeicherten `user.ini`-Überschreibungen.

## 2. Lokalisierungs-Strings bearbeiten

- Doppelklicke eine beliebige Zelle in **Benutzerdefinierter Wert**, um Text zu bearbeiten.
- **Standardwert** — Originaltext aus der von `Data.p4k` extrahierten `base.ini`.
- **Aktueller Wert** — der effektive Wert vor deiner Überschreibung (Basis + alle importierten INI-Schichten).
- **Benutzerdefinierter Wert** — deine persönliche Bearbeitung. Wird bei jeder Änderung automatisch gespeichert und in `<Datenordner>\<Kanal>\user.ini` persistiert (der Datenordner ist standardmäßig `Dokumente\Smart Citizen`, und jeder Star-Citizen-Kanal — LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW — hat seine eigenen isolierten Überschreibungen).
- Die Spalte **Status** kennzeichnet jede Zeile danach, woher ihr aktueller Wert stammt:
  - **Geändert** — du hast den benutzerdefinierten Wert explizit bearbeitet.
  - **Erweitert** — automatisch von der Erweiterungspipeline erzeugt (Statistik-Overlays, Bauplan-Tags usw.).
  - **Unverändert** — Standardtext aus `base.ini`.
  - **Neu** — der Schlüssel existiert nur in deinen Überschreibungen oder in der Erweiterungspipeline, nicht in der Standard-`base.ini`.
- **Ändere die Breite jeder Spalte**, indem du den Trenner zwischen zwei Spaltenköpfen ziehst, oder doppelklicke auf einen Trenner, damit sich die Spalte an ihren breitesten sichtbaren Inhalt anpasst. Deine Breiten bleiben über Neustarts hinweg erhalten. Solange du nichts selbst anpasst, passt Smart Citizen die Spalten automatisch an dein Fenster an, damit eine frische Installation immer sinnvoll auf ihrem eigenen Bildschirm öffnet. Um dieses automatische Layout zurückzubekommen, nutze **Fensterproportionen zurücksetzen** (siehe unten).

## 3. Vorschaubereich

Der **Vorschaubereich** oben rechts zeigt den gerenderten Text der aktuell ausgewählten Zeile. Die Loc-String-Tokens des Spiels werden in gestyltes HTML übersetzt, sodass du ungefähr siehst, wie dein String im Spiel aussehen wird:

- `\n` → Zeilenumbruch
- `<EM3>...</EM3>` → unterstrichene Abschnittsüberschrift
- `<EM4>...</EM4>` → fette blaue Inline-Hervorhebung (typischerweise Statistikwerte)
- `~mission(Name)` → grau dargestellter `[Name]`-Platzhalter (das Spiel setzt zur Laufzeit den tatsächlichen Wert ein)

Der Bereich bleibt über alle Tabs hinweg sichtbar und spiegelt die zuletzt im **String-Editor** ausgewählte Zeile — nützlich, um zu prüfen, wie eine lange Missionsbeschreibung oder ein Journaleintrag formatiert wird, bevor du sie anwendest.

## 4. Kategorien

Verwende den **Kategorie**-Filter, um dich auf einen Bereich zu konzentrieren:

- **Schiffe** — Schiffsnamen und -beschreibungen (`vehicle_Name*`, `vehicle_Desc*`, plus Wikelo/Collector-Mods).
- **Schiffsgegenstände** — Schilde, Kraftwerke, Kühler, Quantenantriebe, Sprungantriebe, Schiffswaffen, Raketen, Bomben, Geschütztürme.
- **Missionen** — Missionsbriefings, Vertragstext, Belohnungsbeschreibungen.
- **Ausrüstung** — FPS-Waffen, Rüstung, Helme, Anzüge, Optiken.
- **Rohstoffe** — Handelswaren und Herstellungsmaterialien.
- **Journal** — In-Game-Journal-/Galactapedia-artige Einträge.
- **Sonstiges** — Alles andere.

## 5. Suchen & Filtern

- Verwende das **Suchfeld**, um Strings nach Schlüssel oder Textinhalt zu finden.
- Kombiniere mit Filtern für **Kategorie** und **Status** (Geändert / Erweitert / Unverändert / Neu).
- Aktiviere **Unveränderte ausblenden**, um dich nur auf deine eigenen Bearbeitungen zu konzentrieren.
- Die **Spaltenfilterfelder** unter jeder Überschrift grenzen die Tabelle weiter ein.
- Klicke auf eine Spaltenüberschrift, um nach dieser Spalte zu sortieren. Klicke auf die Überschrift **★**, um Favoriten nach oben zu sortieren.

## 6. Schiffsfavoriten

- Klicke auf die Spalte **★** einer beliebigen Schiffszeile, um sie als Favorit zu markieren. Nur die Namenszeile eines Schiffs kann favorisiert werden; die Beschreibungszeile desselben Schiffs hat im Spiel kein entsprechendes Verhalten, daher bleiben dort die Spalten für Stern und Sortierreihenfolge leer.
- Favorisierte Schiffe erhalten ein konfigurierbares Präfix vor ihrem Namen, wodurch sie in der In-Game-Schiffsliste ganz oben einsortiert werden.
- Ändere das Präfix-Zeichen im **Erweiterungen**-Tab (Standard: `*`).
- Aktiviere **Nur Schiffs-/Fahrzeugnamen** in der Suchen-&-Filtern-Zeile, um die Tabelle auf Schiffs- und Fahrzeugnamenszeilen einzugrenzen und Schiffsbeschreibungen sowie alle anderen Kategorien auszublenden; in Kombination mit **Nur Favoriten** siehst du genau die Zeilen, die du favorisieren kannst.

## 7. Änderungen auf das Spiel anwenden

Klicke auf **Erweiterungen anwenden**, um deine Bearbeitungen in die Spielinstallation zu schreiben. Eine Sicherung der aktuellen `global.ini` mit Zeitstempel wird in `<Datenordner>\<Kanal>\backups\` erstellt, bevor irgendetwas überschrieben wird.

Die Farbe des Knopfs zeigt dir, wo du stehst: **Rot** bedeutet, dass sich seit deinem letzten Anwenden etwas geändert hat (eine Bearbeitung, eine Neuerstellung, ein Sprach- oder Kanalwechsel) und das Spiel es noch nicht hat; **Grün** bedeutet, dass das Spiel bereits mit dem geladenen Stand übereinstimmt, und der Knopf bleibt deaktiviert, da nichts zu wiederholen ist. Dieselbe Rot/Grün-Konvention gilt für **Erweiterungen erstellen** und **Tag-Änderungen speichern** im Erweiterungen-Tab. Wenn du die App schließt, während der Anwenden-Knopf noch rot ist, fragt Smart Citizen, ob jetzt angewendet werden soll oder ohne Anwenden beendet werden soll, damit nicht angewendete Arbeit nicht stillschweigend verloren geht.

Smart Citizen stempelt außerdem ein kleines Wasserzeichen in die Launcher-Versionszeichenfolge (`Frontend_PU_Version`) und hängt `\nLocalizations Enhanced with Smart Citizen v{VERSION}` in einer eigenen Zeile an. So kannst du im Spiel bestätigen, dass dein Loc-Pack aktiv ist — schau dir das Versionslabel im Star-Citizen-Hauptmenü an. Der Stempel wird bei jedem Anwenden neu geschrieben, sodass er sich über Versionen hinweg nicht anhäuft.

## 8. Eine Sicherung wiederherstellen

Öffne das Menü **Mehr** in der Symbolleiste und wähle **Sicherung wiederherstellen**, um zu einer früheren Version zurückzukehren. Smart Citizen bewahrt bis zu **5 automatische Sicherungen** auf — die älteste wird entfernt, sobald eine neue erstellt wird.

## 9. Lokalisierung leeren

Öffne das Menü **Mehr** und wähle **Lokalisierung leeren**, um die benutzerdefinierte `global.ini` aus dem Spielverzeichnis zu löschen und das Spiel auf seinen ursprünglichen (Original-) Text zurückzusetzen. Deine gespeicherten Überschreibungen in `<Datenordner>\<Kanal>\user.ini` bleiben unberührt und können jederzeit erneut angewendet werden.

## 10. INI importieren

Verwende **INI importieren** im **Konfiguration**-Tab (auch über das Menü **Mehr** in der Symbolleiste verfügbar), um eine vorhandene INI-Datei in deine Überschreibungen einzufügen. Ein Konfliktlösungsdialog lässt dich pro Schlüssel entscheiden, ob du den **aktuellen behalten**, den **importierten verwenden**, **anhängen**, **voranstellen** oder einen **benutzerdefinierten** Wert angeben möchtest.

## 11. Lokalisierungspaket exportieren

Öffne das Menü **Mehr** und wähle **INI exportieren…**, um die aktuell angewendete `global.ini` in ein einzelnes Zip zu verpacken — `SmartCitizen-LocPack-{channel}-{YYYYMMDD}.zip` —, das jeder andere in seinen Ordner `StarCitizen\<Kanal>\data\Localization\english\` legen kann, um dasselbe Loc-Pack ohne Installation von Smart Citizen zu nutzen. Nützlich, um Voreinstellungen mit Freunden oder deiner Organisation zu teilen.

## 12. user.ini zurücksetzen

Verwende **user.ini zurücksetzen** im **Konfiguration**-Tab, um alle deine persönlichen Bearbeitungen für den aktiven Kanal zu löschen. Eine Bestätigungsabfrage stellt sicher, dass es kein Fehlklick ist, und eine automatische Sicherung der aktuellen `user.ini` wird zuerst in `<Datenordner>\<Kanal>\backups\` angelegt — ein Zurücksetzen ist also wiederherstellbar, falls du es dir anders überlegst.

## 13. Einstellungen exportieren / importieren

Verwende **Einstellungen exportieren…** und **Einstellungen importieren…** im **Konfiguration**-Tab, um dein gesamtes Smart-Citizen-Setup zwischen PCs zu übertragen oder es vor einer Neuinstallation zu sichern. Der Export bündelt deine App-Einstellungen und die `user.ini`-Überschreibungen jedes Kanals in ein einziges kleines Zip, einschließlich deines Star-Citizen-Installationspfads; maschinenspezifische Pfade, die auf einem anderen PC keinen Sinn ergeben würden (dein Datenordner, der Cache-Speicherort, die Fenstergeometrie, die Spaltenbreiten des String-Editors), bleiben außen vor. Der Import legt diese Sicherung über deine aktuellen Einstellungen und ersetzt die `user.ini` für die enthaltenen Kanäle; deine aktuellen `user.ini`-Dateien werden zuvor über **user.ini wiederherstellen** als Momentaufnahme gesichert, sodass ein Import umkehrbar ist. Dein Star-Citizen-Pfad wird nur übernommen, wenn er auf dem Ziel-PC noch existiert; andernfalls erkennt Smart Citizen ihn stattdessen automatisch. Nach einem Import startet Smart Citizen neu, um die neuen Einstellungen zu laden, und bietet dann an, deine Erweiterungen neu zu erstellen und anzuwenden.

## 14. Nach Spiel-Updates

Wenn Star Citizen aktualisiert wird, bleiben deine Bearbeitungen in `<Datenordner>\<Kanal>\user.ini` erhalten. Führe **Aus Data.p4k extrahieren** erneut aus, um frische Standard-Strings aus dem gepatchten Spiel zu holen — die Tabelle lädt automatisch neu, und deine Anpassungen werden erneut darauf angewendet.

## 15. Sprachen wechseln

Wähle eine Sprache aus dem Dropdown-Menü **Sprache** im **Konfiguration**-Tab (neben Kanal). Der Wechsel ändert sowohl die Oberfläche der App als auch die Spieltexte in der Tabelle:

- **Englisch** (der Standard) verwendet die aus deiner eigenen `Data.p4k` extrahierten Standard-Strings.
- **Andere Sprachen** laden die von der Community übersetzte `global.ini` dieser Sprache herunter und legen sie über die englische Basis, sodass jeder String, den die Übersetzung nicht abdeckt, auf Englisch zurückfällt, statt zu fehlen. Der Download wird pro Sprache zwischengespeichert; ein späterer Wechsel zurück nutzt den Cache erneut.
- **Erweiterungen bleiben auf Englisch.** Statistikblöcke, Tags und Missionsdetails werden aus Spieldaten erzeugt und behalten ihre englische Form über dem übersetzten Text bei. Eine gemischte Zeile (etwa ein deutscher Rollenname innerhalb eines englischen Statistikblocks) ist erwartet, kein Fehler.
- **Sprachdatei zuordnen** (Konfiguration-Tab) lässt dich eine Sprache auf eine andere `global.ini`-URL verweisen, zum Beispiel deinen eigenen Fork einer Community-Übersetzung. Deine URL gewinnt gegenüber dem mitgelieferten Standard.
- Einige Oberflächentexte werden erst nach einem Neustart der App aktualisiert. Die Tabellen-Strings laden sofort neu.

Anwenden schreibt in den passenden Sprachordner deiner Spielinstallation und legt `g_language` in `user.cfg` fest, damit das Spiel die richtige Datei lädt.

Möchtest du beim Übersetzen helfen? Der Übersetzungsstatus pro Sprache wird in `languages/TRANSLATIONS.md` im Repository verfolgt, und wir liefern viel lieber deine Worte als die einer Maschine aus. Melde dich im Discord.

## 16. App-Updates

Smart Citizen prüft bei jedem Start auf eine neue Version. Wenn eine verfügbar ist, erscheinen die Release-Notizen in einem scrollbaren Fenster mit zwei Optionen:

- **Jetzt aktualisieren** lädt das neue Installationsprogramm herunter, Windows fragt um Erlaubnis, und Smart Citizen schließt sich, aktualisiert und öffnet sich in der neuen Version neu. Deine Bearbeitungen, Sicherungen und Einstellungen bleiben unberührt.
- **Später** belässt dich auf der aktuellen Version; du wirst beim nächsten Start erneut gefragt.

Du kannst auch jederzeit manuell mit **Nach Updates suchen** im Konfiguration-Tab prüfen. Portable Builds zeigen stattdessen einen Knopf **Release-Seite öffnen**, da es kein Installationsprogramm zum Ausführen gibt: lade das neue Zip herunter und entpacke es über den alten Ordner.

## Erweiterungen-Tab

- Statistik-Overlays umschalten, die numerische Werte an Beschreibungen anhängen — SCM-Geschwindigkeit, Schild-HP, DPS, Frachtkapazität, Bergbaulaser-Strahlwerte (Fracture / Extraction), Werte für Handsalvage-Werkzeuge, Bauplan-Pools, Missions-XP und mehr. Missions-XP nennt außerdem die Ruf-Spur, die sie speist (z. B. `750 XP (Fracht)`), Battaglias Scan-/Bergbauverträge tragen ein `[RS ####]`-Tag mit der Basis-Ressourcensignatur des Zielerzes, und das Bergbau-Kompendium-Journal listet die Basis-RS jedes Erzes neben seinen Abbauorten auf.
- **Medizinische Verbrauchsgüter** — fügt eine verständliche Wirkungszeile zu den Basis-CureLife-Pens (MedPen, OxyPen, AdrenaPen und Verwandte) hinzu, sodass die Beschreibung erzählt, was der Pen tatsächlich bewirkt, statt nur seine Hintergrundgeschichte.
- **Werte oberhalb der Beschreibung anzeigen** — kippt den Statistikblock so, dass er oben statt unten in einer Beschreibung sitzt, sodass die Zahlen das Erste sind, was du im Spiel liest.
- **Ressourcensignaturen (RS) neben Erznamen anzeigen**: hängt die Basis-Ressourcensignatur jedes abbaubaren Erzes an dessen eigenen Anzeigenamen an (z. B. „Aluminium (RS 4285)“), sodass sie überall erscheint, wo das Spiel diesen Namen anzeigt, einschließlich des Missions-Trackers. Unabhängig von der Zeile Ressourcensignaturen unter den Missionsdetail-Feldern weiter unten.
- Jede Erweiterungskategorie unabhängig aktivieren oder deaktivieren.
- Das Präfix-Zeichen für Schiffsfavoriten konfigurieren.
- **Bauplan-Besitz** wurde in einen eigenen Tab **Bauplan-Tracker** verschoben; siehe den nächsten Abschnitt.
- **Tag-Generator** — passe die eingeklammerten Tags an, die bei Komponenten-, Raketen-, Schiffswaffen- und Rohstoffnamen platziert werden. Elemente mit ▲/▼ neu anordnen, einzelne Elemente ausschalten, Abkürzungslänge ändern (`M` / `MIL` / `Military`), Trennzeichen (keines, Bindestrich, Leerzeichen usw.) und Klammern (eckig, rund, keine usw.) wählen, und festlegen, ob das Tag vor oder nach dem Namen erscheint. Komponenten haben außerdem ein optionales **Typ**-Element (Schild, Kühler, Kraftwerk usw.) — standardmäßig deaktiviert. Rohstoffe haben die Elemente **Bezeichnung**, **Verwendung** (zeigt, wofür die Herstellungsmaterialien eines Rohstoffs verwendet werden) und **Sammlung**, alle standardmäßig deaktiviert; aktiviere die gewünschten im Tag-Generator. Klicke auf **Tag-Änderungen speichern**, um zu speichern und neu zu erstellen. (**Erweiterungen erstellen** speichert ebenfalls zuerst alle ausstehenden Tag-Bearbeitungen, sodass eine ungespeicherte Änderung nicht bei einer Neuerstellung verloren gehen kann.)
- **Missionstitel** (Tag-Generator-Tab) — leite Frachtmissionstitel mit ihrer Route ein. Wähle Platzierung (Voranstellen, Anhängen oder Titel ersetzen), den Routenpfeil (`>`, `->`, `to`, oder die formkodierenden `->-`/`->=`/`=>-`/`=>=`, die Eins-zu-Viele-Endpunkte je Seite anzeigen), das Titeltrennzeichen und wie viel des Orts angezeigt wird (standardmäßig vollständige Adresse; der Kurzname kann bei seltenen Missionen nicht angezeigt werden), mit Live-Vorschau. Eine Frachtfahrt liest sich wie `Area18 > Lorville - <Originaltitel>`, sodass du den Auftrag auf einen Blick in der Vertragsliste erkennst, und Frachtfahrten mit mehreren Stopps listen ihre Ablieferungsorte auf (`Area18 > Lorville, New Babbage`). Zwei unabhängige Umschalter kürzen den Originaltitel: **Originaltitel kürzen** wendet ausgewählte Phrasenkürzungen an (z. B. „Opportunity for Independent Cargo Hauler“ → „Intro“, „Local Shipment Route“ → „Route“, plus Behandlung der Ling-Familie und Rangpräfixe), und **Frachtgrößen kürzen** kürzt Frachtgrößen ab („Extra Small“ → „XS“). Einzelne Kontrollkästchen bieten feinere Kontrolle — „Fracht“ oder „Haul“ ganz entfernen, „Rang“ weglassen oder „Direkt“-Fahrten zur Betonung unterstreichen — damit Route und Tags auch bei langen Titeln passen. Die Kontrollkästchen unter **Allgemeine Tags** auf derselben Seite blenden die Nur-Titel-Tags ein oder aus: die Ruf-Belohnung, das Bauplan-Tag, `[ACE]`, das Battaglia-`[RS ####]`-Tag und den Namen der Ruf-Spur. Das Bauplan-Tag lautet `[BP]`, wenn jede Version einer Mission einen Bauplan auszahlt, und `[BP?]`, wenn es keine sichere Sache ist (nur manche Versionen tragen einen, oder die Spieldaten kennzeichnen die Auszahlung als Zufallswurf).
- **Missionsbezeichnungen** — passe die in Missionserweiterungsblöcken verwendeten Abschnittsüberschriften an (MISSIONSDETAILS, MÖGLICHE BAUPLÄNE, GEGENSTANDSBELOHNUNGEN, BAUPLÄNE-DATEN), die auf Missionen ohne bestimmten Rufrang angezeigte XP-Bezeichnung (Standard „Ruf“) und das für Überschriften verwendete Hervorhebungs-Tag (EM3 = unterstrichen, EM4 = farbig).
- **Missionsdetail-Felder** — jede Zeile des MISSIONSDETAILS-Blocks einzeln ein- oder ausblenden (Missionstyp, Schwierigkeit, Feindkräfte, Ruf, Baupläne, Ass-Pilot und Ressourcensignaturen), sodass deine Missionsbeschreibungen nur die Daten enthalten, die dich interessieren. **Ressourcensignaturen** fügt Recco-Battaglia-Scan-/Bergbauverträgen eine Aufschlüsselung hinzu, die die vollständige RS-Wertprogression jedes Zielerzes auflistet, getrennt vom `[RS ####]`-Tag im Missionstitel und der Erznamen-Anmerkung weiter oben.
- Klicke auf **Erweiterungen erstellen**, um DataForge-Daten aus `Data.p4k` zu extrahieren und die Erweiterungs-INI-Dateien neu zu erstellen. Deklarative Patches unter `patches/` werden bei jeder Neuerstellung idempotent erneut angewendet, sodass bekannte CIG-Datenfehler behoben bleiben, ohne auf einen Spiel-Patch warten zu müssen.

## Bauplan-Tracker-Tab

Verfolge, welche Herstellungs-Baupläne du bereits besitzt, und sieh es im Spiel widergespiegelt: besessene Gegenstände erhalten ein blaues `[Owned]`-Tag in den MÖGLICHE-BAUPLÄNE-Listen von Missionen, sodass dir eine Vertragsauflistung auf einen Blick sagt, was du noch aufspüren musst.

- **Zwei Listen, ein Verschiebemechanismus.** Verfügbare Baupläne links, deine besessenen rechts. Wähle Gegenstände aus und verschiebe sie mit den Pfeilknöpfen. Die Besessen-Liste bleibt über Neustarts hinweg erhalten.
- **Dinge schnell finden.** Ein Suchfeld grenzt beide Listen ein, und die Filter **Mission / Typ / Klasse / Größe / Grad** grenzen die verfügbare Liste danach ein, wo ein Bauplan fällt und um welche Art von Gegenstand es sich handelt (Rüstung, Munition, FPS-Waffe, Schiffsgegenstand usw.).
- **Protokolle nach besessenen Bauplänen durchsuchen** füllt die Besessen-Liste automatisch: es liest deine Star-Citizen-Protokolldateien nach den Bauplänen, die du im Spiel erhalten hast, und markiert sie als besessen. Es werden nur Baupläne importiert, die seit deinem letzten Scan erhalten wurden, sodass ein erneutes Ausführen jederzeit günstig ist. Der Scan benötigt deinen im Konfiguration-Tab festgelegten Star-Citizen-Installationspfad.
- **Auch LIVE/HOTFIX scannen (den jeweils inaktiven)** prüft zusätzlich denjenigen der beiden Kanäle, der nicht dein aktueller ist, da beide dieselbe Konto-Progression teilen; ein auf LIVE verdienter Bauplan taucht auch in den HOTFIX-Protokollen auf und umgekehrt. Standardmäßig aktiviert. PTU, EPTU und TECH-PREVIEW sind separate Testversionen mit eigener Progression und werden unabhängig von diesem Schalter nie gescannt.
- **Alle Logs erneut scannen (letzten Scan ignorieren)** zwingt den nächsten Scan, jeden Protokolleintrag von Grund auf neu zu lesen, statt nur das, was seit deinem letzten Scan neu ist. Verwende es, wenn deine Besessen-Liste falsch aussieht und ein normaler Scan das nicht behebt. Das Kontrollkästchen deaktiviert sich selbst, sobald der Scan abgeschlossen ist.
- **Protokolle beim Start automatisch durchsuchen** führt denselben Scan automatisch bei jedem Start von Smart Citizen aus, sodass deine Besessen-Liste ohne manuellen Klick aktuell bleibt. Standardmäßig deaktiviert. Das Ergebnis wird dezent in der Statusleiste gemeldet statt in einem Popup, sodass ein Start ohne neue Funde stumm bleibt.
- **Popup für vom Auto-Scan gefundene neue Baupläne anzeigen** bringt das gewohnte Zusammenfassungs-Popup (mit der ausklappbaren Liste der Ergänzungen) zurück, wenn der automatische Start-Scan etwas Neues findet, statt nur der Statusleisten-Meldung. Standardmäßig deaktiviert. Wirkt sich nur aus, wenn der Auto-Scan selbst aktiviert ist, und auch nur, wenn tatsächlich etwas Neues gefunden wird.
- **Eigene Baupläne exportieren… / Eigene Baupläne importieren…** übertragen deine Besessen-Liste zwischen PCs oder teilen sie mit einem Freund. Der Export schreibt alles, was du besitzt, in eine JSON- oder CSV-Datei; der Import liest eine solche Datei ein und ergänzt, was er findet, ohne jemals etwas zu entfernen, das du bereits besitzt. Exporte von scmdb.net lassen sich ebenfalls importieren. Die Importzusammenfassung nennt, wie viele Baupläne neu waren, und listet alle Namen in der Datei auf, die Smart Citizen nicht erfasst.
- **Besessen-Tags anwenden** webt die `[Owned]`-Tags erneut in deine geladenen Strings ein, nachdem du die Besessen-Liste geändert hast. Wie die anderen Aktionsknöpfe wird er **rot**, wenn deine Besessen-Liste Änderungen hat, die die Tabelle noch nicht übernommen hat, und **grün**, sobald alles übereinstimmt.
- Die Spalte **Besessen** der String-Tabelle zeigt weiterhin einen Stern und sortiert besessene zuerst, ist aber jetzt schreibgeschützt; der Besitz wird von diesem Tab aus verwaltet.

## Konfiguration-Tab

- **Erscheinungsbild** — das App-Design wählen (siehe unten).
- **Star-Citizen-Installation** — Pfad zu deinem LIVE-Verzeichnis; bei der Installation automatisch erkannt, hier bearbeitbar. Das Dropdown **Kanal** wählt, welchen Kanal die App liest und beschreibt, und das Dropdown **Sprache** wechselt App- und Spieltexte (siehe *Sprachen wechseln* oben).
- **Smart-Citizen-Daten** — Ordner für `user.ini`, Caches, DataForge-Extraktion, erzeugte Erweiterungs-INIs und Sicherungen. Standardmäßig `Dokumente\Smart Citizen`; verschiebe ihn aus OneDrive heraus, falls Extraktion oder Cache-Bereinigung langsam ist.
- **Basis-Lokalisierung (P4K-Extraktion)** — klicke auf **Aus Data.p4k extrahieren**, um Standard-Lokalisierung sowie DataForge-Entitätsdaten direkt aus deinem installierten Spiel zu entpacken. Dies ist die einzige Quelle für Basis-Strings und Erweiterungsdaten.
- **INI importieren** — eine vorhandene INI-Datei über den Konfliktlösungsdialog in deine Überschreibungen einfügen.
- **user.ini zurücksetzen** — alle deine persönlichen Bearbeitungen für den aktiven Kanal löschen. Fragt um Bestätigung und sichert die aktuelle `user.ini` automatisch, bevor sie geleert wird.
- **user.ini wiederherstellen** — deine persönlichen Bearbeitungen auf eine frühere Momentaufnahme zurücksetzen. Smart Citizen bewahrt rotierende Sicherungen von `user.ini` auf (bis zu 5, automatisch vor jeder Änderung erstellt), sodass du bei einem fehlgeschlagenen Import oder einer Bearbeitung eine frühere Version auswählen und deine Strings zurückbekommen kannst. Die Wiederherstellung selbst ist umkehrbar: die aktuelle Datei wird zuerst gesichert.
- **Einstellungen exportieren… / Einstellungen importieren…**: dein gesamtes Setup (Einstellungen plus die `user.ini` jedes Kanals) in ein kleines Zip sichern oder auf einem neuen PC wiederherstellen. Siehe *Einstellungen exportieren / importieren* oben.

## Protokoll-Tab

- Echtzeit-Anwendungsprotokoll.
- Nach Protokollstufe filtern, automatisch zu den neuesten Einträgen scrollen und das Protokoll für Fehlerbehebung oder Fehlerberichte **exportieren**.

## Designs

Wähle ein Design im Abschnitt **Konfiguration-Tab → Erscheinungsbild**:

- **Standard** — SCLE, ein tiefes Marineblau-Cyber-Design, inspiriert von der mobiGlas-Oberfläche aus Star Citizen.
- **Hell / Dunkel** — klassische Oberflächen-Designs.
- **ODW** — Osiris-DevWorks-Signatur, Marineblau-Anthrazit mit Antikgold.

## Fensterlayout

Smart Citizen merkt sich deine Fenstergröße, das Layout des angedockten String-Editors und deine Spaltenbreiten über Neustarts hinweg. Jeder Tab scrollt seinen eigenen Inhalt, du kannst das Fenster also beliebig klein ziehen und alles durch Scrollen erreichen, statt Bedienelemente gestaucht oder abgeschnitten zu sehen.

Wenn dein Layout einmal unbrauchbar wird (eine Spalte auf einen Streifen zusammengezogen oder eine Fenstergröße, die nicht mehr zu deinem Bildschirm passt), nutze **Mehr → Fensterproportionen zurücksetzen**. Damit werden Fenstergröße, Panel-Layout und Spaltenbreiten auf die Standardwerte zurückgesetzt. Deine Einstellungen, Bearbeitungen und Lokalisierungsdaten bleiben unberührt.

## Statusleiste

Zeigt die Anzahl geladener/geänderter Einträge und den Status eines eventuell laufenden Hintergrund-Arbeitsvorgangs (Extrahieren, Erstellen, Anwenden).

## Geführte Tour

Klicke jederzeit auf den Knopf **Tutorial** in der Symbolleiste, um die geführte Tour erneut abzuspielen — einen Schritt-für-Schritt-Durchgang durch den Kernarbeitsablauf mit Bildschirmhinweisen, die auf jedes Bedienelement zeigen. Die Tour läuft auch automatisch beim ersten Start einer neuen Version, sodass eine frische Installation nie kalt startet. Drücke jederzeit **Überspringen**, um sie zu schließen.

## FAQ-Tab

Der **FAQ**-Tab beantwortet die Fragen, die wir am häufigsten hören, direkt in der App — welche Dateien Smart Citizen berührt, ob du für die Nutzung gebannt werden kannst, warum Windows das Installationsprogramm markiert und wie du deine Änderungen rückgängig machst. Schau zuerst dort nach; wenn deine Frage nicht behandelt wird, ist der Discord nur einen Klick entfernt.

## Tastenkürzel

- **Strg+Umschalt+C** — Gefilterte Zeilen in die Zwischenablage kopieren (Schlüssel=Wert-Format).

## Fehlerbehebung

- **Nichts in der Tabelle** — Stelle sicher, dass **Aus Data.p4k extrahieren** abgeschlossen ist und das Neuladen nach der Extraktion beendet ist, und prüfe dann den **Protokoll-Tab** auf Parsing-Fehler.
- **Erweiterungen leer oder fehlende Einträge** — Führe **Erweiterungen erstellen** aus dem Erweiterungen-Tab aus; dies benötigt einen DataForge-Cache (klicke zuerst auf **Aus Data.p4k extrahieren**, falls noch nicht geschehen).
- **Erweiterungen anwenden schlägt fehl** — Überprüfe den Star-Citizen-Installationspfad im **Konfiguration-Tab** und dass das Spiel nicht läuft.
- **Die Extraktion meldet, dass Data.p4k gesperrt ist**: Der RSI-Launcher lädt gerade ein Update herunter oder überprüft es. Warte, bis er fertig ist (oder schließe den Launcher), und klicke dann erneut auf **Aus Data.p4k extrahieren**.
- **Veraltete Daten nach Spiel-Update** — Führe **Aus Data.p4k extrahieren** erneut aus und erstelle dann die Erweiterungen neu.

## Bekannte Probleme

Manche Missionstext-Anomalien stammen aus den eigenen Daten von Star Citizen: ein falscher Loc-Schlüssel-Verweis in einem Vertragsdatensatz oder eine Bauplan-Belohnung, deren Daten nicht auf einen echten Anzeigenamen zurückverweisen. Das Spiel liest Verträge und Bauplan-Belohnungen zur Laufzeit aus seiner eigenen `Data.p4k`, sodass Smart Citizen diese Fehler nicht an der Quelle beheben kann; es kann nur den *Text* korrigieren, den es selbst erzeugt und anwendet. Wo praktikabel, umgehen wir sie auf Daten- oder Erzeugungsebene, damit das Ergebnis im Spiel trotzdem korrekt lesbar ist.

- **Jorrit-Dossier — „Updated Power Usage Data“ zeigt Energie-Anomalie-Text** — CIG Issue Council [STARC-176797](https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues/STARC-176797). CIGs Vertrag `Hockrow_FacilityDelve_P2M4-Stanton4_Repeat` verweist mit seinem `Description`-Parameter auf `@Hockrow_FacilityDelve_P2M1_Repeat_desc` statt auf seinen eigenen `P2M4_Repeat_desc`, sodass Spieler im Spiel für eine Mission mit dem Titel „Power Usage Data“ den Energie-Anomalie-Stimmungstext von P2M1 sehen. Smart Citizen umgeht dies in zwei Schritten, beide deklariert in `patches/contracts/contractgenerator/mercenary_guild/hockrowagency/hockrowagency_facilitydelve.patch.json`:
  1. Eine DataForge-XML-Bearbeitung, damit unser Erweiterungsgenerator den korrekten P2M4-Bauplan-Pool (Corbel Smolder, Geist Rogue/Whiteout) an `P2M4_Repeat_desc` anhängt, statt auf den von P2M1 zusammenzufallen.
  2. Ein Loc-String-Workaround, der den vollständigen Inhalt von `P2M4_Repeat_desc` (dessen Stimmungstext plus eigenen Bauplan-Pool) an `P2M1_Repeat_desc` anhängt, getrennt durch einen beschrifteten Trenner. Da das Spiel den fehlerhaften Verweis liest und für beide Verträge `P2M1_Repeat_desc` nachschlägt, zeigt der P2M4-Vertrag nun seinen vorgesehenen Inhalt an. P2M1-Spieler sehen den P2M4-Block als beschrifteten Anhang nach ihrer eigenen Beschreibung — unübersichtlicher, aber beide Verträge zeigen jetzt den richtigen Bauplan-Pool und den richtigen Stimmungstext.

  Wenn CIG STARC-176797 korrigiert, kann die gesamte Patch-Datei gelöscht werden, und die nächste Neuerstellung erzeugt wieder saubere, getrennte Beschreibungen.

- **Betankungsmissionen zeigen entstellte Düsennamen** (z. B. „Nozzle Fuelgiver Grin Nozzlefast“ statt „Norfield“) in der MÖGLICHE-BAUPLÄNE-Liste einer Mission. Treibstoffdüsen-Bauplan-Belohnungen verweisen in CIGs Daten nicht wie andere herstellbare Gegenstände auf einen auflösbaren Entitätsnamen zurück, daher fiel unser Erweiterungsgenerator auf eine aus dem internen Dateinamen abgeleitete Namensform statt auf den echten Produktnamen zurück. Für alle 8 bekannten Treibstoffdüsen-Varianten (Marlin, Lindstrom, Bendix, Torrez, Ezra, Norfield, Harkin, RN-7s) über eine Korrektur bekannter Namen in `scripts/generate_enhancements_ini.py` behoben; führe **Erweiterungen erstellen** und **Erweiterungen anwenden** erneut aus, um die Korrektur auch bei Missionen zu übernehmen, die du bereits gesehen hast.

## Feedback, Fehler & Funktionsabstimmung

- **Melde Fehler, teile benutzerdefinierte Konfigurationen und stimme über kommende Funktionen ab** im eigenen Smart-Citizen-Discord-Kanal: [Osiris DevWorks Discord — #smart-citizen feedback & voting](https://discord.com/channels/1438175448420057323/1472394204347895890) (erfordert zuerst den Beitritt zum Osiris-DevWorks-Discord-Server — [Einladung](https://discord.gg/BNzRegKZ7k)). Die Priorisierung von Funktionen richtet sich nach Reaktionen/Abstimmungen in diesem Kanal, je mehr Nachfrage eine Anfrage hat, desto früher landet sie.
- Wenn du einen Fehler meldest, hänge das Protokoll an (Protokoll-Tab → **Exportieren**) und gib die Star-Citizen-Version an, die du verwendest, damit wir Standardprobleme von vorgelagerten Änderungen unterscheiden können.
