# Regista: catalogo fotografico persistente con Qwen

Piano operativo — 13 novembre 2026. Solo progettazione: nessuna modifica funzionale già applicata.

## Obiettivo e decisioni

Regista gira sul PC e offre tre sezioni: Assistente (chat e domande su immagini), Catalogo foto (cartella con sottocartelle, annotazione automatica, ricerca), Musica (funzioni esistenti). Il telefono è un client del PC: nessun modello neurale e nessuna indicizzazione AI sul telefono nel nuovo percorso. Musica locale, widget e trasferimenti restano.

Qwen3-VL 2B è il modello desiderato per visione e regia. Usare un unico modello configurato per entrambi i ruoli; candidato preferito `qwen3-vl:2b-instruct`, da installare/verificare separatamente. `qwen3-vl:2b` è già stato provato in Ollama ma ha mostrato ragionamento lungo e un errore fattuale: non assumere qualità sufficiente né identità fra tag. Registrare nome esatto, digest, quantizzazione, prompt e versione schema. Non scegliere silenziosamente modelli alternativi con la logica automatica precedente.

Una foto viene analizzata visivamente una volta per contenuto e versione esplicitamente selezionata. Il risultato è persistente. Ricerche successive non lanciano analisi delle immagini. Nuove foto entrano in coda; reindicizzazione e seconda passata sono comandi espliciti, mai un ciclo permanente sulle stesse foto.

Non riscrivere l'app da zero e non introdurre Tauri. Riutilizzare infrastruttura, frontend e API funzionanti. Non integrare il prototipo Tkinter VLM Lab come nuova applicazione: usarne solo le idee utili.

## Stato riscontrato nel codice

| Componente | Stato e intervento |
| --- | --- |
| `app/main.py` | Backend FastAPI; API chat, foto, azioni, telefono e musica. Separare i nuovi router invece di ingrandire ulteriormente il file. |
| `web/package.json`, `web/src/App.tsx` | React + TypeScript + Vite, vista chat, categorie, musica e demo. Aggiungere Catalogo e semplificare navigazione. |
| `app/desktop.py`, `requirements-desktop.txt` | Desktop Python + pywebview/WebView2; avvia già Ollama. La chiusura termina il servizio: serve distinguere finestra e servizio se si desidera accesso remoto continuativo. |
| `android/`, `web/src/telefono/` | Kotlin e viste React per telefono; ricerca offline e modelli da rimuovere nel nuovo percorso, mantenendo collegamento e musica. |
| `app/photos.py` | Scansione ricorsiva già presente, miniature, EXIF/date e indice CLIP. Identità basata sul percorso, cache su dimensione e mtime in secondi: non sufficiente per spostamenti e deduplicazione del lavoro visivo. |
| `app/tags.py` | SQLite per tag manuali, senza provenienza o versioni: utile come precedente, non come schema completo del nuovo catalogo. |
| `app/orchestrator.py` | Decisioni strutturate e protezione delle azioni. Ricerca con embedding e verifiche visive ripetute da sostituire. |
| `app/llm.py`, `app/catalog.py` | Client Ollama, caricamento e scelta automatica dei modelli. Riutilizzare il client; adattare scelta, memoria e concorrenza al modello unico. |
| `training/`, `app/command_model.py`, `app/command_demo.py`, `docs/modello-regista.md` | Percorso sperimentale di addestramento da zero per comandi, visione e risposte. Da ritirare dal prodotto e dal nuovo piano, dopo aver verificato dipendenze e conservato una versione recuperabile. |

La ricognizione ha verificato questi punti nel sorgente; non costituisce un collaudo di tutte le funzioni esistenti né una verifica indipendente delle metriche riportate nei commenti.

## Esperienza d'uso

### Catalogo sul PC
- Scegliere una cartella radice autorizzata; includere sottocartelle. Nessuna modifica agli originali durante scansione o annotazione.
- Mostrare conteggi: scoperte, in attesa, analizzate, errori, escluse, mancanti; percentuale di copertura e foto corrente.
- Comandi: Avvia, Pausa, Riprendi, Solo quando inattivo, Riprova errori, Rianalizza selezione. Una seconda passata futura deve mostrare costo e ambito.
- Galleria con miniature, tag automatici, descrizione, data e luogo con provenienza. Nessun numero obbligatorio di tag: oggetti, animali, scena, colori salienti, attività chiaramente visibili; descrizione breve. Limiti tecnici di lunghezza/numero proteggono il parser, non sono una quota da riempire.
- Ricerca naturale, filtri per data/luogo/cartella/tag e risultati paginati. Mostrare quali tag o metadati hanno prodotto la corrispondenza.
- Possibile correggere o escludere un tag sbagliato, senza obbligare l'utente a catalogare manualmente. Correzioni persistenti che una rianalisi non sovrascrive.

