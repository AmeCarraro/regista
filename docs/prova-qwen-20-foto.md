# Qwen: venti immagini pubbliche già presenti

Prova locale del 17 novembre 2026. Due immagini per ciascuna delle dieci categorie, selezionate da `foto/esempi` (200 immagini).

I tempi sono quelli delle chiamate Qwen originali. I tag sono stati poi ricalcolati dalle risposte JSON salvate con il filtro singolare/plurale aggiornato: nessuna nuova analisi visiva e nessuna modifica alle immagini o al database della misura originale.

Mediana 5.28 s; massimo 11.59 s sulla prima chiamata; venti risultati salvati e venti ZIP originali verificati. Ripetere la registrazione ha richiesto zero chiamate al modello.

| File | Categoria di riferimento | Tempo Qwen | Tag dopo il filtro corretto |
|---|---|---:|---|
| 000.jpg | pesci | 11.59 s | uomo, pesce, fiume, acqua, giacca da pesca, cappello, due pesci |
| 001.jpg | cani | 6.16 s | cucciolo, spaniel, tavolo, pavimento di legno, giornali o riviste, collare rosso |
| 002.jpg | registratori a cassette | 5.26 s | registratore audio, microfono, cassetto per cassette, califone, 1350 av, cassette, cavo |
| 003.jpg | motoseghe | 5.76 s | uomo, scopa da legna, legna, albero, tronco di legno |
| 004.jpg | chiese | 5.63 s | chiesa, arco, finestre ad arco |
| 005.jpg | corni musicali | 5.25 s | tromba, francese, dorato, tavola bianca, vegetazione verde |
| 006.jpg | camion dei rifiuti | 5.23 s | camion dei rifiuti, cassone blu, cabina bianca |
| 007.jpg | distributori carburante | 6.21 s | pompa a benzina, vintage, diesel, stella rossa, manopola nera, pompa a benzina rossa |
| 008.jpg | palline da golf | 3.47 s | pallina da golf, carta con testo, due palline da golf, palline da golf bianche |
| 009.jpg | paracadute e teli da gioco | 4.13 s | paracadute, persona, cielo |
| 100.jpg | pesci | 5.30 s | uomo, pesce, cappello, maglietta, vegetazione verde |
| 101.jpg | cani | 5.16 s | cucciolo di cane, box di legno, materasso blu, pelliccia marrone e bianca |
| 102.jpg | registratori a cassette | 6.47 s | computer portatile, cassetta audio, griglia di perforazioni, indicatore bianco, testo stampato |
| 103.jpg | motoseghe | 6.93 s | uomo, serratura, acqua, casco giallo, occhiali da sole, maglietta rossa, serratura di colore rosso, acqua che cade |
| 104.jpg | chiese | 7.66 s | chiesa, torre, lampada a sospensione, nuvole, effetto artistico |
| 105.jpg | corni musicali | 4.96 s | tromba, bronzo, metallo, riflessione |
| 106.jpg | camion dei rifiuti | 5.23 s | camion, rifiuti, arancione, pubblicità, albero, strada, alberi verdi |
| 107.jpg | distributori carburante | 6.05 s | stazione di benzina, bp, auto in movimento |
| 108.jpg | palline da golf | 3.63 s | palla da golf, campo verde |
| 109.jpg | paracadute e teli da gioco | 4.80 s | parapendio, bambini |

## Errori osservati

- `003.jpg` e `103.jpg`: la motosega è stata chiamata rispettivamente «scopa da legna» e «serratura».
- `005.jpg` e `105.jpg`: il corno è stato chiamato «tromba».
- `102.jpg`: il registratore a cassette è stato descritto come un computer portatile.
- `109.jpg`: il telo da gioco dei bambini è stato chiamato «parapendio».

La validità del JSON e il completamento tecnico non equivalgono alla correttezza visiva. Il filtro recupera varianti comuni singolare/plurale e conteggi già presenti nel testo; non corregge una descrizione sbagliata del modello. Il conteggio di parole chiave nel JSON originale non è una percentuale di accuratezza.

Le immagini sono piccole, circa 224×224 pixel, e appartengono a dieci gruppi: questo campione non rappresenta una libreria fotografica completa.

La correzione del filtro è stata verificata su tutte le venti risposte già salvate e con 474 test backend superati. Il runtime del pacchetto PC è stato aggiornato e ha verificato il recupero di `due palline da golf`. Non sono stati cambiati modello, prompt, parametri di generazione o immagini; `_tag_filter_version=italian-forms-1` identifica il nuovo confronto. Le foto già catalogate conservano i risultati precedenti finché non viene richiesta una rianalisi; la rielaborazione senza nuova visione descritta sopra è stata eseguita soltanto nel benchmark.
