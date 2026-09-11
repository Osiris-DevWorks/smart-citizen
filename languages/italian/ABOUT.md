# Smart Citizen

*Smarter Strings for Star Citizen*

## Informazioni su questo progetto

**Smart Citizen** è uno strumento potente e facile da usare che permette ai giocatori di Star Citizen di personalizzare i testi di localizzazione del proprio gioco. Carica, modifica e applica le modifiche di localizzazione con persistenza completa, backup automatici e supporto continuo per gli aggiornamenti del gioco.

Sviluppato da **Osiris DevWorks**, uno studio di sviluppo individuale dedicato alla creazione di strumenti utili per la community dei giocatori.

## La promessa di Osiris DevWorks

Tutti gli strumenti Osiris DevWorks saranno **completamente gratuiti** oppure avranno un **livello gratuito**. Crediamo nella creazione di valore per i giocatori senza paywall o abbonamenti obbligatori.

## Team ODW

- **Osiris_x**
- **Tichro**

## Collaboratori

Grazie a chi ha contribuito al codice di Smart Citizen:

- **Stealrull**
- **Ishikudeska**
- **jonigirl**
- **Coerwyn**
- **denis-coach** (h0use)
- **scubamount**
- **hkstrongside**
- **odw-okano**

## Traduttori

Grazie a chi ha tradotto l'interfaccia di Smart Citizen:

- **Akwa** (Français)
- **Nxzzin** (Português brasileiro)
- **Thord82** (Español)

## Ringraziamenti

Grazie ai tester che hanno contribuito a plasmare Smart Citizen con i loro feedback:

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

### Sostenitori

Grazie a chi ha sostenuto il progetto finanziariamente: i tuoi contributi aiutano a mantenere Smart Citizen gratuito per tutti:

- **Dimwit the Wise**

Smart Citizen include anche strumenti di terze parti a monte:

- [**Osiris-DevWorks/odw-fast-unp4k**](https://github.com/Osiris-DevWorks/odw-fast-unp4k) — `unp4k.exe` e `unforge.exe`, usati per decomprimere `Data.p4k` e convertire DataForge in XML. Questo è il nostro fork del progetto originale [**dolkensp/unp4k**](https://github.com/dolkensp/unp4k), con estrazione parallela e altri miglioramenti alle prestazioni.

I testi di gioco in lingue diverse dall'inglese sono traduzioni della community:

- [**Dymerz/StarCitizen-Localization**](https://github.com/Dymerz/StarCitizen-Localization) — le traduzioni di `global.ini` mantenute dalla community che alimentano le opzioni di lingua francese, portoghese brasiliana, italiana e turca. I loro traduttori fanno il vero lavoro qui; noi ci limitiamo a distribuirlo.
- [**Thord82/Star_citizen_ES**](https://github.com/Thord82/Star_citizen_ES): la traduzione di `global.ini` mantenuta dalla community che alimenta l'opzione di lingua spagnola.
- [**stdblue/StarCitizenJapaneseResources**](https://github.com/stdblue/StarCitizenJapaneseResources): la traduzione di `global.ini` mantenuta dalla community che alimenta l'opzione di lingua giapponese.
- [**42Kit**](https://ini.42kit.com/): la traduzione di `global.ini` mantenuta dalla community che alimenta l'opzione di lingua cinese.
- [**rjcncpt/StarCitizen-Deutsch-INI**](https://github.com/rjcncpt/StarCitizen-Deutsch-INI): la traduzione di `global.ini` mantenuta dalla community che alimenta l'opzione di lingua tedesca.

## Caratteristiche principali

### 🎯 Funzionalità principali
- **Carica e modifica**: carica il `global.ini` della tua installazione di Star Citizen e personalizza i testi in una vista a tabella intuitiva
- **Supporto multi-canale**: LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW hanno ciascuno il proprio `user.ini`, cache, backup ed estrazione DataForge isolati — cambia canale dalla scheda Configurazione senza riavviare
- **Supporto multilingua**: passa da una lingua all'altra per l'app e i testi di gioco tra inglese, francese, spagnolo, portoghese brasiliano, giapponese, cinese, italiano, tedesco e turco dalla scheda Configurazione. Le lingue diverse dall'inglese sovrappongono un `global.ini` tradotto dalla community alla base inglese, con fallback in inglese per tutto ciò che non è tradotto. Altre lingue saranno rese disponibili man mano che arriveranno traduzioni dalla community (vedi `languages/TRANSLATIONS.md`)
- **Contratti di missione**: modifica il testo dei contratti di missione e dei briefing dalla categoria Missions dedicata
- **Filtraggio intelligente**: cerca testi, filtra per categoria (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other) o per stato di modifica
- **Filtri per colonna**: digita direttamente nelle caselle di filtro sotto ogni intestazione di colonna per una ricerca dettagliata
- **Pannello di anteprima live**: un pannello laterale visualizza il testo della riga selezionata con i loc-token del gioco (interruzioni di riga, enfasi EM3/EM4, segnaposto di missione) tradotti in HTML formattato, così vedi grosso modo come apparirà la stringa in gioco
- **Pannello laterale dell'editor**: un'area di modifica attivabile dalla barra degli strumenti, ridimensionabile trascinando e disancorabile, per modificare valori lunghi (voci di diario, briefing di missione, descrizioni di navi) con pulsanti Sottolinea/Evidenzia e sincronizzazione live tra i pannelli
- **Applicazione sicura**: l'applicazione scrive su `global.ini` creando prima un backup automatico con timestamp, convalida l'output rispetto all'insieme di chiavi originali e torna automaticamente indietro in caso di incongruenze
- **Ripristino backup**: conserva fino a 5 versioni di backup per canale — annulla le modifiche in qualsiasi momento con un clic
- **Cancella localizzazione**: riporta il tuo gioco al testo originale senza perdere le tue modifiche salvate
- **Importa INI**: importa un file INI esistente e risolvi i conflitti chiave per chiave con la finestra di dialogo integrata
- **Modalità Semplice e Avanzata**: si apre su una schermata Semplice a due pulsanti (uno applica i miglioramenti con le tue impostazioni salvate, l'altro passa alla modalità Avanzata), oppure usa l'interfaccia Avanzata completa (tabella, filtri, Miglioramenti, Configurazione) ogni volta che vuoi modificare a mano. Scegli la modalità predefinita all'installazione e passa dall'una all'altra all'interno dell'app
- **Scheda FAQ**: le domande che riceviamo più spesso, con risposta direttamente nell'app — quali file vengono toccati, il rischio di ban, l'avviso di Windows sull'app non riconosciuta e come annullare le modifiche
- **Finestra e colonne flessibili**: ridimensiona la finestra come preferisci — ogni scheda scorre il proprio contenuto invece di comprimere o tagliare i controlli. Le colonne dell'Editor Stringhe sono ridimensionabili trascinandole (doppio clic su un separatore per adattarla al contenuto) e le larghezze e la disposizione della finestra vengono mantenute tra un avvio e l'altro, con **Altro → Reimposta le proporzioni della finestra** per ripristinare i valori predefiniti
- **Tutorial guidato**: un tour con indicatori guida i nuovi utenti attraverso il flusso di lavoro al primo avvio di ogni versione, rigiocabile in qualsiasi momento dal pulsante Tutorial

### 🔄 Origine dati e persistenza
- **Origine da Data.p4k**: tutti i dati di localizzazione originali e i dati delle entità DataForge vengono decompressi direttamente dal tuo `Data.p4k` installato — nessun download, nessun mirror della community, sempre allineato alla tua versione effettiva del gioco
- **Modifiche persistenti**: le tue personalizzazioni vengono salvate automaticamente e ricaricate a ogni sessione
- **Migrazione senza interruzioni**: quando Star Citizen si aggiorna, riestrai dal `Data.p4k` aggiornato — le tue modifiche salvate si riapplicano automaticamente ai nuovi testi di base
- **Interfaccia pulita**: vista a tabella ad alte prestazioni con filtri, modifica in linea, scorciatoie da tastiera e un'interfaccia moderna

### 📊 Miglioramenti
- **Statistiche navi**: velocità SCM, carburante idrogeno/quantico, capacità di carico, dotazione completa di armi e moltiplicatori di corazza (fisica / energetica / distorsione / termica) aggiunti alle descrizioni delle navi
- **Statistiche componenti**: PV scudo, assorbimento energetico, tasso di raffreddamento, rigenerazione e statistiche simili per scudi, raffreddatori, generatori, motori quantici e radar — con tag del nome in stile `[MIL-S2-A]` come impostazione predefinita (completamente personalizzabili nel Generatore di Tag)
- **Statistiche armi**: DPS, cadenza di fuoco, gittata e danno su cannoni e torrette da nave dalla S1 fino alla capital. Le armi da nave ricevono un tag danno+dimensione in stile `[E-S2]`, i missili `[IR-S1] Arrester III` e le bombe `[S5] 500SCB Cluster`
- **Annotazioni missione**: tag di ricompensa blueprint `[BP]` / `[BP?]` sui titoli, oltre a blocchi strutturati *MISSION DETAILS*, *POTENTIAL BLUEPRINTS* e *ITEM REWARDS* nelle descrizioni. Le righe di livello di reputazione mostrano i nomi effettivi dei ranghi (Rookie, Jr. Contractor, ecc.) invece di una numerazione generica. L'XP di missione indica quale percorso di reputazione alimenta, e i titoli di scansione/estrazione di Battaglia riportano tag di firma di risorsa `[RS ####]`, affiancati da un riepilogo "Resource Signatures" in MISSION DETAILS per ogni minerale bersaglio e da un'annotazione sul nome del minerale mostrata ovunque il gioco visualizzi quel nome, incluso il tracker delle missioni (due interruttori indipendenti, entrambi attivi per impostazione predefinita)
- **Riferimenti incrociati nel diario**: le voci del Mining Compendium ottengono riferimenti incrociati di crafting e la firma di risorsa base di ogni minerale; le commodity usate nel crafting ottengono un tag del nome personalizzabile `[CF]` e un elenco di ogni blueprint che le richiede
- **Effetti dei consumabili medici**: le penne CureLife di base (MedPen, OxyPen, AdrenaPen e simili) ottengono una riga di effetto in linguaggio semplice, così la descrizione dice cosa fa la penna invece di limitarsi al suo testo di ambientazione
- **Navi preferite**: metti in evidenza una nave con una stella per anteporre un prefisso configurabile (predefinito `*`) in modo che i preferiti si posizionino in cima al terminale ASOP in gioco
- **Generatore di Tag**: personalizza i tag tra parentesi quadre su componenti, missili, armi da nave e commodity — riordina gli elementi, cambia la lunghezza dell'abbreviazione (M / MIL / Military), scegli separatori e parentesi, oppure posiziona il tag dopo il nome invece che prima. I componenti hanno un elemento Tipo opzionale (Scudo, Raffreddatore, ecc.); le commodity hanno un elemento Utilizzo che mostra a cosa servono i loro materiali di crafting
- **Titoli di missione**: fai precedere i titoli di trasporto dal loro percorso (es. `Area18 > Lorville`) — posizionamento, freccia, separatore e livello di dettaglio della località configurabili, più un accorciamento opzionale dei titoli originali, con anteprima live
- **Statistiche sopra o sotto**: scegli se il blocco statistiche si trova in cima o in fondo alla descrizione
- **Tracciatore Blueprint**: una scheda dedicata per contrassegnare i blueprint di crafting che possiedi già. Sposta gli elementi tra Disponibili e Posseduti, filtra per Missione / Tipo / Classe / Dimensione / Grado, e gli oggetti posseduti ottengono un tag blu `[Owned]` negli elenchi di blueprint delle missioni. **Analizza i log per i blueprint posseduti** popola automaticamente la proprietà dai tuoi file di log di Star Citizen, importando solo le novità dall'ultima analisi, ed **Esporta / Importa blueprint posseduti** sposta la lista dei posseduti tra PC (JSON o CSV; le importazioni si limitano ad aggiungere, e funzionano anche le esportazioni da scmdb.net)
- **Etichette di missione**: rinomina le intestazioni di sezione (MISSION DETAILS, POTENTIAL BLUEPRINTS, ecc.), l'etichetta dell'XP e il tag di enfasi usato per le intestazioni
- **Patch dichiarative per i bug di dati CIG**: un sistema di patch applica correzioni a bug DataForge noti al momento dell'estrazione, così il testo in gioco risulta corretto senza dover attendere CIG
- **Categorie selettive**: attiva o disattiva ogni categoria di miglioramento in modo indipendente dalla scheda Miglioramenti

### 🎨 Temi
- **Predefinito**: tema cyber blu notte ispirato all'interfaccia mobiGlas di Star Citizen
- **Chiaro / Scuro**: temi di interfaccia classici
- **ODW**: tema distintivo di Osiris DevWorks — blu antracite con oro antico

### 🛡️ Gestione dati
- **Backup automatici**: backup con timestamp creati prima di applicare le modifiche al tuo gioco (fino a 5 per canale)
- **Persistenza tramite registro**: tutti i percorsi e le preferenze sono salvati in modo sicuro nel Registro di Windows
- **Archiviazione dati configurabile**: le tue modifiche personalizzate sono archiviate sotto `<cartella dati>\<canale>\` (predefinita `Documents\Smart Citizen`, un sottoalbero isolato per ogni canale di Star Citizen) per una persistenza sicura tra le sessioni
- **Backup delle impostazioni**: esporta l'intera configurazione (preferenze, configurazioni dei tag e le sostituzioni di stringhe di ogni canale) in un unico piccolo zip, poi importalo su un nuovo PC o dopo aver estratto una nuova versione portable. Le importazioni salvano prima uno snapshot dei tuoi file attuali, quindi sono reversibili
- **Visualizzatore log integrato**: log dell'applicazione in tempo reale con filtro per livello, scorrimento automatico e un pulsante di esportazione per le segnalazioni di bug
- **Aggiornamento automatico**: Smart Citizen controlla le GitHub Releases all'avvio e mostra le note di rilascio direttamente nell'app; un clic (più una richiesta di autorizzazione di Windows) scarica l'aggiornamento, lo installa e riapre l'app

## Avvio rapido

1. **Primo avvio**: l'app rileva automaticamente la tua installazione di Star Citizen (modificabile nella scheda **Configurazione**)
2. **Estrai**: fai clic su **Estrai da Data.p4k** nella scheda Configurazione per decomprimere la localizzazione originale e i dati delle entità DataForge dal tuo gioco installato — i testi si caricano automaticamente nella tabella al termine dell'estrazione
3. **Modifica i testi**: usa gli strumenti di ricerca e filtro, poi fai doppio clic su qualsiasi cella Valore personalizzato per personalizzare il testo
4. **Applica**: fai clic su **Applica Miglioramenti** — le tue modifiche vengono salvate e applicate con un backup automatico
5. **Miglioramenti (opzionale)**: apri la scheda Miglioramenti per attivare le sovrapposizioni di statistiche per navi, componenti, armi e ricompense di missione
6. **Dopo gli aggiornamenti del gioco**: riesegui Estrai da Data.p4k — le tue modifiche si riapplicano automaticamente

## Community e supporto

### Unisciti a noi
- 💬 [Community Discord](https://discord.gg/BNzRegKZ7k) - Ottieni supporto, condividi configurazioni, richiedi funzionalità
- 🐛 [Feedback, bug e votazione funzionalità di Smart Citizen](https://discord.com/channels/1438175448420057323/1472394204347895890) - Canale dedicato per segnalazioni di bug, feedback e votazioni sulle prossime funzionalità (unisciti prima al server tramite l'invito qui sopra)

### Video guide
- 🎥 [Star Citizen Hides Important Mission Info – This Tool Shows It In-Game & More!](https://www.youtube.com/watch?v=Xo1t404gsgs) di **Karolinger** - una panoramica della community sulle funzionalità di Smart Citizen

### Sostieni questo progetto
Smart Citizen è completamente gratuito. Se lo trovi utile:
- 💳 [Dona tramite PayPal](https://www.paypal.com/ncp/payment/YAWXHMGZH8T76)
- 💰 [Dona tramite Venmo](https://venmo.com/u/Amr-Abouelleil)

## Altri strumenti di Osiris DevWorks

- **[Battlestations](https://battlestations.osiris-devworks.com/)** - Gestisci e condividi le configurazioni di battlestation dell'hangar di Star Citizen
- **[SC Profile Editor](https://github.com/Osiris-DevWorks/sc-profile-editor)** - Importa, modifica ed esporta i profili di controllo di Star Citizen
- **[Extended AFK](https://github.com/Osiris-RK/extended-afk)** - Strumento AFK per evitare le disconnessioni per inattività

## Realizzato con

Realizzato con **PyQt6** e ispirato al lavoro di localizzazione della community di Star Citizen.

**GitHub**: https://github.com/Osiris-DevWorks/smart-citizen

## Licenza e note legali

Smart Citizen è distribuito sotto **Apache License, Version 2.0**.

Consulta la scheda **Legale** per il riepilogo completo della licenza, le attribuzioni dei software di terze parti inclusi (unp4k / PyQt6 / lxml), i riconoscimenti "Made by the Community" di Cloud Imperium, l'informativa sulla privacy e sulla gestione dei dati, e la dichiarazione sull'uso dell'IA.
