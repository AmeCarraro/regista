# Il modello di Regista

L'obiettivo è usare Regista a voce su Android per ritrovare foto, catalogarle e ascoltare musica. Le foto di prova e i dialoghi del progetto bastano per sviluppare le prime versioni.

## Tappe

1. **Capire i comandi.** Addestrare sulla GPU un modello con pesi inizializzati da zero. Il modello riconosce ricerca foto, aggiunta o rimozione di un tag e riproduzione musicale. Estrae tag, titolo e artista dalla frase originale. Valutare azione e argomenti esatti con frasi e nomi tenuti fuori dall'addestramento, poi con richieste scritte a mano.
2. **Catalogo e selezione.** Aggiungere tag multipli per foto, distinguendo tag manuali, suggerimenti visivi e luoghi da GPS. Applicare una modifica all'intera selezione dopo la conferma, registrarla per consentire l'annullamento e ritrovare subito le foto tramite il nuovo tag.
3. **Prima demo nell'app.** Esportare il modello, verificare che l'inferenza dia gli stessi comandi e collegarla alla galleria dimostrativa e al lettore musicale. Misurare dimensione, RAM e latenza sul Redmi. Collegare il microfono alla trascrizione e riusare lo stesso modello dei comandi.
4. **Tag visivi.** Addestrare una rete visiva piccola su immagini di prova o con licenza adatta. Catalogare ogni foto nuova o modificata e salvare i tag per le ricerche successive. Valutare precisione dei tag, tempo d'indicizzazione e rispetto delle correzioni manuali.
5. **Risposte generate.** Addestrare da zero un piccolo modello testuale per risposte e chiarimenti in italiano, usando dialoghi del progetto. Passargli i risultati già verificati da Regista e misurare quanto fedelmente li restituisce. Misurare anche il costo sul Redmi e valutare una versione più capace sul PC con gli stessi comandi.

Ogni tappa può essere provata separatamente. Quando una versione è verificata, il codice, la configurazione e le misure permettono di riprodurla e confrontarla con la successiva.

## Prima prova sulla GPU

Dalla cartella del repository, con Python 3.11 disponibile in `.venv`. Le librerie di addestramento vanno in `build/training-libs`, separate da quelle dell'app. Per la RTX 3050 Ti di questo PC usiamo PyTorch 2.9.1 con CUDA 12.8.

```powershell
.venv/Scripts/python.exe -m pip install --target build/training-libs torch==2.9.1 --index-url https://download.pytorch.org/whl/cu128
$env:PYTHONPATH = (Resolve-Path build/training-libs).Path
.venv/Scripts/python.exe training/commands.py --out build/commands-v3 train
.venv/Scripts/python.exe training/commands.py --out build/commands-v3 benchmark --suite fresh
.venv/Scripts/python.exe training/commands.py --out build/commands-v3 ask 'mostrami le foto dei cani' 'metti Giappone su tutte queste foto'
```

Il modello usa un piccolo insieme di convoluzioni sul testo e due uscite, una per il comando e una per marcare i termini da estrarre. La cartella indicata da `--out` contiene il checkpoint e le metriche. Il punteggio esatto richiede che siano giusti sia il comando sia tutti i suoi argomenti. Il benchmark usa richieste scritte a mano tenute fuori dall'addestramento.

## Risultati sulla RTX 3050 Ti

| Misura | Versione precedente | Nuova versione |
| --- | ---: | ---: |
| Esempi sintetici di addestramento | 3.547 | 6.725 |
| Comandi esatti nel test sintetico | 191/383 | 176/383 |
| Comandi esatti nel benchmark scritto a mano | 17/48 | 28/48 |
| Proposte di modifica tag errate nel benchmark scritto a mano | 12 | 7 |
| Dimensione del checkpoint | 185.743 byte | 208.079 byte |

La nuova versione, con 49.017 parametri, riconosce «mostrami le foto dei cani» e risponde con una richiesta di chiarimento in tutte le 10 richieste incomplete, negate o fuori ambito del benchmark. Una correzione in fase di estrazione separa «Imagine» da «John Lennon» e porta i comandi musicali esatti da 4 a 5 su 10 nel benchmark scritto a mano. Le misure includono questa correzione, provata con lo stesso checkpoint. La qualità resta da migliorare prima di collegare il modello alle operazioni dell'app.

