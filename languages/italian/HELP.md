# Smart Citizen — Guida rapida

## Prima configurazione

All'avvio, Smart Citizen ricarica le personalizzazioni della sessione precedente e verifica la tua installazione di Star Citizen — il programma di installazione precompila questo percorso, ma puoi modificarlo nella scheda **Configurazione**. Tutti i dati di localizzazione stock e DataForge provengono **direttamente dal tuo `Data.p4k` installato** (nessun download, nessun mirror della community), quindi estrarre una volta è un passaggio obbligatorio dopo l'installazione o dopo ogni patch del gioco.

## Modalità Semplice e Avanzata

Smart Citizen si apre in una di due modalità, e puoi passare dall'una all'altra in qualsiasi momento.

- La **modalità Semplice** è una schermata a due pulsanti: uno, **Applica Miglioramenti**, esegue l'intera catena con le impostazioni correnti (estrazione, generazione, applicazione, con un backup del file di gioco eseguito prima); l'altro passa alla **modalità Avanzata**. È la via rapida quando vuoi semplicemente applicare i miglioramenti senza dover modificare i testi a mano.
- La **modalità Avanzata** è l'applicazione completa: la tabella dei testi, i filtri, la scheda Miglioramenti, la scheda Configurazione, e tutto il resto descritto in questa guida.

Scegli la modalità predefinita durante l'installazione, oppure passa dall'una all'altra dall'interno dell'app. La modalità Semplice usa le ultime impostazioni salvate in modalità Avanzata.

## 1. Estrarre la localizzazione di base da Data.p4k

Apri la scheda **Configurazione** e clicca su **Estrai da Data.p4k**. Questo estrae il `global.ini` stock e gli XML delle entità DataForge usati dal generatore di miglioramenti — navi, componenti, armi, missioni, blueprint, ecc.

Al termine dell'estrazione, il `base.ini` estratto viene caricato automaticamente nella tabella — unito a eventuali file di miglioramenti e alle tue modifiche salvate in `user.ini`.

## 2. Modificare i testi di localizzazione

- Fai doppio clic su qualsiasi cella **Valore personalizzato** per modificare il testo.
- **Valore predefinito** — testo originale del `base.ini` estratto da `Data.p4k`.
- **Valore attuale** — il valore effettivo prima della tua modifica (base + eventuali livelli INI importati).
- **Valore personalizzato** — la tua modifica personale. Salvato automaticamente a ogni cambiamento e conservato in `<cartella dati>\<canale>\user.ini` (la cartella dati predefinita è `Documents\Smart Citizen`, e ogni canale di Star Citizen — LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW — ha le proprie modifiche isolate).
- La colonna **Stato** indica da dove proviene il valore attuale di ogni riga:
  - **Modificato** — hai modificato esplicitamente il Valore personalizzato.
  - **Migliorato** — generato automaticamente dalla pipeline dei miglioramenti (sovrapposizioni di statistiche, tag dei blueprint, ecc.).
  - **Non modificato** — testo originale del `base.ini`.
  - **Nuovo** — la chiave esiste solo nelle tue modifiche o nella pipeline dei miglioramenti, non nel `base.ini` originale.
- **Ridimensiona qualsiasi colonna** trascinando il separatore tra due intestazioni, oppure fai doppio clic su un separatore per adattare la colonna alla larghezza del suo contenuto più esteso. Le tue larghezze vengono ricordate tra un avvio e l'altro. Finché non ridimensioni nulla tu stesso, Smart Citizen adatta le colonne alla tua finestra automaticamente, così una nuova installazione si apre sempre correttamente sul proprio schermo. Per riavere quella disposizione automatica, usa **Reimposta le proporzioni della finestra** (vedi sotto).

## 3. Riquadro di anteprima

Il **riquadro di anteprima** in alto a destra mostra il rendering del testo della riga attualmente selezionata. I token delle stringhe di localizzazione del gioco vengono tradotti in HTML stilizzato, così puoi vedere all'incirca come apparirà la tua stringa in gioco:

- `\n` → interruzione di riga
- `<EM3>...</EM3>` → intestazione di sezione sottolineata
- `<EM4>...</EM4>` → enfasi in linea grassetto blu (in genere valori di statistiche)
- `~mission(Name)` → segnaposto `[Name]` in grigio (il gioco sostituisce il valore reale a runtime)

