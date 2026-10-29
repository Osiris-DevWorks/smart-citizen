# Smart Citizen — Note legali e conformità

Questa pagina raccoglie in un unico posto tutte le informazioni legali, di licenza e di gestione dei dati relative a Smart Citizen. Se qualcosa qui contraddice i file `LICENSE` o `NOTICE` distribuiti insieme all'eseguibile, tali file fanno fede.

## Riconoscimento Star Citizen / Cloud Imperium

Smart Citizen è uno **strumento comunitario non ufficiale** per Star Citizen. Non è sviluppato, approvato, sponsorizzato né in alcun modo affiliato a Cloud Imperium Games (CIG) o Roberts Space Industries (RSI). Smart Citizen rientra nelle linee guida "Made by the Community" di CIG per i contenuti e gli strumenti creati dai fan.

**Star Citizen®**, **Roberts Space Industries®** e **Cloud Imperium®** sono marchi registrati di Cloud Imperium Rights LLC e Cloud Imperium Rights Ltd. Tutti i dati di gioco di Star Citizen, inclusi i contenuti di `Data.p4k`, i modelli di navi e componenti, i nomi degli oggetti, i testi delle missioni e il lore, sono proprietà intellettuale di Cloud Imperium Rights LLC.

Smart Citizen non ridistribuisce alcun contenuto di CIG o RSI. L'applicazione legge i file dalla **tua installazione di Star Citizen regolarmente licenziata** sulla tua macchina locale e riscrive le stringhe personalizzate dall'utente su quella stessa installazione. Nessun contenuto di proprietà di CIG lascia il tuo computer tramite Smart Citizen.

## Licenza di Smart Citizen

Smart Citizen è un software open source concesso in licenza secondo i termini della **Apache License, Version 2.0**. Puoi ottenerne una copia su [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0). Il testo completo della licenza è distribuito nel file `LICENSE` accanto all'eseguibile, e il codice sorgente è disponibile presso il [repository GitHub](https://github.com/Osiris-DevWorks/smart-citizen).

Salvo quanto richiesto dalla legge applicabile o concordato per iscritto, il software distribuito sotto questa Licenza è fornito **"COSÌ COM'È", senza garanzie o condizioni di alcun tipo**, espresse o implicite. Per il testo specifico che regola i permessi e le limitazioni, consulta la Licenza.

## Software di terze parti incluso

Smart Citizen distribuisce nel proprio installer i seguenti software di terze parti. Il testo completo di attribuzione per ciascuno si trova nel file `NOTICE` accanto all'eseguibile.

