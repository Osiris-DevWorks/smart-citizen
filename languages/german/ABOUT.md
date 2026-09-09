# Smart Citizen

*Smartere Strings für Star Citizen*

## Über dieses Projekt

**Smart Citizen** ist ein leistungsstarkes, benutzerfreundliches Werkzeug für Star-Citizen-Spieler, um die Lokalisierungs-Strings ihres Spiels anzupassen. Lade, bearbeite und wende Lokalisierungsänderungen an — mit vollständiger Persistenz, automatischen Sicherungen und nahtloser Unterstützung für Spiel-Updates.

Entwickelt von **Osiris DevWorks**, einem Ein-Mann-Entwicklungsstudio, das sich der Erstellung wertvoller Werkzeuge für die Gaming-Community widmet.

## Das Osiris-DevWorks-Versprechen

Alle Werkzeuge von Osiris DevWorks werden entweder **vollständig kostenlos** sein oder eine **kostenlose Stufe** haben. Wir glauben daran, Spielern Mehrwert zu bieten, ohne Bezahlschranken oder verpflichtende Abonnements.

## ODW-Team

- **Osiris_x**
- **Tichro**

## Mitwirkende

Danke an alle, die Code zu Smart Citizen beigetragen haben:

- **Stealrull**
- **Ishikudeska**
- **jonigirl**
- **Coerwyn**
- **denis-coach** (h0use)
- **scubamount**
- **hkstrongside**
- **odw-okano**

## Übersetzer

Danke an alle, die die Oberfläche von Smart Citizen übersetzt haben:

- **Akwa** (Français)
- **Nxzzin** (Português brasileiro)
- **Thord82** (Español)

## Danksagungen

Danke an die Tester, die Smart Citizen mit ihrem Feedback mitgestaltet haben:

- **Boogie Man**
- **Perseuscz**
- **Flat Earth**
- **Lord Valium**
- **Zero**
- **Apolleon Phoibos**
- **Epiq**
- **Narull**
- **XaileiShiv**
- **Mindbulletz**

### Unterstützer

Danke an alle, die das Projekt finanziell unterstützt haben — eure Beiträge helfen, Smart Citizen für alle kostenlos zu halten:

- **Dimwit the Wise**

Smart Citizen bündelt außerdem vorgelagerte Werkzeuge von:

