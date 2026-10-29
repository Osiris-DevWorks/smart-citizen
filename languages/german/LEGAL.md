# Smart Citizen — Rechtliches & Compliance

Diese Seite sammelt jede rechtliche, lizenzrechtliche und datenschutzbezogene Offenlegung für Smart Citizen an einem Ort. Sollte hier etwas im Widerspruch zu den neben der ausführbaren Datei mitgelieferten Dateien `LICENSE` oder `NOTICE` stehen, sind diese Dateien maßgeblich.

## Star Citizen / Cloud Imperium — Anerkennung

Smart Citizen ist ein **inoffizielles Community-Werkzeug** für Star Citizen. Es wird nicht von Cloud Imperium Games (CIG) oder Roberts Space Industries (RSI) entwickelt, unterstützt, gesponsert oder ist in irgendeiner Weise mit ihnen verbunden. Smart Citizen fällt unter CIGs „Made by the Community“-Richtlinien für von Fans erstellte Inhalte und Werkzeuge.

**Star Citizen®**, **Roberts Space Industries®** und **Cloud Imperium®** sind eingetragene Marken der Cloud Imperium Rights LLC und der Cloud Imperium Rights Ltd. Alle Star-Citizen-Spieldaten, einschließlich des Inhalts von `Data.p4k`, Schiffs- und Komponentenmodelle, Gegenstandsnamen, Missionstext und Hintergrundgeschichte, sind geistiges Eigentum der Cloud Imperium Rights LLC.

Smart Citizen verbreitet keine Inhalte von CIG oder RSI weiter. Die App liest Dateien aus **deiner eigenen lizenzierten Star-Citizen-Installation** auf deinem lokalen Rechner und schreibt benutzerdefinierte Strings zurück in dieselbe Installation. Kein CIG-eigener Inhalt verlässt deinen Computer über Smart Citizen.

## Smart-Citizen-Lizenz

