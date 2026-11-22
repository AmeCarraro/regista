# Telefono: catalogo offline, musica e video

Aggiornamento del 19 novembre 2026, APK **0.6**. L'AI fotografica viene eseguita sul PC. Il telefono conserva un indice di tag, descrizioni e metadati; riproduce musica e video locali senza un modello neurale nell'app.

Dal 22 novembre, APK **0.8**: Foto, Video e impostazioni riprendono colori, tipografia, schede e pulsanti arrotondati delle schermate originali. Le impostazioni, con importazione delle foto, copia automatica e backup completo, si aprono dal pulsante in alto nella scheda Telefono. Il pulsante circolare di aggiornamento accanto a **Il tuo catalogo** conserva l'azione **Aggiorna il catalogo dal PC**.

## Collegamento con la fotocamera

In **Computer → Scansiona QR**, Regista chiede il permesso della fotocamera e apre uno scanner locale limitato ai QR. Inquadra il codice mostrato sul PC nella sezione Telefono. Lo scanner restituisce soltanto inviti Regista validi; collegamento e accesso alle foto richiedono ancora conferma sul telefono e sul PC. Nessun fotogramma viene salvato o inviato. Puoi annullare e incollare il link; se il permesso è negato, rimangono disponibili inserimento manuale e accesso alle impostazioni del permesso.

Il vecchio flusso offriva soltanto il link manuale e l'apertura di Regista dalla fotocamera esterna: lo scanner interno viene aggiunto in questa versione, con ZXing Android Embedded 4.3.0. Non dipende da Google Play Services e non riattiva i modelli del telefono. Il parser condiviso da QR, link incollati e deep link verifica formato, porta, certificato e indirizzi privati; gli inviti non validi non avviano connessioni.

Verifiche 0.8: 119 test web, TypeScript, lint, 23 test JVM Android (8 sugli inviti QR), compilazione release e confronto visivo a larghezza telefono con dati fittizi per Foto, Video e Backup. Lo scanner compila; non è ancora stato provato con una fotocamera fisica.

## Catalogo sul telefono

Il PC esporta una copia SQLite separata contenente una riga per contenuto SHA-256, tag effettivi con correzioni, descrizione, data, luogo e stato di catalogazione. Il file non contiene originali, ZIP, percorsi del PC, credenziali o tabelle interne del catalogo. Gli identificativi Android sono inclusi soltanto per il telefono che richiede la copia.

La prima connessione avvia la sincronizzazione. Quando la schermata Foto è visibile, l'app controlla nuovamente ogni cinque minuti; **Aggiorna il catalogo dal PC** permette di anticiparla. La copia è coerente rispetto a un singolo stato del database, anche se nel frattempo arrivano nuove annotazioni o correzioni.

Il trasferimento usa il collegamento TLS già associato al PC, verifica SHA-256 e integrità SQLite e sostituisce la copia precedente soltanto al termine. Se fallisce, l'ultima copia verificata resta disponibile. Il limite tecnico del trasferimento è 128 MB: un catalogo più grande produce un errore visibile e non una copia parziale. Scollegare il PC o associarne un altro cancella questa cache; foto originali, musica, video e vecchi pesi sperimentali restano intatti.

La ricerca sul telefono usa FTS4 indicizzato, senza rete e senza inferenza. Accetta parole e tag, anche combinati, date e luoghi salvati. Conserva i sinonimi iniziali del PC e l'equivalenza tra `2 gatti` e `due gatti`, mantenendo il conteggio legato al soggetto. Non è una chat locale: per richieste complesse e filtri avanzati rimane disponibile la ricerca del PC collegato.

Le foto già importate da quel telefono possono usare l'immagine e l'anteprima locali. Prima di riutilizzare un identificativo MediaStore viene controllata l'identità del file, per evitare di mostrare una foto diversa dopo modifiche o ricreazioni della galleria. Le immagini presenti soltanto sul PC richiedono il PC collegato per l'anteprima o l'originale; tag e descrizioni restano consultabili offline.

La sincronizzazione replica i tag che esistono sul PC, inclusi eventuali errori del riconoscimento: non ne certifica la correttezza. Le correzioni si fanno sul PC e arrivano con il successivo aggiornamento del catalogo.

## Musica

Il lettore esistente rimane: musica del telefono anche a PC spento, coda, pausa, avanzamento, controlli di riproduzione, widget e funzionamento a schermo spento. Restano la lettura e la copia della musica dal PC quando è raggiungibile. Le copie salvate nella musica del telefono continuano a funzionare offline.

## Video del telefono

La scheda **Video** apre il selettore di file Android, impostato sui video locali. Si possono scegliere più file e cercarli per nome nella raccolta dell'app. Sono conservati riferimenti autorizzati ai file scelti, senza duplicarli o trasferirli sul PC. **Togli dalla raccolta** rimuove il riferimento e lascia intatto l'originale.

La riproduzione usa `VideoView` e i controlli nativi Android per pausa e posizione. Aprire un video mette in pausa la musica di Regista; una canzone ancora in caricamento viene interrotta. Tornando alla scheda Musica si può riprendere o scegliere un brano. I formati effettivamente riproducibili dipendono dal decoder del dispositivo; file non più accessibili o non supportati producono un messaggio.

I video del PC e la loro analisi AI non fanno parte di questo aggiornamento.

## Modelli in standby

L'APK non include ONNX Runtime o pesi per inferenza. Gli adattatori dei vecchi esperimenti restano inattivi; anche le richieste legacy di attivazione non avviano download o analisi sul telefono. I vecchi checkpoint e pesi dell'utente non vengono cancellati.

## Distribuzione e verifiche

APK release per arm64-v8a, armeabi-v7a e x86_64; stesso identificativo `app.regista` e stessa chiave di firma, con versione crescente per l'aggiornamento. Gli APK e i metadati del pacchetto PC devono essere aggiornati insieme al nuovo endpoint `/phone/catalog/snapshot`. Il protocollo foto resta 2; il formato della copia offline è versione 1.

Verifiche eseguite:

- **491 test backend**: esportazione sanitizzata, autenticazione e revoca, checksum, pulizia dei file temporanei anche se il telefono si disconnette, correzioni, conteggi e stato coerente durante aggiornamenti concorrenti.
- **119 test web**, controllo TypeScript, lint e compilazione della pagina telefono. Le ricerche annullate non possono sostituire risultati più recenti.
- **6 test JVM Android** sul pianificatore locale: conteggi, sinonimi, Unicode, limiti e trattamento letterale del testo della ricerca.
- Compilazione degli APK release e controlli del pacchetto distribuito.

La build verificata è `0.6` / `464182`, circa 4,46 MB per APK. La firma è valida e il certificato coincide con quello della build precedente. Gli asset nell'APK corrispondono alla pagina telefono appena compilata; non sono presenti pesi neurali o librerie native del vecchio runtime. Anche il Python del pacchetto PC ha esportato e interrogato un catalogo FTS4 isolato senza chiamate al modello.

Non è stata eseguita una nuova installazione o una prova completa su telefono fisico: nessun dispositivo risultava collegato via ADB. Restano da provare sul dispositivo pairing reale, sincronizzazione/offline, apertura delle foto locali, riproduzione musicale e formati video.

Per il collaudo: avviare Regista aggiornato sul PC, installare l'APK 0.6, collegare il telefono, attendere il primo catalogo e poi spegnere la connessione al PC per verificare la ricerca salvata e i contenuti locali. Gli originali presenti soltanto sul PC richiedono la riconnessione.
