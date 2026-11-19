# Catalogo Qwen: implementazione e collaudo

13 novembre 2026, aggiornato il 19 novembre. Riferimento: `piano-catalogo-qwen.md`, conservato senza modifiche. Aggiornamenti: [originali ZIP, tag con quantità e stati di catalogazione](originali-e-classificazione.md); [riconoscimento e benchmark](confronto-qwen-riconoscimento.md); [APK 0.6: catalogo offline, musica e video](telefono-offline-e-video.md).

L'APK **0.7** aggiunge [backup completo dei media accessibili e rete USB](backup-completo-telefono.md): comando nelle impostazioni con conferma, immagini/audio/video e cartelle supplementari, ZIP per contenuto e manifesti di recupero, ripresa e deduplicazione anche fra backup e successiva importazione foto. La suite aggiornata supera 511 test backend, 119 web e 15 JVM Android; il trasferimento fisico rimane da provare.

## Percorso implementato

- SQLite separato dagli originali, WAL, migrazioni fino alla versione 3, FTS5. Identità SHA-256 del contenuto e posizioni multiple, senza inviare percorsi assoluti ai telefoni.
- Scansione ricorsiva incrementale, nanosecondi e dimensione, hash dei file nuovi/modificati, controllo di stabilità, esclusione di collegamenti, cestino, raccolte di output e directory dell'indice. Una radice temporaneamente assente non viene trattata come un disco svuotato. Radici annidate non producono copie fittizie.
- La scansione non chiama modelli. Dopo ogni avvio del servizio l'analisi resta in pausa. Avvia/Riprendi, Pausa, modalità inattivo conservativa, riprova errori e rianalisi della selezione sono espliciti.
- Un worker, job durevoli con lease, scadenza e recupero, tre tentativi con backoff, commit atomico di annotazione/tag/job. Risultati validi precedenti restano disponibili durante una rianalisi. Nessuna promessa di inferenza exactly-once dopo un crash.
- Immagini orientate con EXIF, RGB, lato massimo 512 configurabile, JSON con schema e validazione stretta, rifiuto di output troncato. Digest e quantizzazione del modello, versioni prompt/schema, prompt effettivo, budget immagine/contesto e tempi sono salvati. Il digest viene controllato prima e dopo la visione; un cambio mette in pausa la coda.
- Un arbitro condiviso dalle chiamate Ollama di Regista, comprese chat/test/percorso legacy, serve prima le richieste interattive in attesa. Nessuna preemption della foto già in corso. Nessuno scaricamento dalla memoria di modelli caricati da altri client.
- Ricerca SQLite/FTS, AND/OR/esclusioni, sinonimi iniziali italiani/inglesi, filtri data/luogo/cartella/tag/radice, conteggio backend, paginazione e motivi. La ricerca naturale usa Qwen solo sul testo. Le immagini non vengono riesaminate per una ricerca ordinaria.
- Date EXIF e indizi dai percorsi/nome originale del telefono distinti; anno/mese restano parziali. I filtri temporali considerano l'intervallo compatibile con una data parziale, mantenendo visibile la precisione. Il luogo geografico richiede GPS, con GeoNames quando disponibile; nomi di cartelle non diventano luoghi certi. Nessuna geolocalizzazione visiva.
- Correzioni ed esclusioni dei tag in una tabella separata, mantenute durante la rianalisi. Lettura dei tag del vecchio `demo-tags.sqlite`, backup coerente con SQLite e importazione come fonte `legacy` senza sovrascrivere correzioni nuove.
- Interfaccia PC Catalogo, Assistente e Musica. Nell'Assistente un'immagine temporanea può ricevere una risposta e viene conservata nel catalogo solo tramite Salva; allegati temporanei associati al proprietario, scadenza di due ore, limite 16 MB.
- Router separati dal servizio principale. Conferme, journal e undo delle azioni esistenti nella radice principale restano attivi. Le radici aggiuntive sono consultabili e annotabili; le azioni di spostamento/copia/cestino sulle loro foto sono rifiutate prima della proposta.

## Telefono: prima copia, poi analisi

