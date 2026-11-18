# Riconoscimento Qwen: verifica del 18 novembre 2026

Le prove non giustificano ancora un cambio di modello o di prompt nell'app. È stato mantenuto `qwen3-vl:2b-instruct`, con lo stesso prompt e gli stessi parametri. Non è stato svolto addestramento.

## Altre dieci immagini

[Tag, descrizioni e tempi per ciascuna foto](prova-qwen-altre-10-foto.md). Sono le immagini pubbliche `010.jpg`–`019.jpg` già presenti in `foto/esempi`, diverse dalle venti del [collaudo precedente](prova-qwen-20-foto.md). RTX 3050 Ti Laptop, 4 GB; Ollama già avviato e modello già in memoria. Nessuna foto personale coinvolta.

Mediana **5,02 secondi**, minimo 3,72, massimo 5,79. L'elaborazione dell'input ha richiesto circa 1,00–1,22 secondi e la generazione 2,52–4,59; il caricamento era trascurabile perché il modello era già presente in memoria. Non è una misura dell'avvio a freddo né una stima per immagini a piena risoluzione.

Dieci risposte sono state accettate dal parser, ma ci sono problemi concreti:

- `010.jpg`: «carpione» senza un tag generale «pesce». Il controllo cerca una parola precisa e segnala la mancanza del tag, non prova che il modello non abbia riconosciuto un pesce.
- `011.jpg`: cane e bottiglia individuati, ma razza e «spiaggia» non sono giustificate. Un controllo lessicale superato non rende corretta tutta la descrizione.
- `013.jpg`: «macchina da taglio a serra» invece di motosega.
- `015.jpg`: lo strumento musicale è chiamato «tubo».
- `017.jpg`: quattro distributori nella risposta, tre nella foto. Il filtro conserva coerentemente un conteggio che è già sbagliato nella descrizione; non può correggere il contenuto visivo.
- `019.jpg`: la copertura dorata è ambigua. Il primo riferimento vietava il nome «paracadute» con eccessiva sicurezza. Dopo un'ispezione separata è stato corretto il solo riferimento e sono stati riapplicati i controlli alle stesse risposte, senza nuove chiamate Qwen. Non viene conteggiato come errore visivo dimostrato.

Le classi del dataset non sono una verità sufficiente per i singoli ritagli: per esempio `015.jpg` non va obbligatoriamente chiamata «corno francese» solo perché proviene da quel gruppo. I controlli sono piccoli requisiti sui tag, non una percentuale di accuratezza e non un giudizio completo sulla foto.

## Confronti esplorativi sulle foto difficili

Otto foto già esaminate (`003`, `005`, `102`, `103`, `105`, `109`, `001`, `006`) sono state usate per provare istruzioni brevi, inglese e italiano, e una traduzione successiva senza immagine. Non sono un campione indipendente e i risultati non sono confrontabili con un benchmark completo di catalogazione.

- Con un'osservazione breve in inglese il 2B nomina correttamente «chainsaw» e «French horn». La traduzione italiana successiva può però introdurre «mulinello», «cornetto francese» o «cornamusa francese».
- Anche istruzioni di catalogazione in inglese con JSON italiano mantengono nomi errati come «macchina da taglio» e «tromba».
- Il `qwen3.5:4b` già installato riconosce meglio le motoseghe e il registratore in alcune osservazioni italiane, ma chiama il corno «arpa francese» oppure suggerisce «tromba o clarinetto». Tradurre l'osservazione inglese con questo modello non elimina gli errori: «chainsaw» diventa anche «asportatrice».

Il digest del 4B provato è `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`. Non è stato attivato come default e non sono stati scaricati nuovi modelli.

Il confronto inglese/italiano sulle medesime foto può riusare gli embedding delle immagini e la cache del prompt. Tempi molto più bassi nella seconda passata non dimostrano che la lingua sia più veloce. Gli artefatti esplorativi restano locali in `build/qwen-recognition-probe`.

## Modifiche applicate

- Una risposta con zero tag viene rifiutata: il job resta da catalogare con motivo e conserva il backup ZIP. Il modello può ancora sbagliare una descrizione con tag validi; questa correzione non certifica la correttezza semantica.
- Le nuove annotazioni conservano anche `_ollama`: tempi restituiti dal servizio per caricamento, input e generazione, numero di token di input/cache/output. Metriche assenti o invalide non vengono registrate come zeri misurati. Le annotazioni esistenti non sono ricalcolate automaticamente.
- `app/catalog_benchmark.py` esegue una selezione esplicita in una nuova cartella di risultati, fuori dalle immagini. Non apre il catalogo dell'utente, non modifica gli originali, non scarica modelli e non invia i riferimenti al modello. Salva un checkpoint dopo ogni foto; errori singoli non fermano le altre e un cambio di digest arresta la prova.

## Ripetere la prova

Dalla radice del repository, con il modello esatto già installato:

```powershell
.\.venv\Scripts\python.exe app/catalog_benchmark.py run --images foto/esempi --suite tests/fixtures/qwen-foto-010-019.json --output build/nuova-prova-qwen
```

La cartella di output deve essere nuova. Le dieci immagini devono già essere disponibili localmente: sono escluse da Git. Il modello è quello esplicito dell'app, configurabile tramite `REGISTA_QWEN_MODEL` prima dell'avvio del comando; non ci sono fallback.

Per rigenerare il resoconto salvato senza nuove analisi:

```powershell
.\.venv\Scripts\python.exe app/catalog_benchmark.py report build/qwen-catalog-010-019-20261118/results.json --output build/resoconto-qwen.md
```

`report --suite tests/fixtures/qwen-foto-010-019.json` riapplica esplicitamente i riferimenti aggiornati alle stesse foto nello stesso ordine. Mantiene intatte le risposte originali e segnala nel Markdown la rivalutazione dei riferimenti. È così che è stato prodotto il documento delle dieci foto dopo la correzione del riferimento ambiguo.

Validazione: **486 test backend superati**, inclusi archivio e stato di errore per risposte senza tag, telemetria, selezione isolata, rifiuto di percorsi esterni/duplicati, checkpoint, replay e arresto per cambio del modello. Le modifiche non toccano frontend o Android.