### Assistente e telefono
- Chat generale e invio immagine per domanda immediata. Un allegato temporaneo non entra automaticamente nel catalogo: offrire Salva nel catalogo.
- Dal telefono cercare le foto del catalogo PC; restituire prima miniature, originali solo su richiesta. Upload esplicito per aggiungere foto dal telefono alla cartella d'importazione autorizzata sul PC.
- PC non disponibile: stato chiaro, senza simulare risultati o inferenza sul telefono. La musica locale può continuare.
- Conservare pairing, certificati e revoca accessi. Connessione da fuori casa via rete privata già prevista; non esporre direttamente Ollama. Percorsi locali non inviati al client.
- Ricerca Internet fuori dal perimetro iniziale. Non necessaria per tagging, date o ricerca del catalogo; eventuale strumento futuro separato e trasparente.

## Dati e provenienza

Usare un database SQLite locale, separato dagli originali, con migrazioni versionate e transazioni. Valutare WAL per lettori durante l'indicizzazione. Schema proposto:

- `library_roots`: radice autorizzata e impostazioni di scansione.
- `assets`: identità stabile del contenuto, SHA-256, formato, dimensioni; non usare il percorso come identità semantica.
- `file_locations`: UUID, asset, radice, percorso relativo, dimensione, mtime_ns, presenza. Più copie possono puntare allo stesso asset.
- `metadata`: data, GPS/luogo, filename/cartelle, valore originale, fonte, precisione e conflitti. Metadati del percorso possono cambiare senza richiamare il VLM.
- `annotations`: asset, modello/digest, versioni prompt/schema, descrizione, risultato strutturato, tempi, validità. Vincolo univoco per evitare doppio commit della stessa analisi.
- `tags` e `asset_tags`: termini normalizzati italiani, categorie, provenienza e collegamento all'annotazione. Vocabolario con sinonimi e forme singolari/plurali.
- `overrides`: correzioni dell'utente, da preservare separatamente.
- `jobs`: stato, tentativi, prossima esecuzione, lease e ultimo errore.
- Indice full-text SQLite FTS5 per descrizioni/tag, verificandone disponibilità nella distribuzione Python installata; filtri strutturati separati.

Fonti: EXIF DateTimeOriginal per data di scatto quando valido; GPS per luogo; nome/cartelle come indizi dichiarati. mtime è data del file, non automaticamente data di scatto. Un anno o mese nel percorso resta una data parziale, senza inventare giorno. Conservare conflitti, timezone e valori sconosciuti.

«Giappone» in una cartella è un tag da percorso, non prova geografica. Qwen non deve dedurre Giappone soltanto da un tempio. Eventuali luoghi suggeriti visivamente sono ipotesi separate, escluse per default dai filtri geografici certi. Nella prima versione evitare inferenze geografiche visive e usare metadati espliciti.

## Indicizzazione incrementale e scheduler

1. Scansione ricorsiva limitata alla radice; escludere cache, cestino, output, symlink/junction che escono dalla radice, file incompleti e formati non supportati.
2. Controllare stabilità di dimensione/mtime prima della lettura; hash dei candidati nuovi/cambiati. Rilevare rinomina/spostamento senza ripetere l'analisi visiva; aggiornare solo i metadati di percorso.
3. Creare job durevoli solo per contenuti senza annotazione valida. Rescan immutato deve produrre zero chiamate VLM.
4. Un worker visivo alla volta. Orientamento EXIF corretto, immagine RGB ridimensionata dall'originale (non dalla miniatura già degradata), budget iniziale 512px configurabile.
5. Risposta JSON vincolata da schema e validata. Output troncato/invalido, timeout e file corrotti non sono successi: retries limitati, backoff, errore visibile e ripresa esplicita.
6. Commit atomico annotazione + tag + completamento job. Lease recuperabili dopo crash. Non promettere exactly-once dell'inferenza: un crash dopo la risposta e prima del commit può richiederne la ripetizione; garantire un solo risultato persistente valido per versione.
7. Priorità: richieste interattive PC/telefono prima dell'indicizzazione. Coda/arbitro condiviso da tutti i percorsi Ollama, inclusi chat e test; i job in background cedono almeno tra foto. Timeout limita l'attesa, nessuna promessa di preemption istantanea della GPU.
8. Modalità Manuale, Quando inattivo, Pausa. Per l'inattività combinare assenza di richieste Regista, finestra stabile di bassa attività GPU e impostazioni alimentazione. Soglie iniziali configurabili e misurate sul PC, non hardcoded come garanzia.
9. Non usare soltanto VRAM libera: il modello già caricato occupa memoria anche quando non lavora; non usare soltanto GPU utilization: può essere bassa con memoria occupata da altri processi. Telemetria NVIDIA, memoria disponibile, cooldown e hysteresis. Se telemetria manca, modalità conservativa/manuale.
10. Stop nuovi job quando il computer è impegnato; non terminare applicazioni altrui e non scaricare modelli caricati da altri client. Budget di contesto e memoria espliciti; una sola copia del modello.