Da PC: Catalogo → Importa tutte le foto dal telefono. La richiesta è durevole e viene presa quando l'app Android collegata è aperta. Dal telefono: Importa tutte le foto sul PC, oppure abilita la copia delle nuove foto. Non vengono spostati o rimossi gli originali del telefono.

Android elenca le immagini tramite MediaStore senza filtro DCIM: include tutte le cartelle accessibili con i permessi concessi dal sistema. Le cartelle private di altre app e le immagini non concesse da Android non sono accessibili a Regista. Per ottenere l'originale completo, inclusi GPS, occorre anche il permesso Android sulla posizione delle foto.

Manifest con SHA-256, upload in streaming con hash verificato, file temporaneo e copia atomica senza sovrascrittura. Deduplicazione per contenuto fra cartelle, copie e telefoni; un file già presente sul PC non deve essere trasmesso di nuovo. Limite tecnico di upload 400 MB per originale. JPEG/PNG/WebP/BMP/TIFF/GIF/AVIF leggibili da Pillow possono essere analizzati. HEIC/HEIF e alcuni RAW riconoscibili possono essere conservati senza decoder: vengono segnati come esclusi dall'analisi. Formati sconosciuti o danneggiati sono segnalati, senza un falso successo.

Ogni importazione mette in pausa il tagging. Al termine, o quando l'utente decide, Avvia/Riprendi sul PC abilita la coda. Un'inferenza già in corso può terminare prima della pausa.

Protocollo telefono 2: il PC conserva analisi e catalogo principale. Dal 19 novembre, su richiesta dell'utente, l'APK 0.6 riceve una copia SQLite sanitizzata e indicizzata di tag, descrizioni e metadati per cercare offline; FTS4 sul telefono non richiede modelli. Per le foto presenti anche sul telefono viene verificata l'identità MediaStore prima dell'apertura locale; le immagini presenti soltanto sul PC richiedono il collegamento. La ricerca avanzata del PC rimane disponibile online. Pairing, certificati, revoca, musica, widget e copia periodica autorizzata restano. La scheda Video riproduce i file locali scelti tramite Android. Android non include ONNX Runtime; Sight/CommandPreview rimangono in standby. I vecchi APK vanno aggiornati insieme al servizio.

## Modello e configurazione

`REGISTA_PHOTO_CATALOG=1` è il default. `REGISTA_QWEN_MODEL=qwen3-vl:2b-instruct` è il candidato esplicito predefinito del piano. L'assenza del tag esatto è un errore visibile, senza fallback. In `settings.json` desktop le chiavi corrispondenti sono `photo_catalog` e `qwen_model`. L'installer accetta `-QwenModel` e non scarica più CLIP o modelli per Android; eventuali download dell'installer richiedono la sua conferma esplicita.

Aggiornamento del 17 novembre: installato e provato `qwen3-vl:2b-instruct`, digest `afc393e3572c07db0bc84aa460d928a16c75f3fbb9ca9e0dccc4fbd2dafb573e`, quantizzazione Q4_K_M. Il precedente `qwen3-vl:2b` rimane distinto. Nessun alias creato. [Risultati e tag delle tre foto pubbliche](prova-qwen-instruct.md).

`REGISTA_IMAGE_SIDE`, `NUM_CTX`, `KEEP_ALIVE` configurano i budget. La modalità inattivo usa `REGISTA_IDLE_SECONDS` (60), `REGISTA_IDLE_GPU_PERCENT` (10), `REGISTA_IDLE_FREE_MB` (768), `REGISTA_IDLE_STABLE_SECONDS` (30). Richiede telemetria NVIDIA e, su Windows, alimentazione di rete; in assenza dei dati resta conservativa. Questi valori sono iniziali, non soglie collaudate come garanzia su questo hardware.

`REGISTA_INFERENCE_TIMEOUT` controlla l'attesa della risposta Ollama: 300 secondi per default, `0` per disattivarla. Per le chiamate JSON il limite copre tutta la risposta, esclusa la coda GPU. Connessione e invio hanno timeout separati di 20 e 60 secondi; le richieste di stato/modelli mantengono 20 secondi. Il worker rinnova la lease ogni 60 secondi durante attesa e inferenza. Timeout e risposte invalide restano da catalogare con motivo persistente e riprova esplicita.