Il riquadro resta visibile in tutte le schede e riflette l'ultima riga selezionata nell'**Editor di stringhe** — utile per verificare come verrà formattata una lunga descrizione di missione o una voce di journal prima di applicare.

## 4. Categorie

Usa il filtro **Categoria** per concentrarti su un ambito specifico:

- **Ships** — Nomi e descrizioni delle navi (`vehicle_Name*`, `vehicle_Desc*`, più le varianti Wikelo/Collector).
- **Ship Items** — Scudi, generatori, raffreddatori, motori quantici, motori di salto, armi di nave, missili, bombe, torrette.
- **Missions** — Briefing di missione, testi dei contratti, descrizioni delle ricompense.
- **Gear** — Armi FPS, armature, caschi, tute, ottiche.
- **Commodities** — Beni commerciabili e materiali di crafting.
- **Journal** — Voci del journal di gioco, in stile Galactapedia.
- **Other** — Tutto il resto.

## 5. Ricerca e filtri

- Usa la **casella di ricerca** per trovare stringhe per chiave o contenuto testuale.
- Combina con i filtri **Categoria** e **Stato** (Modificato / Migliorato / Non modificato / Nuovo).
- Seleziona **Nascondi non modificati** per concentrarti solo sulle tue modifiche.
- Le **caselle di filtro per colonna** sotto ogni intestazione restringono ulteriormente la tabella.
- Clicca su un'intestazione di colonna per ordinare in base a essa. Clicca sull'intestazione **★** per portare i preferiti in cima.

## 6. Navi preferite

- Clicca sulla colonna **★** su qualsiasi riga di nave per contrassegnarla come preferita. Solo la riga del nome di una nave può essere aggiunta ai preferiti; la riga della descrizione della stessa nave non ha un comportamento equivalente in gioco, quindi lì le colonne della stella e dell'ordinamento restano vuote.
- Le navi preferite ricevono un prefisso configurabile anteposto al nome, che le porta in cima alla lista navi in gioco.
- Cambia il carattere del prefisso nella scheda **Miglioramenti** (predefinito: `*`).
- Seleziona **Solo Nomi di Navi e Veicoli** nella riga Ricerca e filtri per restringere la tabella alle sole righe dei nomi di navi e veicoli, nascondendo le descrizioni delle navi e ogni altra categoria; si abbina a **Solo Preferiti** per sfogliare esattamente le righe che puoi aggiungere ai preferiti.

## 7. Applicare le modifiche al gioco

Clicca su **Applica Miglioramenti** per scrivere le tue modifiche nell'installazione del gioco. Un backup con timestamp del `global.ini` attuale viene creato in `<cartella dati>\<canale>\backups\` prima che qualsiasi cosa venga sovrascritta.

Il colore del pulsante ti indica a che punto sei: **rosso** significa che qualcosa è cambiato dall'ultima applicazione (una modifica, una rigenerazione, un cambio di lingua o canale) e il gioco non lo ha ancora; **verde** significa che il gioco corrisponde già a ciò che è caricato, e il pulsante resta disabilitato perché non c'è nulla da rifare. La stessa convenzione rosso/verde si applica a **Genera Miglioramenti** e **Salva Modifiche Tag** nella scheda Miglioramenti. Se chiudi l'app mentre il pulsante Applica è ancora rosso, Smart Citizen ti chiede se applicare subito o uscire senza applicare, così il lavoro non applicato non può sparire silenziosamente.

Smart Citizen aggiunge anche una piccola filigrana alla stringa di versione del launcher (`Frontend_PU_Version`), aggiungendo `\nLocalizations Enhanced with Smart Citizen v{VERSION}` su una riga propria. È così che puoi confermare in gioco che il tuo loc-pack è attivo — guarda l'etichetta di versione nel menu principale di Star Citizen. La filigrana viene riscritta a ogni applicazione, quindi non si accumula mai tra le versioni.

## 8. Ripristinare un backup

Apri il menu **Altro** sulla barra degli strumenti e scegli **Ripristina Backup** per tornare a una versione precedente. Smart Citizen conserva fino a **5 backup automatici** — il più vecchio viene eliminato man mano che se ne creano di nuovi.