- [**Osiris-DevWorks/odw-fast-unp4k**](https://github.com/Osiris-DevWorks/odw-fast-unp4k) — `unp4k.exe` und `unforge.exe`, verwendet zum Entpacken von `Data.p4k` und zum Konvertieren von DataForge in XML. Dies ist unser Fork des ursprünglichen [**dolkensp/unp4k**](https://github.com/dolkensp/unp4k) mit paralleler Extraktion und weiteren Leistungsverbesserungen.

Die nicht-englischen Spieltexte sind Community-Übersetzungen:

- [**Dymerz/StarCitizen-Localization**](https://github.com/Dymerz/StarCitizen-Localization) — die von der Community gepflegten `global.ini`-Übersetzungen, die die Sprachoptionen Französisch, brasilianisches Portugiesisch und Italienisch antreiben. Die eigentliche Arbeit leisten deren Übersetzer; wir liefern sie nur aus.
- [**Thord82/Star_citizen_ES**](https://github.com/Thord82/Star_citizen_ES): die von der Community gepflegte `global.ini`-Übersetzung, die die spanische Sprachoption antreibt.
- [**stdblue/StarCitizenJapaneseResources**](https://github.com/stdblue/StarCitizenJapaneseResources): die von der Community gepflegte `global.ini`-Übersetzung, die die japanische Sprachoption antreibt.
- [**42Kit**](https://ini.42kit.com/): die von der Community gepflegte `global.ini`-Übersetzung, die die chinesische (vereinfachte) Sprachoption antreibt.
- [**rjcncpt/StarCitizen-Deutsch-INI**](https://github.com/rjcncpt/StarCitizen-Deutsch-INI) — die von der Community gepflegte `global.ini`-Übersetzung, die die deutsche Sprachoption antreibt.
- [**Orbit-Startech/StarCitizen-TCTP**](https://github.com/Orbit-Startech/StarCitizen-TCTP): die von der Community gepflegte `global.ini`-Übersetzung, die die traditionell-chinesische Sprachoption antreibt. Zuletzt im Mai 2024 aktualisiert, deckt sie etwa zwei Drittel der aktuellen Spieltexte ab; der Rest fällt auf Englisch zurück.

## Hauptfunktionen

### 🎯 Kernfunktionen
- **Laden & Bearbeiten**: Lade `global.ini` aus deiner Star-Citizen-Installation und passe Strings in einer intuitiven Tabellenansicht an
- **Unterstützung mehrerer Kanäle**: LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW erhalten jeweils eigene isolierte `user.ini`, Cache, Sicherungen und DataForge-Extraktion — Kanäle im Konfiguration-Tab ohne Neustart wechseln
- **Unterstützung mehrerer Sprachen**: Wechsle App und Spieltexte zwischen Englisch, Französisch, Spanisch, brasilianischem Portugiesisch, Japanisch, Chinesisch (vereinfacht), Italienisch, Deutsch und traditionellem Chinesisch im Konfiguration-Tab. Nicht-englische Sprachen legen eine von der Community übersetzte `global.ini` über die englische Basis, mit englischem Rückfall für alles Unübersetzte. Weitere Sprachen werden freigeschaltet, sobald Community-Übersetzungen eintreffen (siehe `languages/TRANSLATIONS.md`)
- **Missionsverträge**: Bearbeite Missionsvertrags- und Briefing-Text aus der eigenen Kategorie Missionen
- **Intelligente Filterung**: Strings durchsuchen, nach Kategorie (Schiffe, Schiffsgegenstände, Missionen, Ausrüstung, Rohstoffe, Journal, Sonstiges) oder Änderungsstatus filtern
- **Spaltenfilter**: Direkt in Filterfelder unter jeder Spaltenüberschrift tippen für feingranulare Suche
- **Live-Vorschaubereich**: Eine seitliche Vorschau rendert den Text der ausgewählten Zeile, wobei die Loc-Tokens des Spiels (Zeilenumbrüche, EM3/EM4-Hervorhebung, Missionsplatzhalter) in gestyltes HTML übersetzt werden, sodass du ungefähr siehst, wie der String im Spiel aussehen wird
- **Editor-Seitenpanel**: Über die Symbolleiste umschaltbare, größenveränderbare, abdockbare Fläche zum Bearbeiten langer Werte (Journaleinträge, Missionsbriefings, Schiffsbeschreibungen) mit Unterstreichen-/Hervorheben-Knöpfen und Live-Synchronisation zwischen den Bereichen
- **Sichere Anwendung**: Anwenden schreibt in `global.ini`, zuerst mit einer automatischen Sicherung mit Zeitstempel, validiert die Ausgabe gegen den Standard-Schlüsselsatz und macht bei jeder Abweichung automatisch rückgängig
- **Sicherungen wiederherstellen**: Bis zu 5 Sicherungsversionen pro Kanal aufbewahren — Änderungen jederzeit mit einem Klick rückgängig machen
- **Lokalisierung leeren**: Dein Spiel auf den Originaltext zurücksetzen, ohne deine gespeicherten Überschreibungen zu verlieren
- **INI importieren**: Eine vorhandene INI-Datei importieren und Konflikte Schlüssel für Schlüssel mit dem integrierten Konfliktdialog lösen
- **Einfacher & erweiterter Modus**: Öffnet sich zu einem einfachen Zwei-Knopf-Bildschirm (ein Knopf wendet Erweiterungen mit deinen gespeicherten Einstellungen an, der andere wechselt zur erweiterten Ansicht), oder nutze die vollständige erweiterte Oberfläche (Tabelle, Filter, Erweiterungen, Konfiguration), wann immer du von Hand bearbeiten möchtest. Wähle deinen Standard bei der Installation und wechsle jederzeit in der App zwischen ihnen
- **FAQ-Tab**: Die häufigsten Fragen, direkt in der App beantwortet — welche Dateien berührt werden, Bann-Risiko, die Windows-Warnung vor unbekannten Apps und wie man Änderungen rückgängig macht
- **Flexibles Fenster & Spalten**: Ändere die Fenstergröße beliebig — jeder Tab scrollt seinen eigenen Inhalt, statt Bedienelemente zu stauchen oder abzuschneiden. Die Spalten des String-Editors lassen sich per Ziehen anpassen (Doppelklick auf einen Trenner passt die Spalte an ihren Inhalt an), und Breiten wie Fensterlayout bleiben über Neustarts hinweg erhalten — mit **Mehr → Fensterproportionen zurücksetzen** stellst du die Standardwerte wieder her
- **Geführtes Tutorial**: Eine Coach-Mark-Tour führt neue Nutzer beim ersten Start jeder Version durch den Arbeitsablauf — jederzeit über den Tutorial-Knopf wiederholbar

### 🔄 Datenquelle & Persistenz
- **Aus Data.p4k bezogen**: Alle Standard-Lokalisierungs- und DataForge-Entitätsdaten werden direkt aus deiner installierten `Data.p4k` entpackt — keine Downloads, keine Community-Spiegelserver, immer synchron mit deiner tatsächlichen Spielversion
- **Persistente Bearbeitungen**: Deine Anpassungen werden automatisch gespeichert und in jeder Sitzung neu geladen
- **Nahtlose Migration**: Wenn Star Citizen aktualisiert wird, erneut aus der gepatchten `Data.p4k` extrahieren — deine gespeicherten Bearbeitungen werden automatisch auf die neuen Basis-Strings angewendet
- **Übersichtliche Oberfläche**: Leistungsstarke Tabellenansicht mit Filtern, Inline-Bearbeitung, Tastenkürzeln und einer modernen Oberfläche

### 📊 Erweiterungen
- **Schiffswerte**: SCM-Geschwindigkeit, Wasserstoff-/Quantumtreibstoff, Frachtkapazität, vollständige Waffenausrüstung und Panzerungsmultiplikatoren (physisch / Energie / Distortion / thermisch), angehängt an Schiffsbeschreibungen
- **Komponentenwerte**: Schild-HP, Energieverbrauch, Kühlrate, Regeneration und ähnliche Werte für Schilde, Kühler, Kraftwerke, Quantenantriebe und Radare — standardmäßig mit Namens-Tags im Stil `[MIL-S2-A]` (vollständig anpassbar im Tag-Generator)
- **Waffenwerte**: DPS, Feuerrate, Reichweite und Schaden bei Schiffswaffen und Geschütztürmen von S1 bis Capital. Schiffswaffen erhalten ein Schaden+Größe-Tag im Stil `[E-S2]`, Raketen `[IR-S1] Arrester III` und Bomben `[S5] 500SCB Cluster`
- **Missionsanmerkungen**: `[BP]` / `[BP?]`-Bauplan-Belohnungs-Tags bei Titeln, plus strukturierte Blöcke *MISSIONSDETAILS*, *MÖGLICHE BAUPLÄNE* und *GEGENSTANDSBELOHNUNGEN* in Beschreibungen. Ruf-Stufen-Zeilen zeigen echte Rangnamen (Rookie, Jr. Contractor usw.) statt generischer Nummerierung. Missions-XP nennt die Ruf-Spur, die sie speist, und Battaglias Scan-/Bergbau-Titel tragen `[RS ####]`-Ressourcensignatur-Tags, ergänzt durch eine MISSIONSDETAILS-Aufschlüsselung „Ressourcensignaturen“ pro Zielerz und eine Erznamen-Anmerkung, die überall angezeigt wird, wo das Spiel diesen Namen darstellt, einschließlich des Missions-Trackers (zwei unabhängige Schalter, beide standardmäßig aktiviert)
- **Journal-Querverweise**: Bergbau-Kompendium-Einträge erhalten Herstellungs-Querverweise und die Basis-Ressourcensignatur jedes Erzes; in der Herstellung verwendete Rohstoffe erhalten ein anpassbares `[CF]`-Namens-Tag und eine Liste aller Baupläne, die sie benötigen
- **Effekte medizinischer Verbrauchsgüter**: Die Basis-CureLife-Pens (MedPen, OxyPen, AdrenaPen und Verwandte) erhalten eine verständliche Wirkungszeile, sodass die Beschreibung sagt, was der Pen tatsächlich bewirkt, statt nur seine Hintergrundgeschichte
- **Schiffsfavoriten**: Markiere ein Schiff mit einem Stern, um ein konfigurierbares Präfix (Standard `*`) voranzustellen, damit Favoriten im In-Game-ASOP-Terminal ganz oben einsortiert werden
- **Tag-Generator**: Passe die eingeklammerten Tags bei Komponenten, Raketen, Schiffswaffen und Rohstoffen an — Elemente neu anordnen, Abkürzungslänge ändern (M / MIL / Military), Trennzeichen und Klammern wählen oder das Tag statt davor dahinter platzieren. Komponenten haben ein optionales Typ-Element (Schild, Kühler usw.); Rohstoffe haben ein Verwendungs-Element, das zeigt, wofür ihre Herstellungsmaterialien verwendet werden
- **Missionstitel**: Frachtmissionstitel mit ihrer Route einleiten (z. B. `Area18 > Lorville`) — konfigurierbare Platzierung, Pfeil, Trennzeichen und Ortsdetail, plus optionale Kürzung des Originaltitels, mit Live-Vorschau
- **Werte oberhalb oder unterhalb**: Wähle, ob ein Statistikblock oben oder unten in der Beschreibung sitzt
- **Bauplan-Tracker**: Ein eigener Tab zum Markieren der Herstellungs-Baupläne, die du bereits besitzt. Gegenstände zwischen Verfügbar und Besessen verschieben, nach Mission / Typ / Klasse / Größe / Grad filtern, und besessene Gegenstände erhalten ein blaues `[Owned]`-Tag in Missions-Bauplan-Listen. **Protokolle nach besessenen Bauplänen durchsuchen** füllt den Besitz automatisch aus deinen Star-Citizen-Protokolldateien, wobei nur importiert wird, was seit dem letzten Scan neu ist, und **Eigene Baupläne exportieren / importieren** überträgt die Besessen-Liste zwischen PCs (JSON oder CSV; Importe fügen immer nur hinzu, und auch scmdb.net-Exporte funktionieren)
- **Missionsbezeichnungen**: Die Abschnittsüberschriften (MISSIONSDETAILS, MÖGLICHE BAUPLÄNE usw.), die XP-Bezeichnung und das für Überschriften verwendete Hervorhebungs-Tag umbenennen
- **Deklarative CIG-Datenfehler-Patches**: Ein Patch-System wendet Korrekturen für bekannte DataForge-Fehler zur Extraktionszeit an, sodass der In-Game-Text korrekt angezeigt wird, ohne auf CIG warten zu müssen
- **Selektive Kategorien**: Jede Erweiterungskategorie unabhängig im Erweiterungen-Tab aktivieren oder deaktivieren

### 🎨 Designs
- **Standard**: Tiefes Marineblau-Cyber-Design, inspiriert von der mobiGlas-Oberfläche aus Star Citizen
- **Hell / Dunkel**: Klassische Oberflächen-Designs
- **ODW**: Osiris-DevWorks-Signaturdesign — Marineblau-Anthrazit mit Antikgold

### 🛡️ Datenverwaltung
- **Automatische Sicherungen**: Sicherungen mit Zeitstempel werden vor dem Anwenden von Änderungen an deinem Spiel erstellt (bis zu 5 pro Kanal)
- **Registry-Persistenz**: Alle Pfade und Einstellungen werden sicher in der Windows-Registry gespeichert
- **Konfigurierbare Datenspeicherung**: Deine benutzerdefinierten Bearbeitungen werden unter `<Datenordner>\<Kanal>\` gespeichert (Standard `Dokumente\Smart Citizen`, ein isolierter Unterbaum pro Star-Citizen-Kanal) für sichere Persistenz über Sitzungen hinweg
- **Einstellungssicherung**: Exportiere dein gesamtes Setup (Einstellungen, Tag-Konfigurationen und die String-Überschreibungen jedes Kanals) in ein kleines Zip und importiere es dann auf einem neuen PC oder nach dem Entpacken einer frischen portablen Version. Importe sichern zuerst deine aktuellen Dateien als Momentaufnahme, daher sind sie umkehrbar
- **Protokollanzeige in der App**: Echtzeit-Anwendungsprotokoll mit Stufenfilter, automatischem Scrollen und einem Export-Knopf für Fehlerberichte
- **Auto-Updater**: Smart Citizen prüft beim Start GitHub Releases und zeigt die Release-Notizen in der App; ein Klick (plus eine Windows-Berechtigungsabfrage) lädt das Update herunter, installiert es und öffnet die App neu

## Schnellstart

1. **Erster Start**: Die App erkennt deine Star-Citizen-Installation automatisch (bearbeitbar im **Konfiguration**-Tab)
2. **Extrahieren**: Klicke im Konfiguration-Tab auf **Aus Data.p4k extrahieren**, um Standard-Lokalisierung + DataForge-Entitätsdaten aus deinem installierten Spiel zu entpacken — die Strings werden nach Abschluss der Extraktion automatisch in die Tabelle geladen
3. **Strings bearbeiten**: Nutze die Such- und Filterwerkzeuge und doppelklicke dann auf eine beliebige Zelle in Benutzerdefinierter Wert, um Text anzupassen
4. **Anwenden**: Klicke auf **Erweiterungen anwenden** — deine Änderungen werden gespeichert und mit einer automatischen Sicherung angewendet
5. **Erweiterungen (optional)**: Öffne den Erweiterungen-Tab, um Statistik-Overlays für Schiffe, Komponenten, Waffen und Missionsbelohnungen zu aktivieren
6. **Nach Spiel-Updates**: Führe „Aus Data.p4k extrahieren“ erneut aus — deine Bearbeitungen werden automatisch erneut angewendet

## Community & Unterstützung

### Tritt uns bei
- 💬 [Discord-Community](https://discord.gg/BNzRegKZ7k) - Support erhalten, Konfigurationen teilen, Funktionen anfragen
- 🐛 [Smart Citizen Feedback, Fehler & Funktionsabstimmung](https://discord.com/channels/1438175448420057323/1472394204347895890) - Eigener Kanal für Fehlerberichte, Feedback und Abstimmungen über kommende Funktionen (tritt zuerst über die obige Einladung dem Server bei)

### Videoanleitungen
- 🎥 [Star Citizen Hides Important Mission Info – This Tool Shows It In-Game & More!](https://www.youtube.com/watch?v=Xo1t404gsgs) von **Karolinger** - ein Community-Überblick über die Funktionen von Smart Citizen

### Dieses Projekt unterstützen
Smart Citizen ist völlig kostenlos. Wenn du es wertvoll findest:
- 💳 [Über PayPal spenden](https://www.paypal.com/ncp/payment/YAWXHMGZH8T76)
- 💰 [Über Venmo spenden](https://venmo.com/u/Amr-Abouelleil)

## Weitere Werkzeuge von Osiris DevWorks

- **[Battlestations](https://battlestations.osiris-devworks.com/)** - Star-Citizen-Hangar-Battlestation-Builds verwalten und teilen
- **[SC Profile Editor](https://github.com/Osiris-DevWorks/sc-profile-editor)** - Star-Citizen-Steuerungsprofile importieren, bearbeiten und exportieren
- **[Extended AFK](https://github.com/Osiris-RK/extended-afk)** - AFK-Werkzeug zur Vermeidung von Leerlauf-Timeouts

## Basiert auf

Erstellt mit **PyQt6** und inspiriert von der Lokalisierungsarbeit der Star-Citizen-Community.

**GitHub**: https://github.com/Osiris-DevWorks/smart-citizen

## Lizenz & Rechtliches

Smart Citizen ist unter der **Apache-Lizenz, Version 2.0** lizenziert.

Siehe den **Rechtliches**-Tab für die vollständige Lizenzzusammenfassung, Zuschreibungen gebündelter Drittanbieter-Software (unp4k / PyQt6 / lxml), Cloud-Imperium-„Made by the Community“-Anerkennungen, Offenlegung zu Datenschutz & Datenverarbeitung sowie die KI-Nutzungserklärung.
