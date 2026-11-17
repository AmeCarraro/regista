# Regista

Assistente locale sul PC, catalogo fotografico persistente e musica. Il telefono è un client del PC: cerca nel catalogo e importa gli originali, senza caricare modelli neurali.

Le immagini vengono identificate con SHA-256. Scansioni ripetute, copie identiche e rinomine non richiedono una nuova analisi visiva. Tag, descrizioni, metadati e correzioni restano in SQLite; le ricerche usano i dati salvati.

## Uso del catalogo

1. Apri **Catalogo foto**, aggiungi le cartelle autorizzate e premi **Scansiona cartelle**.
2. Per le foto del telefono, collega l’app Android e premi **Importa tutte le foto dal telefono** sul PC, oppure il pulsante equivalente sul telefono. Regista considera tutte le cartelle accessibili ad Android e copia una sola volta ogni contenuto identico.
3. Importazione e tagging sono separati: premi **Avvia / Riprendi tag** quando vuoi iniziare l’analisi sul PC. Ogni riavvio e ogni importazione lasciano la coda in pausa.
4. Cerca con termini e filtri oppure abilita la ricerca naturale. Qwen interpreta soltanto il testo della query. Le immagini non vengono riesaminate per cercarle.

Nell’Assistente puoi inviare un’immagine temporanea e fare una domanda. **Salva nel catalogo** è un comando separato. Musica e widget mantengono il loro percorso esistente.

## Modello esplicito

Il candidato predefinito è `qwen3-vl:2b-instruct`, configurabile con `REGISTA_QWEN_MODEL` oppure `qwen_model` nel `settings.json` desktop. Serve il tag esatto: nessun modello alternativo viene scelto automaticamente e nessun modello viene scaricato all’avvio.

Su questo PC è stato installato e provato `qwen3-vl:2b-instruct` Q4_K_M. Il tag esatto e il digest vengono verificati prima e dopo ogni annotazione. I tag non supportati dalla descrizione e i duplicati vengono esclusi dal risultato salvato; questo controllo non garantisce che la descrizione visiva sia corretta. [Prova su venti immagini locali, tag ed errori osservati](docs/prova-qwen-20-foto.md).

L'attesa massima per una risposta locale è di **5 minuti** per impostazione predefinita. `REGISTA_INFERENCE_TIMEOUT` permette di cambiarla in secondi; `0` disattiva il timeout della risposta. Il limite comprende tutta la risposta di Qwen, esclusa l'attesa del turno GPU. Timeout e risposte invalide lasciano la foto **Da catalogare**, con motivo salvato e riprova esplicita. Il budget della risposta è distinto dal tempo e rimane di 4.096 token.

I tag coprono soggetti, quantità esplicite (come `due gatti`), colori e dettagli visibili, senza quota fissa. Quantità e colori possono essere ricavati anche dalla descrizione, mantenendo tag generali e specifici distinti. Gli equivalenti `2 gatti` / `due gatti` vengono trattati come la stessa quantità.

## Originali, doppioni e stato delle foto

Ogni originale viene conservato prima dell'analisi in uno ZIP verificato con SHA-256, nella cartella `backup-originali` accanto al database del catalogo. Copie identiche condividono un solo ZIP. Le nuove importazioni non salvano un secondo file identico e il telefono non reinvia un contenuto già ricevuto e verificato.

Le importazioni gestite da Regista entrano in `Importate dal telefono/Da catalogare` e passano a `Classificate` quando l'analisi riesce. Le cartelle sorgenti del PC mantengono la loro struttura. Nel Catalogo trovi filtri per classificate, da catalogare ed errori, più un elenco separato degli originali ancora da trasferire dal telefono. Dalla scheda della foto puoi scaricare lo ZIP originale.

I byte originali, inclusi i metadati incorporati, restano invariati. Per proteggere i backup anche da un guasto del disco, copia `backup-originali` su un'altra unità. [Flusso, recupero e limiti](docs/originali-e-classificazione.md).

## Avvio e distribuzione

Lo stack rimane FastAPI, React/Vite e desktop Python con pywebview. Il backend parte con `uvicorn main:app` da `app/`, indicando `PHOTOS_DIR`, `INDEX_DIR`, `PAGE_DIR` e `MUSIC_DIR` secondo l’installazione. `app/desktop.py` conserva l’avvio della finestra e l’opzione `--no-window`. Non è stato introdotto Tauri.

Gli script esistenti `run.ps1`, `tools/desktop.ps1`, `tools/package.ps1` e `android.ps1 build` mantengono i rispettivi ruoli. L’installer accetta `-QwenModel` e mostra/conferma gli eventuali download; non scarica CLIP o modelli per il telefono. Desktop e APK vanno aggiornati insieme: i vecchi client foto ricevono “aggiornamento richiesto”. Pairing, certificati e revoca rimangono necessari.

Il servizio lavora solo con PC acceso e non sospeso. Chiudere la finestra desktop arresta il servizio; una nuova modalità tray e l’avvio con Windows non sono ancora implementati.

## Verifiche e documentazione

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# In web/, con Node disponibile:
node node_modules/typescript/bin/tsc -b
node node_modules/vitest/vitest.mjs run
node node_modules/vite/bin/vite.js build
node node_modules/vite/bin/vite.js build --config vite.telefono.config.ts
```

- [Piano originale](docs/piano-catalogo-qwen.md)
- [Implementazione, configurazione, diagnostica e limiti di collaudo](docs/catalogo-qwen-stato.md)
- [Istruzioni del percorso precedente, archiviate per rollback](docs/README-legacy.md)

Gli esperimenti in `training/` e i vecchi pesi restano recuperabili. Nessun training è necessario per il nuovo catalogo. Per il rollback temporaneo del backend e della vista Foto precedente: `REGISTA_PHOTO_CATALOG=0`.