### Quanto testo nascondere durante l'addestramento

`train --slot-dropout` regola la probabilità di nascondere ciascuna parola di un tag, titolo o artista durante l'addestramento. Abbiamo confrontato tre valori a parità di dati, seed 42 e 20 epoche, scegliendo per ciascuna prova il checkpoint con più comandi esatti in validazione.

| Probabilità | Validazione sintetica | Test sintetico | Test scritto a mano | Proposte di modifica tag errate nel test scritto a mano |
| --- | ---: | ---: | ---: | ---: |
| 0,35 | 152/294 | 187/383 | 26/48 | 7 |
| 0,55 (predefinita) | 138/294 | 176/383 | 28/48 | 7 |
| 0,80 | 153/294 | 179/383 | 25/48 | 9 |

Il checkpoint con 0,55 ha completato più richieste scritte a mano in questo confronto. Le alternative si riproducono dal commit `3ac11e2` usando `--slot-dropout 0.35` o `--slot-dropout 0.8` e cartelle di output separate.

### Frasi colloquiali e richieste negate

La terza prova aggiunge 1.429 esempi sintetici di addestramento con nomi composti, frasi colloquiali e richieste negate o incomplete. Conserva i 6.725 esempi precedenti e gli stessi gruppi di validazione e test sintetici. La rete ha la stessa struttura, con un vocabolario più ampio. Il checkpoint scelto in validazione è quello dell'epoca 12 su 20, con seed 42 e `--slot-dropout 0.55`.

| Misura | Checkpoint precedente | Corpus ampliato |
| --- | ---: | ---: |
| Comandi esatti nel test sintetico | 176/383 | 206/383 |
| Comandi esatti nel primo test scritto a mano | 28/48 | 25/48 |
| Azioni riconosciute nel nuovo test scritto a mano | 36/49 | 41/49 |
| Comandi esatti nel nuovo test scritto a mano | 20/49 | 19/49 |
| Azioni proposte quando serviva un chiarimento nel nuovo test | 4 | 2 |
| Dimensione del checkpoint | 208.079 byte | 227.919 byte |

Il nuovo test usa 49 richieste scritte a mano, preparate separatamente e controllate per evitare duplicati con l'addestramento. Il corpus ampliato migliora il riconoscimento dell'azione, mentre l'estrazione degli argomenti resta fragile, soprattutto per la musica. Teniamo il checkpoint precedente come riferimento per la demo. La prossima prova dovrebbe misurare l'effetto di addestrare la rete a riconoscere l'inizio e la fine degli argomenti.

### Inizio e fine degli argomenti

`train --boundaries` addestra la rete a prevedere l'inizio e la fine di ciascun argomento e a riconoscere quando è assente. Il testo tra i due punti viene copiato dalla richiesta originale. Se i confini di un argomento sono incoerenti o due argomenti si sovrappongono, il modello chiede un chiarimento. I checkpoint precedenti continuano a usare l'estrazione per parola.

| Misura | Estrazione per parola | Inizio e fine espliciti |
| --- | ---: | ---: |
| Comandi esatti in validazione | 160/294 | 187/294 |
| Comandi esatti nel test sintetico | 206/383 | 219/383 |
| Rimozioni di tag esatte nel test sintetico | 18/80 | 35/80 |
| Comandi esatti nel primo test scritto a mano | 25/48 | 26/48 |
| Comandi esatti nel nuovo test scritto a mano | 19/49 | 18/49 |
| Azioni proposte quando serviva un chiarimento nel nuovo test | 2 | 4 |
| Dimensione del checkpoint | 227.919 byte | 230.027 byte |

Stessi 8.154 esempi, seed 42 e 20 epoche sulla RTX 3050 Ti. La prova con confini espliciti ha scelto il checkpoint dell'epoca 8 in validazione. Resta sperimentale perché sul nuovo test scritto a mano propone più azioni quando dovrebbe chiedere chiarimenti.

```powershell
.venv/Scripts/python.exe training/commands.py --out build/commands-boundaries train --boundaries
.venv/Scripts/python.exe training/commands.py --out build/commands-boundaries benchmark --suite fresh
```

### Quando chiedere un chiarimento prima di modificare i tag

`calibrate` sceglie una soglia sul punteggio dell'azione usando solo la validazione sintetica. Cerca di ridurre le proposte di modifica errate mantenendo almeno il 90% di quelle corrette. `ask` e `benchmark` accettano `--edit-confidence` per provare la soglia. Il valore predefinito è zero.

