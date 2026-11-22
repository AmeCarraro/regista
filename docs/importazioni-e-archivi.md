# Importazioni, archivi e organizzazione di foto e video

Richieste del 22 novembre 2026. Il lavoro riguarda insieme applicazione PC e Android.

## Cartelle nascoste e documenti

La Galleria di Android omette le cartelle marcate `.nomedia`. La scansione MediaStore non può vederne i contenuti. Regista usa invece le autorizzazioni SAF conferite da «Aggiungi una cartella» e visita direttamente tutte le sottocartelle accessibili, senza modificare `.nomedia`.

Autorizzare sul telefono, se presenti:

- `Android/media/com.whatsapp/WhatsApp/Media`
- `Android/media/org.telegram.messenger/Telegram` (o la cartella pubblica Telegram del dispositivo)

Android può impedire l'accesso a cartelle private, `Android/data`, cloud non scaricato e altri spazi non concessi. Regista non dichiara questi contenuti importati. Le scansioni con errori restano da verificare.

Una sincronizzazione congela blocchi indipendenti per origine (normale / WhatsApp / Telegram) e categoria (media / documenti). Ogni blocco riprende con lo stesso identificativo e ha un solo ZIP definitivo. Una sincronizzazione successiva crea nuovi blocchi e non modifica archivi precedenti. Lo SHA evita di ritrasmettere contenuti già verificati, mentre i manifesti conservano ogni provenienza.

Precisazione concordata: foto e video della stessa provenienza condividono un blocco; l'audio del backup completo è separato. I documenti hanno un blocco ZIP distinto per ciascuna sottocategoria: PDF, Excel (`.xls` + `.xlsx`), Word (`.doc` + `.docx`), CSV, TXT. Le copie normali sono organizzate nello stesso modo, per esempio `Documenti/WhatsApp/PDF/…`, `Documenti/WhatsApp/Excel/…`. Il server rifiuta un Excel nel manifesto di un blocco PDF.

Le copie multimediali normali conservano l'organizzazione precedente. WhatsApp e Telegram hanno cartelle proprie nell'area delle importazioni, con le sottocartelle originali. I documenti sono sotto `Documenti`, con sottocartelle WhatsApp/Telegram quando pertinenti. I contenuti identici hanno una sola identità; una seconda destinazione può usare un hard link allo stesso originale. Le provenienze sono sempre mantenute. I tag automatici `WhatsApp` e `Telegram` si applicano anche ai doppioni.

«Importa e indicizza documenti» permette di usare le cartelle autorizzate o scegliere singoli file. Il comando PC nella sezione Telefono richiede al solo dispositivo scelto di mostrare la selezione. Supporto iniziale: PDF, XLSX, XLS, DOCX, DOC, CSV, TXT. L'estrazione di testo è locale, separata e limitata nel tempo; non riscrive mai un originale. Per DOC il file è archiviato con nome e metadati; il testo richiede DOCX. PDF protetti o scansionati restano trovabili per nome, tipo, data e tag, con un motivo visibile quando il testo manca. Nessun OCR implicito.

La chat riconosce richieste di documenti senza caricare Qwen: «Mandami il PDF della bolletta di ottobre», «Apri l'Excel delle spese». Mostra i file originali, consente di scegliere fra più corrispondenze e offre Apri/Scarica. Sul telefono il download verifica lo SHA prima dell'apertura nell'app scelta o del salvataggio tramite selettore Android. Il medesimo percorso autenticato funziona sulla VPN privata quando il PC è raggiungibile; la VPN non viene configurata automaticamente.

## Verifiche automatiche

`tests/test_messenger_documents.py` collauda API di importazione e ripresa, cartelle con `.nomedia`, destinazioni, provenienze dei doppioni, tag, ZIP separati e immutabili, PDF/XLSX con testo, PDF protetto e scansionato, richieste chat e byte originali scaricati. I file sono sintetici in una directory di test, fuori dal catalogo personale. I test JVM verificano le regole dei blocchi e la ripresa. Queste prove non sostituiscono il collaudo di SAF, schermo spento, tethering e finestre Android sul Redmi fisico.

Verifica del 22 novembre: 547 test Python superati, un test facoltativo CLIP saltato perché i campioni pubblici non fanno più parte della libreria personale; 119 test web superati e lint senza segnalazioni. Verifica visiva con dati sintetici: selezione Maiusc da A a B, anteprima e applicazione di tag/album, nascondi dalla vista generale, ricerca documenti e allegato originale nella chat. Caricamento reale Qwen in Ollama: 52,38 s a freddo; scaricamento: 0,30 s. Questi sono tempi misurati, non promesse sulle successive operazioni.

## Comportamento richiesto

