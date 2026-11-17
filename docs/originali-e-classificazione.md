# Originali, classificazione e ripresa delle importazioni

17 novembre 2026. Aggiornamento successivo alla prima correzione Qwen Instruct.

## Tag proporzionati alla scena

Il prompt `catalog-it-3` chiede soggetti principali, oggetti, ambiente, quantità chiaramente riconoscibili, colori e caratteristiche salienti. Non impone un numero di tag. Descrizioni concise e assenza di paragoni riducono le aggiunte non pertinenti. Una proposta dominata da tag duplicati viene rifiutata come risposta ripetitiva.

I tag sono normalizzati e verificati rispetto alla descrizione. Dai soggetti accettati si ricavano anche quantità esplicite da due a venti e combinazioni soggetto-colore presenti letteralmente nel testo. Esempio: `gatti`, insieme alla descrizione «due gatti», produce anche `due gatti`; `telecomandi` in «due telecomandi grigi» produce `due telecomandi` e `telecomandi grigi`. I tag generali restano utili alla ricerca. `2 gatti` e `due gatti` condividono una forma canonica e la ricerca riconosce entrambe le scritture, mantenendo la quantità legata al soggetto: un gatto accanto a due cani non è un risultato per «due gatti». Evidenza e origine delle aggiunte sono registrate nei dati diagnostici.

Il profilo di generazione attuale usa temperatura 0,4, top-p 0,8, top-k 20, repetition penalty 1,05, presence penalty 0,3, frequency penalty 0,3 e seed 42. Si tratta di una configurazione applicativa misurata localmente, diversa dal preset generale Qwen della prima prova.

Ultima prova su tre foto pubbliche, modello già caricato: gatti 6 tag in 3,168 s; cane 4 tag in 3,837 s; stanza 8 tag in 6,535 s. Per i gatti sono stati salvati `cuscino`, `due gatti`, `due telecomandi`, `gatti`, `telecomandi`, `telecomandi bianchi`. L'aumento di dettaglio non garantisce accuratezza: nella descrizione dei telecomandi rimane una formulazione contraddittoria sul conteggio, e Qwen può ancora sbagliare colori o oggetti. Non è una valutazione su una libreria completa.

## Cinque minuti, motivo e riprova

`REGISTA_INFERENCE_TIMEOUT` ha default `300`, in secondi. `0` mantiene la possibilità di disattivare il timeout della risposta. Per le chiamate JSON il limite copre l'intera risposta HTTP, anche se arrivano byte intermedi; l'attesa nello scheduler è separata. Connessione e invio mantengono limiti distinti di 20 e 60 secondi.

Timeout, output troncato, JSON invalido e tag completamente incoerenti lasciano un lavoro in errore, con motivo persistente, fuori dalla coda automatica dopo il primo tentativo. Altri errori transitori conservano il massimo precedente di tre tentativi con backoff. **Riprova errori** rimette in coda le foto; **Avvia / Riprendi tag** abilita l'analisi. Il worker continua con le altre foto. Le lease vengono rinnovate durante attesa e inferenza.

## ZIP originali prima della classificazione

La cartella è `<directory del catalogo>/backup-originali/<prime due cifre SHA>/<SHA-256>.zip`. Nel desktop la directory del catalogo è sotto `INDEX_DIR`; in Docker è nel volume dell'indice. Un archivio per contenuto evita sia una seconda copia di ogni doppione sia la riscrittura di un unico ZIP enorme a ogni importazione.

Ogni ZIP contiene `manifest.json` e `original/<nome originale>`. Il manifest riporta nome, dimensione, SHA-256 e data di creazione del backup. L'immagine conserva esattamente i byte di partenza, inclusi EXIF/GPS incorporati: non viene ricompressa o riscritta come immagine. Il contenitore ZIP è compresso; i JPEG possono occupare quasi lo stesso spazio dell'originale.

Il backup viene scritto in un file temporaneo, riletto per verificare CRC e SHA-256, sincronizzato e pubblicato senza sovrascrivere una destinazione creata contemporaneamente. Il file finale viene verificato prima della conferma dell'importazione. Un archivio valido rimane invariato; un archivio danneggiato viene mantenuto con suffisso `.corrotto-…zip` e ricreato solo se è disponibile un originale integro. La scansione crea anche i backup mancanti delle foto già nel catalogo. La prima scansione dopo l'aggiornamento può quindi richiedere tempo e spazio su disco, senza rieseguire l'AI sulle foto già annotate.