Per il checkpoint `commands-v2`, la soglia scelta è 0,8. Nella validazione le modifiche errate scendono da 59 a 48 e quelle corrette da 50 a 48. Nel nuovo test scritto a mano le modifiche errate scendono da 9 a 7, mentre i comandi completi scendono da 20 a 19 su 49. Le azioni proposte dove serviva un chiarimento restano quattro. Il punteggio aiuta a filtrare qualche errore, ma non basta per decidere se applicare una modifica.

```powershell
.venv/Scripts/python.exe training/commands.py --out build/commands-v2 calibrate
.venv/Scripts/python.exe training/commands.py --out build/commands-v2 benchmark --suite fresh --edit-confidence 0.8
```

### Più modi di chiedere foto e musica

`train --references` aggiunge 768 frasi con verbi, riferimenti alla galleria, titoli e artisti diversi. Il confronto usa la stessa rete per parola, il seed 42 e 20 epoche sulla RTX 3050 Ti. Il checkpoint selezionato in validazione è quello dell'epoca 16.

| Misura | Corpus da 8.154 esempi | Corpus con 768 frasi in più |
| --- | ---: | ---: |
| Comandi esatti nel test sintetico | 206/383 | 172/383 |
| Comandi musicali esatti nel test sintetico | 18/60 | 28/60 |
| Comandi esatti nel primo test scritto a mano | 25/48 | 29/48 |
| Comandi esatti nel nuovo test scritto a mano | 19/49 | 20/49 |
| Comandi musicali esatti nel nuovo test scritto a mano | 1/10 | 4/10 |
| Modifiche tag errate nel nuovo test scritto a mano | 8 | 6 |
| Dimensione del checkpoint | 227.919 byte | 256.655 byte |

Il vantaggio sulla musica convive con un calo su ricerca e modifiche ai tag nel test sintetico. La variante resta opzionale.

```powershell
.venv/Scripts/python.exe training/commands.py --out build/commands-references train --references
.venv/Scripts/python.exe training/commands.py --out build/commands-references benchmark --suite fresh
```

### Catalogo dei tag manuali

`app/tags.py` salva più tag per foto in SQLite. Aggiunte e rimozioni su una selezione avvengono in un'unica transazione. Il catalogo mantiene la grafia del tag e cerca anche con variazioni di maiuscole o di rappresentazione Unicode. Restituisce gli identificativi effettivamente cambiati, così l'app potrà registrare e annullare solo quelle modifiche.

Il catalogo è verificato in isolamento, prima del collegamento alla galleria. L'integrazione dovrà usare un'identità che sopravvive allo spostamento di una foto: l'indice attuale ricava il suo identificativo dal percorso relativo.

### Esito della prova sulle parole sconosciute

Un addestramento da 20 epoche sulla RTX 3050 Ti ha distinto parole sconosciute brevi, medie, lunghe e numeriche. Rispetto a `commands-v3`, il nuovo test scritto a mano è rimasto a 19/49 comandi esatti, con proposte di modifica tag errate salite da 8 a 10. Sul test sintetico i comandi esatti sono scesi da 206 a 165 su 383. Abbiamo mantenuto la rappresentazione precedente.

### Esportazione per l'app

`export_commands.py` genera `commands.onnx` e `commands.json`, che contiene il vocabolario, il formato degli ingressi e delle uscite e l'hash del modello. L'esportazione verifica i punteggi e confronta i comandi decodificati da PyTorch e ONNX Runtime prima di scrivere i file. Su CPU Windows i tre checkpoint `commands-v2`, `commands-references` e `commands-boundaries` hanno prodotto gli stessi comandi su 481 ingressi ciascuno. I file ONNX occupano rispettivamente 199.766, 243.926 e 220.069 byte. Peso e tempi effettivi su Android sono ancora da misurare.

```powershell
.venv/Scripts/python.exe -m pip install --target build/training-libs onnx==1.19.1 ml-dtypes==0.5.4
$env:PYTHONPATH = (Resolve-Path build/training-libs).Path
.venv/Scripts/python.exe training/export_commands.py build/commands-v2 --out build/onnx-v2
```

### Demo del comando e del catalogo