Annotazioni `catalog-it-3`, schema `2`: istruzioni e schema sono presenti nel testo della richiesta e nel decoder; categorie enum, budget di 4.096 token, campionamento con penalità sulle ripetizioni e seed registrato. Il risultato salvato include tag unici supportati dalla descrizione, con arricchimento di quantità e colori; le scritture numeriche e in lettere dei conteggi sono equivalenti. Tag scartati, evidenze delle aggiunte e risposta originale restano nei dati diagnostici. È una scelta conservativa: sinonimi e riformulazioni possono essere esclusi. Una descrizione errata può ancora produrre tag errati. Le annotazioni già salvate e le correzioni manuali restano disponibili; per applicare la nuova versione alle foto già analizzate occorre **Rianalizza selezione**.

Dal 18 novembre sono rifiutate anche le risposte prive di tag; restano da catalogare con il motivo. Le nuove annotazioni includono i tempi e i conteggi di token restituiti da Ollama, separati dal tempo complessivo. Non sono cambiati modello, prompt o campionamento. Il [nuovo collaudo](prova-qwen-altre-10-foto.md) porta a trenta le immagini pubbliche distinte provate con il catalogatore; gli errori di riconoscimento e conteggio restano un limite aperto. La suite backend aggiornata supera 486 test.

## Diagnostica

```powershell
.\.venv\Scripts\python.exe app/catalog_cli.py --database build/prova/catalog.sqlite scan C:\FotoProva
.\.venv\Scripts\python.exe app/catalog_cli.py --database build/prova/catalog.sqlite status
.\.venv\Scripts\python.exe app/catalog_cli.py --database build/prova/catalog.sqlite verify-model
.\.venv\Scripts\python.exe app/catalog_cli.py --database build/prova/catalog.sqlite run --max-photos 10
.\.venv\Scripts\python.exe app/catalog_cli.py --database build/prova/catalog.sqlite search cane nero
```

Per rollback del backend e della vista Foto precedente: `REGISTA_PHOTO_CATALOG=0`; nel desktop `photo_catalog: false`. I vecchi dati/esperimenti/pesi non vengono cancellati. Un APK protocollo 2 richiede il backend nuovo; per un rollback Android va usata una build precedente compatibile. Le istruzioni storiche sono in `README-legacy.md`.

## Prove e limiti

Test automatici su dati sintetici: 100 contenuti distinti, copie identiche, nuova scansione/rinomina senza nuove inferenze, modifica contenuto, versioni, lease scadute, commit stale, file corrotti, retry, correzioni persistenti, query senza immagini, date parziali, paginazione, AND/OR/esclusioni, tag/descrizioni distinti, pairing/revoca, importazione e pausa, HEIC archiviato, allegati temporanei e priorità interattiva. Questi test non misurano la qualità di Qwen su foto reali.

Prova Ollama reale: un disegno sintetico di un sorriso, con override esplicito del solo comando diagnostico a `qwen3-vl:2b`. Annotazione JSON valida, salvata e ricercabile; 38,31 s per quella singola chiamata, senza attribuire il tempo a un benchmark a caldo o a p50/p95. Artefatti locali ignorati da Git in `build/catalog-smoke/`.

Frontend PC e telefono compilati; 427 test backend e 114 test web superati, typecheck e lint senza errori; APK release compilati con la toolchain Docker già presente, offline. Nessun dispositivo fisico risultava collegato via ADB. Non è stato installato un APK sul telefono dell'utente e non sono state importate foto personali.

Restano da completare/validare prima di considerare chiuso l'intero piano: scelta e collaudo del modello esatto su 30–50 foto etichettate; benchmark regia/negazioni/ambiguità e p50/p95 con carico concorrente; telemetria e alimentazione in condizioni reali; prova su telefono fisico con tutte le cartelle accessibili; distribuzione e aggiornamento su un'installazione reale; servizio/tray indipendente dalla finestra. È disponibile il servizio senza finestra tramite `desktop.py --no-window`, ma non è stata implementata una nuova modalità tray, l'avvio automatico o la prevenzione della sospensione.