Per elaborare a finestra chiusa serve modalità background/tray con indicatore e comando Esci. Il PC non elabora da spento o sospeso. Avvio con Windows e prevenzione sospensione sono opzioni separate, non modifiche silenziose. L'app aperta può indicizzare già nella prima release.

## Ricerca e regia

- Qwen traduce la richiesta in un piano JSON: azione, termini, AND/OR, esclusioni, periodo, luogo, cartella, ordinamento e limite. Il backend convalida e compila query parametrizzate; il modello non produce SQL eseguibile o percorsi arbitrari.
- «Cane» deve trovare anche «cani», «cucciolo» quando pertinente; dizionario iniziale semplice e verificato, evitando espansioni troppo ampie.
- L'indice full-text supporta ricerca nelle descrizioni oltre ai tag. Congiunzioni come «cane nero» non provano che nero si riferisca al cane: prevedere tag composti/attributi riferiti agli oggetti e dichiarare i limiti nei casi ambigui.
- «Non trovo risultati» non significa «non possiedi foto così», soprattutto con catalogo parziale o tag mancanti. Mostrare la copertura.
- Nessun richiamo VLM alle immagini per una ricerca ordinaria. Richiesta esplicita di verifica/nuova analisi resta un'operazione distinta.
- Nessun training necessario. Non basta però cambiare il nome del modello: rivalutare capacità di regia con benchmark sui comandi esistenti, negazioni, richieste ambigue e musica. Se qualità insufficiente, chiarimento/regole deterministiche e segnalazione del limite, non azioni speculative.
- Conservare proposte, conferma, journal e undo per spostamenti/copie/cestino. Testo nelle immagini, EXIF o nomi file è dato non attendibile e non autorizza strumenti.

## Cosa conservare, sostituire e ritirare

**Conservare:** stack attuale; musica e widget; trasporto sicuro telefono; gestione autorizzazioni; miniature; parsing EXIF/date e GPS adattato alla provenienza; azioni con conferma e undo; test validi; dati originali.

**Sostituire:** `PhotoIndex` vettoriale con catalogo persistente; ricerca semantica CLIP e verifica visiva a ogni query con tag/descrizioni; classificazione `kinds.py` basata su embedding con categorie annotate; selezione automatica multi-modello con modello esplicito; indicizzazione offline Android con client del PC.

**Ritirare dal runtime e dall'interfaccia:** demo del modello addestrato da zero, aggiunta manuale obbligatoria dei tag, modelli ONNX foto/comandi sul telefono, sincronizzazione vettori e download modelli telefono, training comandi/visione/risposte come requisito del prodotto. Esaminare `training/`, `command_model.py`, `command_demo.py`, `CommandDemo.tsx`, `CommandTags.tsx`, `ManualTags.kt`, `Sight.kt`, endpoint `/phone/vectors`, `/phone/models` e relativi installer/test. Sono candidati: verificare riferimenti prima di rimuovere classi intere.

**Dipendenze indirette da risolvere prima della rimozione:** duplicati in `photos.twins` usa vettori + hash percettivo; sostituire con duplicati esatti via SHA-256, mentre similarità percettiva resta proposta non automatica. Album viaggi possono riusare metadati; categorie vanno ricostruite da tag. Rimuovere ONNX Runtime e pesi CLIP solo dopo assenza di consumatori in backend, Android, installer, export e test. Non togliere NumPy senza verificare usi rimanenti.