`app/command_model.py` esegue il modello esportato con ONNX Runtime. Addestramento, esportazione e demo condividono il tokenizer e l'estrazione degli argomenti. La demo da terminale lavora su tre foto fittizie e usa un catalogo separato. Mostra le foto selezionate e il tag prima di chiedere conferma. In prova, rifiutare ha lasciato il catalogo vuoto. Confermare ha associato `Giappone` a due foto, che il comando di ricerca ha poi ritrovato.

```powershell
.venv/Scripts/python.exe training/demo_catalog.py build/onnx-v2 'metti Giappone su tutte queste foto' --select 1 2
.venv/Scripts/python.exe training/demo_catalog.py build/onnx-v2 'fammi vedere le foto di Giappone'
```

### Quanto conta l'inizializzazione

Con il corpus da 8.922 esempi e la stessa rete, abbiamo ripetuto 20 epoche sulla RTX 3050 Ti con i seed 7, 17 e 29. I comandi esatti in validazione sono stati rispettivamente 173, 175 e 185 su 294, contro 165 con il seed 42. La selezione si è basata sulla validazione.

Il seed 29 passa da 20 a 24 comandi esatti su 49 nel nuovo test scritto a mano e da 4 a 7 rimozioni corrette su 9. Nel primo test scritto a mano scende da 29 a 22 su 48. Nel nuovo test propone quattro azioni quando serviva un chiarimento, contro due con il seed 42. Questa variabilità è un motivo per confrontare più addestramenti prima di promuovere un checkpoint.

```powershell
.venv/Scripts/python.exe training/commands.py --out build/commands-seed-29 train --references --seed 29
.venv/Scripts/python.exe training/commands.py --out build/commands-seed-29 benchmark --suite fresh
```

### Prova comandi nella pagina di Regista

Con il frontend compilato e un pacchetto ONNX disponibile, questa modalità mostra «Prova comandi» nel menu del PC. La demo lavora su nomi di foto fittizie e scrive i tag in `demo-tags.sqlite` nella cartella d'indice scelta. La richiesta produce solo un'anteprima. Il catalogo cambia dopo il clic su «Conferma».

```powershell
$env:REGISTA_COMMAND_BUNDLE = (Resolve-Path build/onnx-v2).Path
$env:PAGE_DIR = (Resolve-Path web/dist).Path
$env:INDEX_DIR = Join-Path (Resolve-Path build).Path 'demo-web-index'
.venv/Scripts/python.exe -m uvicorn main:app --app-dir app --host 127.0.0.1 --port 8097 --lifespan off
```

Apri `http://127.0.0.1:8097/`, seleziona due voci e prova «metti Giappone su tutte queste foto». Dopo la conferma, «fammi vedere le foto di Giappone» mostra le due voci. In questa configurazione il servizio non avvia l'indicizzazione delle foto.

### Anteprima offline su Android

Imposta `REGISTA_COMMAND_BUNDLE` prima di compilare l'APK per includere `commands.onnx` e `commands.json` nella versione sperimentale. La scheda «Telefono» mostra «Prova comandi offline». Il modello gira nel processo Android e mostra l'azione e i nomi estratti. L'anteprima è di sola lettura e accetta testo scritto.

```powershell
$env:REGISTA_COMMAND_BUNDLE = (Resolve-Path build/onnx-v2).Path
.\android.ps1 build
```

Su un emulatore Android 13 sono stati riconosciuti `cani`, `Imagine` con artista `John Lennon`, e il tag `Giappone`. L'ultimo comando è stato verificato in modalità aereo. La misura di RAM e latenza sul Redmi resta da fare.

### Esportazione compatta

`export_commands.py --compact` salva i pesi ONNX in FP16 e li converte in FP32 per il calcolo. I tre checkpoint hanno mantenuto tutti i comandi decodificati sulle stesse 481 richieste di verifica per checkpoint. Il modello `v2` è passato da 199.766 a 102.507 byte. Il comando per `Imagine` di `John Lennon` ha restituito titolo e artista corretti anche nell'APK compatto sull'emulatore Android 13 in modalità aereo.

```powershell
.venv/Scripts/python.exe training/export_commands.py build/commands-v2 --out build/onnx-v2-compact --compact
$env:REGISTA_COMMAND_BUNDLE = (Resolve-Path build/onnx-v2-compact).Path
.\android.ps1 build
```