Lo ZIP si scarica dalla scheda della foto sul PC. Per recuperare un originale basta aprire lo ZIP ed estrarre il file sotto `original/`; il test di recupero verifica che il contenuto sia identico byte per byte. Questa copia separata protegge dalle modifiche organizzative; per un guasto dell'unità occorre conservarne una copia su un altro disco o supporto.

## Una copia operativa per importazione

L'identità è il SHA-256 dell'intero file. Le nuove importazioni identiche non creano un secondo file operativo o un secondo ZIP. Il contenuto già presente sul PC viene ricontrollato prima di dire al telefono che non serve trasmetterlo. Un percorso il cui file è cambiato non può confermare il vecchio hash. Sul telefono un secondo originale identico nello stesso lotto viene saltato soltanto dopo la conferma del primo salvataggio sul PC.

I duplicati già presenti nelle cartelle sorgenti restano un solo elemento nel catalogo e condividono l'analisi e il backup. La loro eliminazione fisica dalle cartelle dell'utente non è automatica. Immagini simili con compressione, ritaglio o EXIF differenti hanno byte diversi: questo aggiornamento non applica deduplicazione visiva.

## Classificate, da catalogare e da trasferire

Le nuove copie gestite da Regista entrano in `<cartella importazione>/Da catalogare/<SHA>.<estensione>`. Un risultato valido passa la copia a `Classificate`. Prima dello spostamento vengono verificati backup, contenuto e destinazione; un file diverso non viene sovrascritto. I vecchi nomi SHA del precedente importatore vengono riconosciuti e organizzati dopo la scansione. Le cartelle sorgenti aggiunte sul PC restano nella loro organizzazione originale e usano gli stessi filtri logici nel catalogo.

La modalità foto in sola lettura disabilita anche la riorganizzazione dei file importati in precedenza: tag e stato possono essere aggiornati nel catalogo, mentre i percorsi delle foto restano invariati.

Timeout e altri errori espongono motivo e tentativi nella scheda della foto. I filtri permettono di vedere tutte le foto, le classificate, tutte quelle da catalogare o solo quelle con errore. Un'annotazione precedente e le correzioni manuali restano disponibili durante una rianalisi; un suo fallimento rende la foto da rivedere. Gli errori storici di una versione precedente non continuano a contare dopo un successo più recente.

Il manifesto del telefono conserva separatamente gli originali ancora da ricevere, quelli ricevuti e gli errori. Il PC mostra un conteggio per contenuto distinto e un'anteprima dei primi venti; non si confondono con le immagini già ricevute ma ancora da classificare. **Importa tutte le foto dal telefono** può riprendere un trasferimento: gli originali già ricevuti e verificati non vengono trasmessi di nuovo. Restano necessari i permessi Android sulle cartelle e sulle immagini accessibili all'app.

## Migrazione e verifiche

Il database passa alla versione 3 con backup SQLite coerente `catalog.before-v3.sqlite`. Annotazioni, tag manuali, correzioni, ricevute e versioni precedenti restano conservati. La struttura delle risposte è compatibile con il protocollo telefono 2; per mostrare i nuovi controlli serve l'APK aggiornato.

Sono stati verificati recupero ZIP esatto, originali duplicati, importazioni interrotte, destinazioni occupate, archivi corrotti, mancata conferma di backup non verificati, riprova esplicita, annullamento, migrazione e ricevute dei doppioni. Le prove reali hanno usato soltanto le tre foto pubbliche già documentate, senza importare o riorganizzare foto personali.

Verifica finale: 463 test backend e 114 test web superati; TypeScript, lint e build PC/telefono senza errori. APK release ricompilati per arm64-v8a e armeabi-v7a. Pacchetto PC in `build/Regista` aggiornato conservando runtime, configurazioni e dati; il suo Python ha creato e verificato tre ZIP delle foto pubbliche senza avviare l'AI. Il controllo tramite browser non è stato completato: il browser integrato non era disponibile e l'approvazione automatica ha rifiutato l'accesso a una finestra Brave estranea al test. I nuovi stati e i motivi sono stati verificati tramite API su un'istanza isolata, poi chiusa.