## 9. Cancellare la localizzazione

Apri il menu **Altro** e scegli **Cancella Localizzazione** per eliminare il `global.ini` personalizzato dalla directory di gioco, riportando il gioco al testo predefinito (vanilla). Le tue modifiche salvate in `<cartella dati>\<canale>\user.ini` restano intatte e possono essere riapplicate in qualsiasi momento.

## 10. Importare un INI

Usa **Importa INI** nella scheda **Configurazione** (disponibile anche nel menu **Altro** della barra degli strumenti) per integrare un file INI esistente nelle tue modifiche. Una finestra di risoluzione dei conflitti ti permette di decidere, chiave per chiave, se **mantenere l'attuale**, **usare l'importato**, **aggiungere in coda**, **aggiungere in testa**, oppure fornire un valore **personalizzato**.

## 11. Esportare un Loc-Pack

Apri il menu **Altro** e scegli **Esporta INI…** per raggruppare il `global.ini` attualmente applicato in un unico zip — `SmartCitizen-LocPack-{channel}-{YYYYMMDD}.zip` — che chiunque altro può inserire nella propria cartella `StarCitizen\<channel>\data\Localization\english\` per usare lo stesso loc-pack senza installare Smart Citizen. Utile per condividere preset con amici o con la tua organizzazione.

## 12. Reimpostare user.ini

Usa **Reimposta user.ini** nella scheda **Configurazione** per cancellare tutte le tue modifiche personali per il canale attivo. Una richiesta di conferma assicura che non sia un clic accidentale, e un backup automatico del `user.ini` attuale viene prima salvato in `<cartella dati>\<canale>\backups\` — così una reimpostazione è recuperabile se cambi idea.

## 13. Esportare / Importare le impostazioni

Usa **Esporta Impostazioni…** e **Importa Impostazioni…** nella scheda **Configurazione** per spostare l'intera configurazione di Smart Citizen tra PC, o per farne un backup prima di un'installazione pulita. L'esportazione raccoglie le impostazioni dell'app e le modifiche `user.ini` di ogni canale in un unico piccolo zip, incluso il percorso di installazione di Star Citizen; i percorsi specifici della macchina che non avrebbero senso su un altro PC (la cartella dati, la posizione della cache, la geometria della finestra, le larghezze delle colonne dell'editor di stringhe) vengono esclusi. Il backup registra ogni impostazione, comprese quelle lasciate al valore predefinito: ripristinarlo riporta quindi la configurazione esattamente com'era, e un'impostazione modificata *dopo* il backup torna al suo valore predefinito invece di mantenere quello più recente. L'importazione sovrappone quel backup alle impostazioni attuali e sostituisce `user.ini` per i canali che contiene: i tuoi file `user.ini` attuali vengono prima salvati in uno snapshot tramite **Ripristina user.ini**, quindi un'importazione è reversibile. Il percorso di Star Citizen viene mantenuto solo se esiste ancora sul PC su cui stai importando; altrimenti Smart Citizen lo rileva automaticamente. Dopo un'importazione Smart Citizen si riavvia per caricare le nuove impostazioni, poi propone di rigenerare e applicare i tuoi miglioramenti.

## 14. Dopo gli aggiornamenti del gioco

Quando Star Citizen si aggiorna, le tue modifiche vengono conservate in `<cartella dati>\<canale>\user.ini`. Riesegui **Estrai da Data.p4k** per recuperare i testi originali aggiornati dal gioco patchato — la tabella si ricarica automaticamente e le tue personalizzazioni si riapplicano sopra.

## 15. Cambiare lingua

Scegli una lingua dal menu a tendina **Lingua** nella scheda **Configurazione** (accanto a Canale). Il cambio modifica sia l'interfaccia dell'app sia i testi di gioco nella tabella:

- **Inglese** (predefinito) usa i testi originali estratti dal tuo `Data.p4k`.
- **Le altre lingue** scaricano il `global.ini` tradotto dalla community per quella lingua e lo sovrappongono alla base inglese, così qualsiasi stringa non coperta dalla traduzione torna all'inglese invece di risultare mancante. Il download viene messo in cache per lingua; tornare a una lingua già usata riutilizza la cache.
- **I miglioramenti restano in inglese.** I blocchi di statistiche, i tag e i dettagli di missione sono generati dai dati di gioco e mantengono la loro forma inglese sopra la prosa tradotta. Una riga mista (per esempio un nome di ruolo in francese dentro un blocco di statistiche in inglese) è un comportamento previsto, non un bug.
- **Associa File Lingua** (scheda Configurazione) ti permette di puntare una lingua verso un URL diverso per il `global.ini`, per esempio un tuo fork di una traduzione della community. Il tuo URL prevale sul valore predefinito integrato.
- Alcuni testi dell'interfaccia si aggiornano solo dopo un riavvio dell'app. I testi della tabella si ricaricano immediatamente.

L'applicazione scrive nella cartella lingua corrispondente della tua installazione di gioco e imposta `g_language` in `user.cfg`, così il gioco carica il file giusto.

Vuoi aiutare a tradurre? Lo stato delle traduzioni per lingua è tracciato in `languages/TRANSLATIONS.md` nel repository, e preferiamo di gran lunga pubblicare le tue parole piuttosto che quelle di una macchina. Contattaci su Discord.

## 16. Aggiornamenti dell'app

Smart Citizen controlla la presenza di una nuova versione a ogni avvio. Quando ne è disponibile una, le note di rilascio appaiono in una finestra scorrevole con due opzioni:

- **Aggiorna Ora** scarica il nuovo programma di installazione, Windows chiede l'autorizzazione, e Smart Citizen si chiude, si aggiorna e si riapre sulla nuova versione. Le tue modifiche, i backup e le impostazioni restano intatti.
- **Più Tardi** ti mantiene sulla versione attuale; ti verrà richiesto di nuovo al prossimo avvio.

Puoi anche controllare manualmente in qualsiasi momento con **Controlla Aggiornamenti** nella scheda Configurazione. Le build portable mostrano invece un pulsante **Apri Pagina Rilascio**, dato che non c'è un installer da eseguire: scarica il nuovo zip e decomprimilo sopra la cartella precedente.

## Scheda Miglioramenti

- Attiva le sovrapposizioni di statistiche che aggiungono valori numerici alle descrizioni — velocità SCM, HP degli scudi, DPS, capacità di carico, statistiche del fascio del laser di minaggio (Fracture / Extraction), tassi degli strumenti di recupero portatili, pool di blueprint, XP di missione, e altro. L'XP di missione indica anche la voce di reputazione che alimenta (es.: `750 XP (Hauling)`), i contratti di scan/minaggio di Battaglia portano un tag `[RS ####]` con la signature di risorsa base del minerale bersaglio, e il journal Mining Compendium elenca la RS base di ogni minerale accanto ai suoi luoghi di estrazione.
- **Consumabili Medici** — aggiunge una riga di effetto in linguaggio semplice alle penne CureLife base (MedPen, OxyPen, AdrenaPen e simili), così la descrizione dice cosa fa realmente la penna invece di limitarsi al suo testo di ambientazione.
- **Mostra statistiche sopra la descrizione** — sposta il blocco di statistiche in cima alla descrizione invece che in fondo, così i numeri sono la prima cosa che leggi in gioco.
- **Mostra le Firme delle Risorse (RS) accanto ai nomi dei minerali**: aggiunge la Firma delle Risorse di base di ogni minerale estraibile al suo nome visualizzato (es. "Aluminium (RS 4285)"), così compare ovunque il gioco mostri quel nome, incluso il tracker delle missioni. Indipendente dalla riga Firme delle Risorse nei Campi Dettagli Missione più sotto.
- Abilita o disabilita ogni categoria di miglioramento in modo indipendente.
- Configura il carattere del prefisso per le navi preferite.
- **Il possesso dei blueprint** si è spostato nella propria scheda **Tracciatore Blueprint**; vedi la sezione successiva.
- **Generatore di Tag** — personalizza i tag tra parentesi applicati ai nomi di componenti, missili, armi di nave e commodity. Riordina gli elementi con ▲/▼, disattiva singoli elementi, cambia la lunghezza dell'abbreviazione (`M` / `MIL` / `Military`), scegli il separatore (nessuno, trattino, spazio, ecc.) e le parentesi (quadre, tonde, nessuna, ecc.), e scegli se il tag appare prima o dopo il nome. I componenti hanno anche un elemento **Tipo** opzionale (Shield, Cooler, Power Plant, ecc.) — disattivato per impostazione predefinita. Le commodity hanno gli elementi **Etichetta**, **Utilizzo** (in cosa confluiscono i materiali di crafting di una commodity) e **Collezione**, tutti disattivati per impostazione predefinita; attiva quelli che vuoi dal Generatore di Tag. Clicca su **Salva Modifiche Tag** per salvare e rigenerare. (**Genera Miglioramenti** salva anche prima ogni modifica ai tag in sospeso, così una modifica non salvata non può sfuggire a una rigenerazione.)
- **Titoli di Missione** (scheda Generatore di Tag) — fai precedere ai titoli delle missioni di trasporto il loro percorso. Scegli il posizionamento (Anteponi, Aggiungi in coda, o Sostituisci il titolo), la freccia del percorso (`>`, `->`, `to`, o le forme codificate `->-`/`->=`/`=>-`/`=>=` che mostrano una singola destinazione contro più destinazioni per lato), il separatore del titolo, e quanto mostrare della località (indirizzo completo per impostazione predefinita; il nome breve può non essere visualizzato in rare missioni), con un'anteprima dal vivo. Un trasporto si legge come `Area18 > Lorville - <titolo originale>`, così vedi il lavoro a colpo d'occhio nella lista contratti, e i trasporti multi-tappa elencano le loro destinazioni (`Area18 > Lorville, New Babbage`). Due opzioni indipendenti riducono il titolo originale: **Abbrevia titoli originali** applica abbreviazioni di frasi selezionate (es. "Opportunity for Independent Cargo Hauler" → "Intro", "Local Shipment Route" → "Route", più la gestione della Ling Family e dei prefissi di rango), e **Abbrevia dimensioni di carico** abbrevia le dimensioni di carico ("Extra Small" → "XS"). Caselle di controllo individuali offrono un controllo più fine — rimuovere del tutto "Cargo" o "Haul", eliminare "Rank", oppure sottolineare i trasporti "Direct" per enfasi — così il percorso e i tag rientrano anche nei titoli lunghi. Le caselle di controllo **Tag Generali** nella stessa pagina mostrano o nascondono i tag riservati ai titoli: la ricompensa di reputazione, il tag blueprint, `[ACE]`, il tag `[RS ####]` di Battaglia e il nome del percorso di reputazione. Il tag blueprint appare come `[BP]` quando ogni versione di una missione ricompensa con un blueprint, e come `[BP?]` quando non è garantito (solo alcune versioni ne includono uno, oppure i dati di gioco indicano la ricompensa come un tiro a probabilità).
- **Etichette di Missione** — personalizza le intestazioni di sezione usate nei blocchi di miglioramento delle missioni (MISSION DETAILS, POTENTIAL BLUEPRINTS, ITEM REWARDS, BLUEPRINT DATA), l'etichetta XP mostrata sulle missioni senza un rango di reputazione specifico (predefinito "Rep"), e il tag di enfasi (EM3 = sottolineato, EM4 = colore) usato per le intestazioni.
- **Campi Dettagli Missione** — mostra o nascondi individualmente ogni riga del blocco MISSION DETAILS (tipo di missione, difficoltà, spawn, reputazione, blueprint, pilota asso e firme delle risorse), così le tue descrizioni di missione riportano solo i dati che ti interessano. **Firme delle Risorse** aggiunge ai contratti di scansione/estrazione di Recco Battaglia un riepilogo che elenca la progressione completa dei valori RS di ogni minerale bersaglio, separato dal tag `[RS ####]` nel titolo della missione e dall'annotazione sul nome del minerale descritta sopra.
- Clicca su **Genera Miglioramenti** per estrarre i dati DataForge da `Data.p4k` e ricostruire i file INI dei miglioramenti. I patch dichiarativi sotto `patches/` vengono riapplicati in modo idempotente a ogni rigenerazione, così i bug noti nei dati di CIG restano corretti senza dover attendere una patch di gioco.

## Scheda Tracciatore Blueprint

Tieni traccia dei blueprint di crafting che possiedi già, e vedi il riscontro in gioco: gli oggetti posseduti ricevono un tag blu `[Owned]` nelle liste POTENTIAL BLUEPRINTS delle missioni, così un elenco contratti ti dice a colpo d'occhio cosa ti resta ancora da procurarti.

- **Due liste, una navetta.** I blueprint disponibili a sinistra, la tua collezione posseduta a destra. Seleziona gli elementi e spostali con i pulsanti freccia. La collezione posseduta persiste tra i riavvii.
- **Trova le cose in fretta.** Una casella di ricerca restringe entrambe le liste, e i filtri **Mission / Type / Class / Size / Grade** riducono la lista dei disponibili in base a dove un blueprint viene droppato e a che tipo di oggetto appartiene (Armor, Ammo, FPS Weapon, Ship Item, e così via).
- **Scansiona i Log per i Blueprint Posseduti** riempie automaticamente la collezione posseduta: legge i file di log di Star Citizen per individuare i blueprint ricevuti in gioco e li contrassegna come posseduti. Vengono importati solo i blueprint ricevuti dall'ultima scansione, quindi rieseguirla in qualsiasi momento è economico. La scansione richiede che il percorso di installazione di Star Citizen sia impostato nella scheda Configurazione.
- **Scansiona anche LIVE/HOTFIX (quello non attivo)** controlla anche quello dei due che non è il tuo canale attuale, dato che condividono la stessa progressione dell'account — un blueprint ottenuto su LIVE compare nei log di HOTFIX e viceversa. Attivato per impostazione predefinita. PTU, EPTU e TECH-PREVIEW sono build di test separate con una propria progressione e non vengono mai scansionate, indipendentemente da questa opzione.
- **Riesegui la scansione di tutti i log (ignora l'ultima scansione)**: forza la prossima scansione a rileggere ogni voce di log da zero invece delle sole novità dall'ultima scansione. Usala se la tua collezione posseduta sembra errata e una scansione normale non la corregge. Si deseleziona da sola al termine della scansione.
- **Esporta Blueprint Posseduti… / Importa Blueprint Posseduti…**: spostano la tua lista dei posseduti tra PC, o la condividono con un amico. L'esportazione scrive tutto ciò che possiedi in un file JSON o CSV; l'importazione ne rilegge uno e aggiunge ciò che trova, senza mai rimuovere nulla che già possiedi. Anche le esportazioni da scmdb.net si importano. Il riepilogo dell'importazione dice quanti blueprint erano nuovi ed elenca gli eventuali nomi nel file che Smart Citizen non traccia.
- **Applica Tag Posseduti** reintegra i tag `[Owned]` nei tuoi testi caricati dopo che hai modificato la collezione posseduta. Come gli altri pulsanti di azione, diventa **rosso** quando la tua lista posseduti ha modifiche che la tabella non ha ancora recepito, e **verde** quando tutto corrisponde.
- La colonna **Owned** della tabella dei testi mostra ancora una stella e ordina prima i posseduti, ma ora è di sola lettura; il possesso si gestisce da questa scheda.

## Scheda Configurazione

- **Aspetto** — scegli il tema dell'app (vedi sotto).
- **Installazione di Star Citizen** — percorso della tua directory LIVE; rilevato automaticamente all'installazione, modificabile qui. Il menu a tendina **Canale** sceglie quale canale l'app legge e scrive, e il menu a tendina **Lingua** cambia i testi dell'app e del gioco (vedi *Cambiare lingua* sopra).
- **Dati Smart Citizen** — cartella per `user.ini`, cache, estrazione DataForge, INI di miglioramenti generati e backup. Predefinita su `Documents\Smart Citizen`; spostala fuori da OneDrive se l'estrazione o la pulizia della cache sono lente.
- **Localizzazione di Base (Estrazione P4K)** — clicca su **Estrai da Data.p4k** per estrarre la localizzazione originale e i dati delle entità DataForge direttamente dal tuo gioco installato. È l'unica fonte per i testi di base e i dati dei miglioramenti.
- **Importa INI** — integra un file INI esistente nelle tue modifiche tramite la finestra di risoluzione dei conflitti.
- **Reimposta user.ini** — cancella tutte le tue modifiche personali per il canale attivo. Richiede conferma ed esegue automaticamente il backup del `user.ini` attuale prima di cancellarlo.
- **Ripristina user.ini** — riporta le tue modifiche personali a uno snapshot precedente. Smart Citizen mantiene backup rotanti di `user.ini` (fino a 5, eseguiti automaticamente prima di ogni modifica), così se un'importazione o una modifica va storta puoi scegliere una versione precedente e recuperare i tuoi testi. Il ripristino stesso è reversibile: il file attuale viene prima salvato in uno snapshot.
- **Esporta Impostazioni… / Importa Impostazioni…**: salva l'intera configurazione (impostazioni più lo `user.ini` di ogni canale) in un unico piccolo zip, oppure ripristinala su un nuovo PC. Vedi *Esportare / Importare le impostazioni* sopra.

## Scheda Log

- Log dell'applicazione in tempo reale.
- Filtra per livello di log, scorrimento automatico alle voci più recenti, ed **Esporta** il log per la risoluzione dei problemi o le segnalazioni di bug.

## Temi

Scegli un tema nella sezione **scheda Configurazione → Aspetto**:

- **Predefinito** — SCLE, un tema cyber blu notte ispirato all'interfaccia mobiGlas di Star Citizen.
- **Chiaro / Scuro** — temi classici dell'interfaccia.
- **ODW** — firma Osiris DevWorks, antracite blu notte con oro antico.

## Disposizione della finestra

Smart Citizen ricorda le dimensioni della finestra, la disposizione dell'editor di stringhe agganciato e le larghezze delle colonne tra un avvio e l'altro. Ogni scheda scorre il proprio contenuto, quindi puoi rimpicciolire la finestra quanto vuoi e raggiungere ogni controllo scorrendo, invece di vederli compressi o tagliati.

Se la disposizione finisce in uno stato scomodo (una colonna ridotta a una striscia, o una dimensione della finestra che non si adatta più al tuo schermo), usa **Altro → Reimposta le proporzioni della finestra**. Ripristina le dimensioni della finestra, la disposizione dei pannelli e le larghezze delle colonne ai valori predefiniti. Le tue impostazioni, le tue modifiche e i dati di localizzazione non vengono toccati.

## Barra di stato

Mostra il conteggio delle voci caricate / modificate e lo stato di qualsiasi processo in background in esecuzione (estrazione, generazione, applicazione).

## Tour guidato

Clicca sul pulsante **Tutorial** nella barra degli strumenti in qualsiasi momento per rivedere il tour guidato — una spiegazione passo passo del flusso di lavoro principale con indicazioni a schermo che puntano a ogni controllo. Il tour parte anche automaticamente al primo avvio di una nuova versione, così un'installazione nuova non parte mai a freddo. Premi **Salta** in qualsiasi momento per chiuderlo.

## Scheda FAQ

La scheda **FAQ** risponde alle domande che riceviamo più spesso, direttamente dentro l'app — quali file tocca Smart Citizen, se si rischia il ban usandolo, perché Windows segnala il programma di installazione, e come annullare le tue modifiche. Controlla lì per prima cosa; se la tua domanda non è coperta, il Discord è a un clic di distanza.

## Scorciatoie da tastiera

- **Ctrl+Shift+C** — Copia le righe filtrate negli appunti (formato chiave=valore).

## Risoluzione dei problemi

- **Tabella vuota** — Assicurati che **Estrai da Data.p4k** sia terminato e che il ricaricamento post-estrazione sia completo, poi controlla la **scheda Log** per errori di parsing.
- **Miglioramenti vuoti o oggetti mancanti** — Esegui **Genera Miglioramenti** dalla scheda Miglioramenti; richiede una cache DataForge (clicca prima su **Estrai da Data.p4k** se non l'hai ancora fatto).
- **Applica Miglioramenti fallisce** — Verifica il percorso di installazione di Star Citizen nella **scheda Configurazione** e che il gioco non sia in esecuzione.
- **L'estrazione dice che Data.p4k è bloccato**: il launcher RSI sta scaricando o verificando un aggiornamento. Attendi che finisca (oppure chiudi il launcher), poi clicca di nuovo su **Estrai da Data.p4k**.
- **Dati obsoleti dopo un aggiornamento del gioco** — Riesegui **Estrai da Data.p4k**, poi rigenera i miglioramenti.

## Problemi noti

Alcune anomalie nei testi delle missioni hanno origine nei dati stessi di Star Citizen — un riferimento a loc-key errato in un record di contratto, o una ricompensa in blueprint i cui dati non rimandano a un nome visualizzato reale. Il gioco legge i contratti e le ricompense in blueprint dal proprio `Data.p4k` a runtime, quindi Smart Citizen non può correggerli alla fonte; può solo correggere il *testo* che genera e applica. Dove possibile, aggiriamo questi problemi a livello di dati o di generazione, così il risultato in gioco appare comunque corretto.

- **Dossier Jorrit — "Updated Power Usage Data" mostra il testo di Energy Anomaly** — CIG Issue Council [STARC-176797](https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues/STARC-176797). Il contratto `Hockrow_FacilityDelve_P2M4-Stanton4_Repeat` di CIG punta il proprio parametro `Description` a `@Hockrow_FacilityDelve_P2M1_Repeat_desc` invece che al proprio `P2M4_Repeat_desc`, quindi i giocatori vedono in gioco il testo di ambientazione di Energy Anomaly di P2M1 per una missione intitolata "Power Usage Data". Smart Citizen aggira questo problema in due passaggi, entrambi dichiarati in `patches/contracts/contractgenerator/mercenary_guild/hockrowagency/hockrowagency_facilitydelve.patch.json`:
  1. Una modifica XML di DataForge affinché il nostro generatore di miglioramenti assegni il pool di blueprint P2M4 corretto (Corbel Smolder, Geist Rogue/Whiteout) a `P2M4_Repeat_desc` invece di ricadere su quello di P2M1.
  2. Un espediente sulla stringa di localizzazione che aggiunge il contenuto completo di `P2M4_Repeat_desc` (il suo testo di ambientazione più il proprio pool di blueprint) in coda a `P2M1_Repeat_desc`, separato da un divisore etichettato. Poiché il gioco legge il puntatore bacato e cerca `P2M1_Repeat_desc` per entrambi i contratti, il contratto P2M4 ora mostra il contenuto previsto. I giocatori di P2M1 vedono il blocco P2M4 come un'appendice etichettata dopo la propria descrizione — più affollato, ma entrambi i contratti ora mostrano il pool di blueprint corretto e il testo di ambientazione corretto.

  Quando CIG correggerà STARC-176797, l'intero file di patch potrà essere eliminato e la rigenerazione successiva produrrà di nuovo descrizioni pulite e separate.

- **Missioni di rifornimento che mostrano nomi di ugelli corrotti** (es. "Nozzle Fuelgiver Grin Nozzlefast" invece di "Norfield") nella lista POTENTIAL BLUEPRINTS di una missione. Le ricompense in blueprint degli ugelli di rifornimento non rimandano a un nome di entità risolvibile nei dati di CIG come fanno gli altri oggetti fabbricabili, quindi il nostro generatore di miglioramenti ricadeva su una versione "de-slugificata" del nome di file interno invece del vero nome del prodotto. Corretto per tutte le 8 varianti note di ugelli di rifornimento (Marlin, Lindstrom, Bendix, Torrez, Ezra, Norfield, Harkin, RN-7s) tramite una correzione con nomi noti in `scripts/generate_enhancements_ini.py`; riesegui **Genera Miglioramenti** e **Applica al Gioco** per applicare la correzione alle missioni già viste.

## Feedback, bug e voto delle funzionalità

- **Segnala bug, condividi configurazioni personalizzate e vota le prossime funzionalità** nel canale Discord dedicato a Smart Citizen: [Osiris DevWorks Discord — #smart-citizen feedback & voting](https://discord.com/channels/1438175448420057323/1472394204347895890) (richiede prima l'iscrizione al server Discord di Osiris DevWorks — [invito](https://discord.gg/BNzRegKZ7k)). La priorità delle funzionalità è guidata dalle reazioni/voti in quel canale, quindi più richiesta ha una proposta, prima verrà realizzata.
- Quando segnali un bug, allega il log (scheda Log → **Esporta**) e indica la versione di Star Citizen che stai usando, così possiamo distinguere i problemi originali dai cambiamenti a monte.