Smart Citizen ist Open-Source-Software, lizenziert unter der **Apache-Lizenz, Version 2.0**. Eine Kopie der Lizenz erhältst du unter [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0). Der vollständige Lizenztext liegt der `LICENSE`-Datei neben der ausführbaren Datei bei, und der Quellcode ist im [GitHub-Repository](https://github.com/Osiris-DevWorks/smart-citizen) verfügbar.

Sofern nicht durch geltendes Recht gefordert oder schriftlich vereinbart, wird die unter der Lizenz vertriebene Software **„WIE BESEHEN“ ohne jegliche ausdrückliche oder stillschweigende Gewährleistungen oder Bedingungen** bereitgestellt. Die genauen Berechtigungen und Einschränkungen findest du in der Lizenz.

## Gebündelte Drittanbieter-Software

Smart Citizen liefert die folgende Drittanbieter-Software in seinem Installationsprogramm mit. Der vollständige Zuschreibungstext für jede findet sich in der Datei `NOTICE` neben der ausführbaren Datei.

- **unp4k / unforge** — Mitgeliefert unter `assets/unp4k/` als `unp4k.exe` und `unforge.exe`. Osiris DevWorks liefert einen eigenen Fork ([odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k)) des ursprünglichen Projekts [dolkensp/unp4k](https://github.com/dolkensp/unp4k) mit paralleler Extraktion und Leistungsverbesserungen. Wird verwendet, um `Data.p4k` zu entpacken und DataForge-Entitätsdateien in XML zu konvertieren. Lizenziert unter der **MIT-Lizenz**.
- **PyQt6** — Oberflächen-Framework von Riverbank Computing. Verwendet unter der **GNU General Public License v3 (GPL-3.0)** für nicht-kommerzielle Verbreitung; eine kommerzielle Lizenzierung ist ebenfalls von Riverbank erhältlich. Smart Citizen ist ein kostenloses, quelloffenes Community-Werkzeug und erfüllt die Bedingungen der GPL-3.0.
- **lxml** — XML-Parsing-Bibliothek von lxml.de. Verwendet unter der **BSD-3-Clause-Lizenz**.

Die Python-Standardbibliothek und andere von PyInstaller mitgelieferte Laufzeitabhängigkeiten unterliegen ihren eigenen Lizenzen; siehe die Python Software Foundation License unter [docs.python.org/3/license.html](https://docs.python.org/3/license.html).

## Datenschutz & Datenverarbeitung

Smart Citizen ist eine **lokale Desktop-Anwendung**. Sie überträgt deine Bearbeitungen, deine `user.ini`, deine `base.ini`, deine Anpassungen oder andere Inhalte von deinem Computer nicht an einen von Osiris DevWorks oder Dritten betriebenen Server.

### Was auf deinem Computer bleibt

Alles. Deine Lokalisierungsbearbeitungen, Sicherungen, Anwendungseinstellungen und der DataForge-Cache leben ausschließlich auf deiner lokalen Festplatte:

- **Einstellungen** — Windows-Registry unter `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` bei der Standardinstallation, oder `config.json` neben der ausführbaren Datei beim portablen Build.
- **Benutzerbearbeitungen + Sicherungen** — standardmäßig `Dokumente\Smart Citizen\{Kanal}\` (konfigurierbar im Konfiguration-Tab; der portable Build verwendet stattdessen `<exe-Verzeichnis>\data\`).
- **DataForge-XML-Cache** — `%LOCALAPPDATA%\Smart Citizen\{Kanal}\cache\dataforge\`.
- **Absturzprotokolle + manuelle Protokollexporte** — `Dokumente\Smart Citizen\logs\` (oder das portable Äquivalent), nur geschrieben, wenn die App abstürzt oder du im Protokoll-Tab auf *Exportieren* klickst.

### Was über das Netzwerk läuft

Smart Citizen stellt ausgehende Netzwerkanfragen nur in drei Fällen:

- **Update-Prüfung** — Eine kleine, nicht authentifizierte Anfrage an `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest` etwa alle 6 Stunden, um die installierte Version mit dem neuesten GitHub-Release zu vergleichen. Liefert nur Release-Metadaten (Tag-Name, Release-URL); es wird kein Smart-Citizen-Zustand gesendet.
- **Sprach-Downloads** — Wenn du zu einer nicht-englischen Sprache wechselst, lädt Smart Citizen die von der Community übersetzte `global.ini` dieser Sprache von der konfigurierten URL herunter (standardmäßig das GitHub-Repository [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization) für einige Sprachen, andere Sprachen verwenden ihre eigene konfigurierte Quelle — siehe `languages/sources.json`). Der Download wird lokal zwischengespeichert; nichts von deinem Rechner wird gesendet.
- **Benutzerdefinierte Remote-Quellen** — Wenn du im Konfiguration-Tab eine Datenquelle konfiguriert hast, die auf eine `http(s)://`-URL verweist, ruft Smart Citizen diese URL beim Aktualisieren von Quelldateien ab. Standardmäßig gilt dies nur für die GitHub-Raw-URL-Form der `global`-Quelle; die Standardkonfiguration liest seit v1.0 stattdessen `base.ini` aus deiner lokalen Data.p4k-Extraktion.

### Was Smart Citizen **nicht** tut

- Keine Telemetrie, Analyse oder Nutzungsberichte jeglicher Art.
- Keine personenbezogenen Daten werden erfasst, gespeichert oder übertragen.
- Keine Hintergrund-Daten-Uploads.
- Keine automatische Absturzmeldung an einen Remote-Server — Absturzprotokolle werden **nur lokal** unter `Dokumente\Smart Citizen\logs\` geschrieben. Wenn du eines für einen Fehlerbericht teilen möchtest, kopierst und fügst du die Datei selbst ein.
- Keine Konten, keine Anmeldung, keine Remote-Identität.

Solltest du ein Verhalten entdecken, das im Widerspruch zum Obigen steht, melde bitte einen Fehler unter [github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues).

## KI-Nutzungserklärung

Teile des Quellcodes von Smart Citizen wurden mit Unterstützung von **Claude**, Anthropics KI-Programmierassistent, geschrieben. Generierter Code wird **von einem menschlichen Maintainer geprüft und freigegeben, bevor er zusammengeführt wird** — die KI committet nicht direkt und wird wie jeder andere Code-Beitrag behandelt: gelesen, getestet und nur nach seinen Verdiensten akzeptiert.

Im Einzelnen:

- KI-Unterstützung beschleunigt die Entwicklung von Generatoren, Klassifikatoren, Refactorings und Tests; mit KI-Hilfe erstellte Commits tragen einen `Co-Authored-By: Claude`-Vermerk in ihrer Commit-Nachricht, sodass die Historie überprüfbar ist.
- Alle Star-Citizen-Spieldaten-Parsing-Logik, Missionsklassifikation und String-Verarbeitungsregeln werden von den menschlichen Maintainern entworfen und gegen echte DataForge-Cache-Beispiele validiert.
- Einige der Oberflächen- und Dokumentationsübersetzungen von Smart Citizen sind KI-generierte Platzhalter, bis menschliche Übersetzungen eintreffen. Sie werden pro Sprache und pro String in `languages/TRANSLATIONS.md` verfolgt und ersetzt, sobald menschliche Übersetzungen eintreffen. Vorhandene menschliche Übersetzungen werden niemals von der KI verändert.
- **Die Anwendung selbst enthält keine KI- oder Machine-Learning-Funktionen.** Smart Citizen bündelt kein Modell, ruft zur Laufzeit keinen KI-Dienst auf und überträgt deine Bearbeitungen oder Star-Citizen-Spieldaten nicht an einen KI-Anbieter.

## Rechtliche Anliegen melden

Wenn du glaubst, dass Smart Citizen ein Urheberrecht, eine Marke oder ein anderes Recht verletzt, das du besitzt — oder wenn du eine Frage dazu hast, wie die App mit deinen Daten umgeht — eröffne ein Issue oder kontaktiere die Maintainer über den [Osiris DevWorks Discord](https://discord.gg/BNzRegKZ7k).