- Importazione avviata esplicitamente dall'utente e mantenuta a schermo spento da un servizio Android con notifica, avanzamento persistente e interruzione volontaria. Nessuna nuova scansione autorizzata dal solo avvio dell'app.
- Foto e video nello stesso catalogo e negli stessi album; audio incluso nel backup completo. Originali conservati senza ricodifica. Selezione dai media accessibili di Android, incluse immagini PNG e file salvati da WhatsApp/Telegram; cartelle private e cloud non accessibile escluse e segnalate.
- Preferenza alla rete del tethering USB quando esiste ed è raggiungibile, con ripiego sul Wi-Fi. Indicazione del canale effettivo in entrambe le app; il solo cavo MTP/ricarica non costituisce questa rete.
- Nome originale, cartella sul telefono, tipo, data e SHA salvati nel manifesto e conservati nel catalogo. I dati dell'origine non si perdono scollegando un dispositivo.
- Un blocco coincide con l'insieme scelto per un'importazione: prima copie normali verificate, poi un unico ZIP completo, verificato e immutabile. Le riprese conservano il blocco e saltano i file confermati. I doppioni hanno un originale unico e più riferimenti nel manifesto. Nessuno ZIP definitivo dichiarato completo con file mancanti o errori.
- Scollega revoca soltanto l'accesso. Foto, video, tag, copie normali e archivi non vengono eliminati né dimenticati.
- Dall'elenco ZIP sul PC: apri archivio, scegli rimozione dal telefono, verifica entrambe le copie PC, identifica sul telefono i soli file con SHA coincidente, mostra il riepilogo e richiedi conferma esplicita PC e Android. L'operazione richiede il telefono aperto; non avviene al termine dell'importazione. I file cambiati non vengono rimossi. Preferenza al cestino Android.
- Selezione da A a B e per date sul PC, tag multipli separati da virgole, album/cartelle per viaggio visibili anche nella raccolta generale. Nascondi modifica la vista senza cancellare file o ZIP. Qwen può preparare una selezione e una proposta di tag, applicata soltanto dopo la conferma dell'utente.
- Controllo del modello Ollama sul PC da entrambe le app: Carica/Scarica, operazione idempotente con pulsante bloccato mentre lavora, stato reale, tempo trascorso e durata precedente. Nessun modello viene avviato sul telefono.
- Collegamento fuori dalla stessa Wi-Fi possibile mediante rete privata/VPN (es. Tailscale) con Regista acceso sul PC. Non è stata configurata una VPN sui dispositivi dell'utente; mantenere pairing e verifica del certificato, usando gli indirizzi privati consentiti, compreso 100.64.0.0/10.

## Stato del lavoro

- Le 200 immagini pubbliche di prova sono state rimosse dalla libreria attiva e conservate fuori dalla cartella scandita, in `build/removed-example-photos-20261122`.
- Reset PC e associazioni richiesto esplicitamente per riprovare con le nuove app; prima di eseguirlo è stata verificata l'assenza di richieste di cancellazione sul telefono dell'importazione corrente. Le copie PC vengono conservate recuperabili in `build/reset-pc-phone-media-20261122`.
- Reset eseguito: 888 foto e ZIP tolti dalla libreria attiva ma conservati nella cartella di recupero; tre credenziali revocate, zero richieste di cancellazione sul telefono corrente. Regista PC è stato chiuso per eseguire il reset ed è ancora da riaprire dopo la distribuzione delle nuove versioni.
- Backend archivi per blocco e pulizia da ZIP implementato: 14 test dedicati superati, più 94 test di regressione catalogo/telefono. Organizzazione con anteprima, tag multipli, album e nascondi implementata: 7 test dedicati e 63 test catalogo/snapshot superati.
- Servizio Android per importazione fotografica, checkpoint e notifica in sviluppo; prima compilazione e 23 test JVM preesistenti superati. Va esteso al trasferimento unificato foto/video e agli archivi per blocco prima della distribuzione.
- `forget_device` modificato per conservare i dati: aggiornare anche test, interfacce e gestione della cache Android.
- Ancora da implementare e collaudare: archivi per blocco, ripresa media, provenienza e catalogo video, USB preferito, rimozione da archivio con doppia conferma, selezioni/tag multipli/album/nascondi, build di entrambe le app e distribuzione.

## Verifiche di accettazione

Testare interruzione/rete persa/ripresa senza duplicare file; nessun avvio senza richiesta; disaccoppiamento dal ciclo dell'Activity; revoca con dati intatti; cartelle di origine e formati misti; ZIP incompleti o corrotti mai autorizzati alla pulizia del telefono; file modificati o SHA diverso mai rimossi; cancellazione rifiutata dall'utente rispettata; album misti e nascondi senza perdita di originali. Conservare la chiave di firma Android e il tono visivo arrotondato già ripristinato nella versione 0.8.
