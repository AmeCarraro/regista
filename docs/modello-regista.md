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
.venv/Scripts/python.exe training/commands.py --out build/commands-v2 train
.venv/Scripts/python.exe training/commands.py --out build/commands-v2 benchmark
.venv/Scripts/python.exe training/commands.py --out build/commands-v2 ask 'mostrami le foto dei cani' 'metti Giappone su tutte queste foto'
```

Il modello usa un piccolo insieme di convoluzioni sul testo e due uscite, una per il comando e una per marcare i termini da estrarre. La cartella indicata da `--out` contiene il checkpoint e le metriche. Il punteggio esatto richiede che siano giusti sia il comando sia tutti i suoi argomenti. Il benchmark usa richieste scritte a mano tenute fuori dall'addestramento.

## Risultati sulla RTX 3050 Ti

| Misura | Versione precedente | Nuova versione |
| --- | ---: | ---: |
| Esempi sintetici di addestramento | 3.547 | 6.725 |
| Comandi esatti nel test sintetico | 191/383 | 173/383 |
| Comandi esatti nel benchmark scritto a mano | 17/48 | 27/48 |
| Proposte di modifica tag errate nel benchmark scritto a mano | 12 | 7 |
| Dimensione del checkpoint | 185.743 byte | 208.079 byte |

La nuova versione, con 49.017 parametri, riconosce «mostrami le foto dei cani» e risponde con una richiesta di chiarimento in tutte le 10 richieste incomplete, negate o fuori ambito del benchmark. Fatica ancora con titoli musicali, per esempio include «di» nel titolo di «riproduci Imagine di John Lennon». La qualità resta da migliorare prima di collegare il modello alle operazioni dell'app.