**Dati preesistenti:** importare tag manuali come fonte legacy, conservarli nel backup; non cancellare foto, checkpoint o pesi dell'utente. Disattivare/archiviare gli esperimenti e rimuovere il codice obsoleto dal prodotto con commit recuperabili. Il piano autorizza sviluppo futuro, non la distruzione di dati. Nessuna eliminazione già effettuata.

## Fasi di implementazione

1. **Baseline e contratti:** inventario dipendenze, stato git, test backend/frontend/Android esistenti, backup database; definire schema e migrazione, verificare modello esatto, parsing JSON e qualità su 30–50 foto etichettate manualmente. Misurare primo avvio e richieste a caldo. Non usare la vecchia accuratezza come misura del nuovo tagging.
2. **Catalogo e annotazioni:** aggiungere moduli `photo_catalog.py`, `photo_annotator.py`, `index_jobs.py` (nomi proposti), scanner incrementale, metadati e job persistenti; CLI diagnostica e modalità manuale. Feature flag mantiene temporaneamente il vecchio flusso per rollback.
3. **Scheduler condiviso:** `inference_scheduler.py` per tutte le chiamate Regista, priorità e pausa; telemetria best effort, gestione errori e pressione memoria. Modalità inattivo solo dopo test.
4. **Nuova ricerca:** `photo_search.py`, router catalogo e adattamento orchestratore. Riutilizzare accesso a file/miniature tramite ID, aggiornare azioni e mapping per vecchi ID durante migrazione.
5. **Interfaccia PC:** aggiungere `Catalog.tsx`, stato coda, filtro e spiegazione risultati; mantenere Assistente e Musica; eliminare demo obsolete dopo verifica.
6. **Telefono:** API autenticata per query/paginazione/miniature/originali/upload; schermata catalogo PC; errori offline; eliminare inferenza e download pesi lato Android dopo passaggio riuscito. Versionare protocollo e mostrare aggiornamento richiesto ai vecchi client.
7. **Background e distribuzione:** separare vita della finestra dal servizio quando abilitato; aggiornare installer, configurazione e documentazione; aggiornamento atomico frontend/backend/Android compatibili.
8. **Migrazione finale e pulizia:** spostare il default sul nuovo catalogo, conservare vecchi dati per rollback; eliminare dipendenze e codice inattivi solo dopo tutti i test. Fare commit per fase, senza pubblicare o fare push automaticamente.

## Criteri di accettazione

- 100 foto → una annotazione valida per contenuto; scansione ripetuta invariata → zero nuove richieste visive.
- Nuova foto → un nuovo job; rinomina → nessuna nuova visione; modifica contenuto → nuova analisi; nuova versione prompt → nessuna rianalisi di massa senza comando esplicito.
- Arresto a metà e ripartenza → nessuna perdita di risultati o duplicazione dei tag; file corrotto non blocca il resto della coda.
- «Cani in Giappone nel marzo 2025» combina contenuti e metadati con fonti corrette. «Giappone» suggerito dal solo aspetto non diventa luogo certo.
- Query → zero visioni nuove; risultato paginato con conteggio calcolato dal backend, copertura e motivi. Testare AND/OR/esclusioni, sinonimi e attributi.
- Priorità interattiva dimostrata con coda in background e richieste simultanee PC/telefono; registrare tempi p50/p95 senza inventare obiettivi di velocità prima del benchmark.
- Foto fuori radice, junction, ID non autorizzati e allegati eccessivi rifiutati; pairing e revoca continuano a funzionare; testo malevolo nell'immagine non attiva azioni.
- Android esegue ricerche tramite PC senza caricare modelli; originale scaricato solo su richiesta; musica/widget invariati.
- Conferme e undo verificati; vecchi tag preservati; nessun download/cancellazione di pesi non richiesto.
- Test regressione backend/frontend e build Android, test di integrazione con Ollama reale su questo PC e prova su telefono fisico. Distinguere sempre test simulati da misure reali.

## Direttiva per chi implementa

Leggere questo documento e il codice prima di intervenire. Realizzare le fasi nell'ordine, riutilizzando Regista e preservando dati e musica. Modello unico Qwen3-VL 2B sul PC; catalogo tramite annotazioni persistenti e ricerca sui dati salvati; telefono senza inferenza. Nessuna riscrittura Tauri, nessuna rete addestrata da zero, nessuna nuova dipendenza cloud. Documentare limiti reali e lavoro non verificato. Il primo risultato da consegnare è scanner + annotazione persistente + ricerca su cartella di prova, seguito dall'integrazione UI e telefono.
