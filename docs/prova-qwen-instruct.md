# Prova locale Qwen Instruct e correzione del catalogo

Questa pagina conserva la prima correzione (`catalog-it-2`). Il timeout è stato successivamente riportato a cinque minuti e i tag arricchiti con quantità: [stato attuale, ZIP originali e nuove prove](originali-e-classificazione.md).

17 novembre 2026. Tre foto pubbliche, nessuna foto personale. NVIDIA RTX 3050 Ti Laptop 4 GB, Ollama 0.40.5, `qwen3-vl:2b-instruct` Q4_K_M, digest `afc393e3572c07db0bc84aa460d928a16c75f3fbb9ca9e0dccc4fbd2dafb573e`. Immagini orientate e adattate a 512 pixel massimi; contesto 6.144 token. Il modello usa GPU e RAM, non risiede interamente in VRAM.

## Problema riscontrato

La configurazione precedente usava temperatura zero, schema con categoria espressa da un pattern e massimo 1.800 token. La prima foto del cane ha richiesto 9,44 secondi, inclusi 5,06 di caricamento del modello. I tag restituiti erano `cane`, `bianco`, `pelo folto`, `prato verde`, `animale`. Le foto dei gatti e della stanza si sono fermate per il limite di token dopo 31,25 e 33,69 secondi; sono state rifiutate, senza salvare un'annotazione valida. Non era un timeout di 30 secondi.

Nella prova diagnostica breve precedente, limitata a otto tag, i risultati erano:

| Foto | Tag restituiti, comprese ripetizioni ed errori |
| --- | --- |
| Due gatti | gatti, divano, telecomandi, cane, cane, cane, cane, cane |
| Cane bianco | cane bianco, pelo folto, sedia, prato, vegetazione verde, animale, cane, pelo |
| Stanza | soggiorno, tavolo da pranzo, tv, camino, donna, pareti gialle, tavolo da pranzo, cucina |

Erano presenti categorie errate: per esempio `divano` e `telecomandi` erano classificati come colori. La sola validazione JSON non verificava la coerenza fra descrizione e tag.

## Modifica applicata

Il timeout di risposta locale passa da 300 a 3.600 secondi. `REGISTA_INFERENCE_TIMEOUT=0` elimina il timeout della risposta. Le lease vengono rinnovate ogni minuto per mantenere la proprietà dei lavori lunghi. Connessione e invio conservano timeout separati.

Il budget delle annotazioni passa da 1.800 a 4.096 token. Si usano categorie enum e il campionamento visivo suggerito dagli [autori di Qwen](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct#generation-hyperparameters): temperatura 0,7, top-p 0,8, top-k 20, repetition penalty 1 e presence penalty 1,5. Il seed 42 è registrato con il risultato. Lo schema viene incluso nel testo oltre che nel decoder, come raccomanda la [documentazione Ollama](https://docs.ollama.com/capabilities/structured-outputs).

Il prompt richiede descrizione e tag italiani, senza numero obbligatorio di tag. I tag devono essere estratti dalla descrizione. Prima del salvataggio vengono rimossi duplicati normalizzati e termini assenti come parole/espressioni complete nella descrizione; la risposta originale e le ragioni degli scarti restano nel risultato diagnostico. Se tutti i tag proposti sono incoerenti, l'annotazione viene rifiutata. Questo controllo riduce le aggiunte incoerenti, ma non verifica la verità della descrizione rispetto all'immagine.

## Risultato salvato dopo la correzione

È stato eseguito il percorso effettivo `IndexJobs` → `PhotoAnnotator` → commit SQLite, su un database di prova separato. Tempi con modello già caricato, comprensivi di preparazione, controlli digest e scrittura nel catalogo.

| Foto | Tempo | Tag effettivamente salvati |
| --- | ---: | --- |
| Due gatti | 3,275 s | gatti, riposo, telecomandi |
| Cane bianco | 3,933 s | bianco, cane, prato |
| Stanza | 6,179 s | camino, cucina, finestre, parete verde, pavimento in legno, sedie, stanza, tavolo, vaso di fiori |

Tre annotazioni completate, nessun errore. Le ricerche salvate `cani`, `gatti` e `televisore` hanno restituito rispettivamente cane, gatti e stanza. `televisore` corrisponde alla descrizione salvata. Una nuova scansione non ha creato lavoro né chiamato Qwen.

Suite backend completa: **439 test superati**. Le regressioni includono tag duplicati/assenti dalla descrizione, corrispondenze solo a parole complete, attesa HTTP disattivata, rinnovo delle lease durante un'inferenza sospesa e annullamento senza lasciare un lavoro o un'inferenza orfani. Questi test verificano il software, non l'accuratezza del modello.

Restano limiti visivi: la descrizione dei gatti parla di un cuscino, mentre la scena mostra un divano con copertura/cuscini; nella stanza la categoria `object` per `cucina` è discutibile. Tag salienti possono mancare. Non è una misura dell'accuratezza generale e non garantisce tempi o qualità su una libreria intera. Servono ancora foto più varie, con etichette di riferimento.

Gli artefatti dettagliati sono locali e ignorati da Git in `build/qwen-instruct-benchmark/`: risposte iniziali in `results.json`, diagnostica breve in `compact-results.json`, ultima prova completa indicata da `fixed-latest.json`, con database e risposte complete nella sottocartella corrispondente. Le vecchie annotazioni non vengono riesaminate automaticamente: usare **Rianalizza selezione** per applicare la correzione alle foto già elaborate.

Fonti delle immagini: [cane, PyTorch Hub](https://raw.githubusercontent.com/pytorch/hub/master/images/dog.jpg), [gatti, COCO](http://images.cocodataset.org/val2017/000000039769.jpg), [stanza, COCO](http://images.cocodataset.org/val2017/000000000139.jpg).