- **unp4k / unforge** — Incluso in `assets/unp4k/` come `unp4k.exe` e `unforge.exe`. Osiris DevWorks distribuisce un proprio fork ([odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k)) del progetto originale [dolkensp/unp4k](https://github.com/dolkensp/unp4k), con estrazione parallela e miglioramenti delle prestazioni. Utilizzato per estrarre `Data.p4k` e convertire in XML i file delle entità DataForge. Concesso in licenza secondo i termini della **MIT License**.
- **PyQt6** — Framework per l'interfaccia grafica, di Riverbank Computing. Utilizzato secondo i termini della **GNU General Public License v3 (GPL-3.0)** per la distribuzione non commerciale; una licenza commerciale è disponibile anche presso Riverbank. Smart Citizen è uno strumento comunitario gratuito e open source e soddisfa i requisiti della GPL-3.0.
- **lxml** — Libreria per il parsing XML, di lxml.de. Utilizzata secondo i termini della **licenza BSD-3-Clause**.

La libreria standard di Python e le altre dipendenze di runtime incluse tramite PyInstaller sono soggette alle rispettive licenze; vedi la Python Software Foundation License su [docs.python.org/3/license.html](https://docs.python.org/3/license.html).

## Privacy e gestione dei dati

Smart Citizen è un'**applicazione desktop locale**. Non trasmette le tue modifiche, il tuo `user.ini`, il tuo `base.ini`, le tue personalizzazioni, né alcun altro contenuto del tuo computer a nessun server gestito da Osiris DevWorks o da terze parti.

### Cosa rimane sul tuo computer

Tutto. Le tue modifiche di localizzazione, i backup, le impostazioni dell'applicazione e la cache DataForge risiedono esclusivamente sul tuo disco locale:

- **Impostazioni** — Registro di Windows sotto `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` nell'installazione predefinita, oppure `config.json` accanto all'eseguibile nella build portatile.
- **Modifiche utente + backup** — `Documents\Smart Citizen\{channel}\` per impostazione predefinita (configurabile nella scheda Config; la build portatile usa invece `<exe-dir>\data\`).
- **Cache XML DataForge** — `%LOCALAPPDATA%\Smart Citizen\{channel}\cache\dataforge\`.
- **Dump di arresto anomalo + esportazioni manuali del log** — `Documents\Smart Citizen\logs\` (o equivalente portatile), scritti solo quando l'applicazione si arresta in modo anomalo o quando fai clic su *Export* nella scheda Log.

### Cosa viene trasmesso in rete

Smart Citizen effettua richieste di rete in uscita solo in tre circostanze:

- **Controllo aggiornamenti** — Una piccola richiesta non autenticata a `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest` circa ogni 6 ore, per confrontare la versione installata con l'ultima release su GitHub. Restituisce solo metadati della release (nome del tag, URL della release); non viene inviato alcuno stato di Smart Citizen.
- **Download delle lingue** — Quando passi a una lingua diversa dall'inglese, Smart Citizen scarica il `global.ini` tradotto dalla comunità per quella lingua dall'URL configurato (per impostazione predefinita il repository GitHub [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization)). Il download viene memorizzato in cache localmente; nulla dalla tua macchina viene inviato.
- **Fonti remote configurate dall'utente** — Se hai configurato una fonte dati che punta a un URL `http(s)://` nella scheda Config, Smart Citizen recupera quell'URL durante l'aggiornamento dei file di origine. Di base questo riguarda solo la forma URL GitHub-raw della fonte `global`; la configurazione standard a partire dalla v1.0 legge invece `base.ini` dalla tua estrazione locale di Data.p4k.

### Cosa Smart Citizen **non** fa

- Nessuna telemetria, analisi o segnalazione di utilizzo di alcun tipo.
- Nessuna informazione personalmente identificabile raccolta, memorizzata o trasmessa.
- Nessun caricamento di dati in background.
- Nessuna segnalazione automatica degli arresti anomali a un server remoto — i dump di arresto anomalo vengono scritti **solo localmente** in `Documents\Smart Citizen\logs\`. Se desideri condividerne uno per una segnalazione di bug, sei tu a copiare e incollare il file.
- Nessun account, nessun login, nessuna identità remota.

Se riscontri un comportamento in contrasto con quanto sopra, ti preghiamo di segnalare un bug su [github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues).

## Dichiarazione sull'uso dell'IA

Alcune parti del codice sorgente di Smart Citizen sono state scritte con l'assistenza di **Claude**, l'assistente IA per la programmazione di Anthropic. Il codice generato viene **revisionato e approvato da un maintainer umano prima del merge** — l'IA non esegue commit direttamente ed è trattata come qualsiasi altro contributo di codice: letto, testato e accettato solo in base ai suoi meriti.

Nello specifico:

- L'assistenza dell'IA accelera lo sviluppo di generatori, classificatori, refactoring e test; i commit realizzati con l'aiuto dell'IA riportano un trailer `Co-Authored-By: Claude` nel messaggio di commit, in modo che la cronologia sia verificabile.
- Tutta la logica di analisi dei dati di gioco di Star Citizen, la classificazione delle missioni e le regole di gestione delle stringhe sono progettate dai maintainer umani e validate su campioni reali della cache DataForge.
- Alcune traduzioni dell'interfaccia e della documentazione di Smart Citizen sono generate dall'IA come sostituti temporanei, in attesa dell'arrivo di traduzioni umane. Sono tracciate, per lingua e per stringa, in `languages/TRANSLATIONS.md`, e vengono sostituite man mano che arrivano le traduzioni umane. Le traduzioni umane già esistenti non vengono mai modificate dall'IA.
- **L'applicazione in sé non contiene alcuna funzionalità di IA o apprendimento automatico.** Smart Citizen non include alcun modello, non richiama alcun servizio di IA in fase di esecuzione, e non trasmette le tue modifiche né i dati di gioco di Star Citizen a un fornitore di IA.

## Segnalazione di questioni legali

Se ritieni che Smart Citizen violi un diritto d'autore, un marchio o un altro diritto di cui sei titolare — oppure se hai una domanda su come l'applicazione gestisce i tuoi dati — apri una issue o contatta i maintainer tramite il [Discord di Osiris DevWorks](https://discord.gg/BNzRegKZ7k).
