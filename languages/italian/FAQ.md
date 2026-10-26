# Domande frequenti

Risposte rapide alle domande più comuni. Se la tua domanda non è qui, clicca sul link **Feedback** nel footer e chiedici su Discord.

## Come annullo le modifiche apportate da Smart Citizen?

Facilmente, e in qualsiasi momento. Smart Citizen non modifica mai i file originali del gioco direttamente, quindi tornare alla versione vanilla è questione di un clic:

- **Barra degli strumenti → Altro → Cancella localizzazione** elimina il `global.ini` personalizzato scritto da Smart Citizen. Il gioco torna immediatamente al suo testo predefinito. Le tue modifiche non vengono perse: restano salvate nell'app e puoi riapplicarle quando vuoi.
- Preferisci tornare indietro di una sola versione invece che azzerare tutto? **Barra degli strumenti → Altro → Ripristina backup** riporta il file di gioco a un backup con timestamp (Smart Citizen conserva gli ultimi 5 e ne crea uno nuovo ogni volta che applichi le modifiche).

Le tue modifiche personali si trovano in `user.ini`, nella cartella dati di Smart Citizen, separata dal gioco: cancellare il file di gioco non le tocca mai.

## Rischio il ban per aver usato Smart Citizen?

Smart Citizen modifica solo il testo di localizzazione (le parole che il gioco ti mostra): non tocca la logica di gioco, non ti dà alcun vantaggio e non comunica con i server di CIG. Le nostre modifiche **dovrebbero** essere tranquille.

L'**Overlay di Smart Citizen** opzionale (scheda Overlay) funziona allo stesso modo, senza mettere mano al gioco. Disegna normali finestre sopra il gioco, legge i pixel del tuo schermo come fa uno strumento per screenshot e legge il file `Game.log` del gioco. Non si inietta mai nel gioco né si aggancia a esso, non apre mai il processo del gioco né ne legge la memoria, e non invia mai input da tastiera o mouse. Se imposti una scorciatoia per il cassetto, registra presso Windows solo quella combinazione di tasti, nel modo standard con cui un programma chiede una scorciatoia. Star Citizen blocca le scorciatoie registrate da altri programmi mentre ha il focus, quindi, finché una scorciatoia è impostata, l'overlay riceve anche l'input grezzo della tastiera (raw input), il modo in sola lettura con cui Windows informa un programma in background dei tasti premuti. Non è un hook della tastiera: non trattiene, non modifica e non invia alcun tasto, non registra nulla e reagisce solo alla tua combinazione. CIG non si è espressa su overlay di questo tipo, quindi vale anche qui l'avvertenza sull'uso a tuo rischio riportata più sotto.

CIG ha sostenuto pubblicamente la localizzazione della community. Il loro post [Community Localization Update](https://robertsspaceindustries.com/spectrum/community/SC/forum/1/thread/star-citizen-community-localization-update) illustra il supporto ufficiale alle traduzioni create dai giocatori, che a nostro avviso consente esplicitamente il tipo di modifica alla localizzazione fatta da Smart Citizen.

Streamer molto seguiti portano avanti progetti di localizzazione simili alla luce del sole, e a nessuno di loro è mai stato chiesto di fermarsi.

Detto questo: il modo in cui usi Smart Citizen è a tuo rischio. Le nostre modifiche dovrebbero andare bene, ma per qualsiasi cosa tu faccia in autonomia, sei tu, insieme ai tuoi collaboratori, a rispondere degli eventuali danni. Se non sei sicuro che una modifica sia appropriata, mantienila puramente estetica e tieni sempre un backup.

## Quali file modifica Smart Citizen?

Uno solo, e soltanto quando clicchi **Applica Miglioramenti**:

- `StarCitizen\<canale>\data\Localization\<lingua>\global.ini` — il file di localizzazione del gioco per il canale (LIVE, PTU, ecc.) e la lingua che hai selezionato. Smart Citizen fa prima il backup del file esistente, poi scrive il risultato unito.
- Si assicura anche che `g_language` sia impostato nel tuo `user.cfg`, così il gioco carica la localizzazione giusta. Nient'altro nella tua installazione di gioco viene toccato.

Tutto ciò che Smart Citizen genera per uso proprio (la cache delle sorgenti, i file di miglioramento, i backup, il tuo `user.ini`) risiede nella cartella dati di Smart Citizen, non nel gioco.

## Perché Windows dice che questa app non è riconosciuta?

Perché Smart Citizen non ha ancora una firma digitale (code signing). Windows SmartScreen e Smart App Control segnalano qualsiasi nuova app di un editore per cui non hanno un certificato di firma registrato, anche se è completamente sicura. È un avviso del tipo "non l'abbiamo mai vista prima", non "questa è pericolosa".

Per eseguirla: nella finestra di SmartScreen clicca su **Ulteriori informazioni → Esegui comunque**. Se Smart App Control la blocca del tutto, puoi consentire l'app dal suo prompt, oppure disattivare temporaneamente Smart App Control, installare l'app e riattivarlo.

La firma del codice è nella nostra roadmap, e farà sparire questo avviso. Fino ad allora, scarica Smart Citizen solo dalle nostre release ufficiali su GitHub, così sai di avere la build originale.
