# Backup completo dei media del telefono

19 novembre 2026 · APK 0.7.

In **Telefono → Impostazioni e backup → Sincronizza tutti i contenuti…**, una conferma esplicita avvia il backup di immagini, foto, audio e video. Non è un'operazione periodica e non cancella originali dal telefono. La classificazione AI resta separata e in pausa. Nell'APK 0.8 le impostazioni si aprono dal pulsante in alto nella scheda Telefono; dettagli su cartelle, USB e copertura sono sezioni espandibili.

## Copertura della scansione

La scansione consulta le raccolte Immagini, Audio e Video di MediaStore su tutti i volumi montati accessibili, incluse le schede SD visibili. Non usa un filtro DCIM, un album specifico o il filtro `IS_MUSIC`: considera anche audio che Android non classifica come canzoni.

Per file non indicizzati o cartelle con `.nomedia`, **Aggiungi una cartella** apre il selettore Android. Il backup successivo visita ricorsivamente le cartelle autorizzate e le loro sottocartelle. La selezione è impostata su contenuti locali; autorizzazioni revocate, documenti virtuali o cartelle non leggibili producono segnalazioni.

Non equivale a un'immagine completa del filesystem: Android protegge cartelle private di altre app, `Android/data`, `Android/obb` e alcune radici del selettore. I contenuti cloud non disponibili localmente non sono inclusi come se fossero presenti sul telefono. I file devono essere indicizzati oppure trovarsi nelle cartelle supplementari autorizzate. Non viene richiesto accesso root o debug USB.

Servono permessi completi per immagini, video e audio, oltre all'accesso alla posizione dei media per conservare gli originali con i metadati. Su Android 14+ la selezione limitata di alcune foto non viene presentata come accesso all'intera libreria; la richiesta distingue esplicitamente il permesso delle immagini selezionate.

## Doppioni, integrità e ripresa

Ogni avvio legge i contenuti accessibili e ne calcola SHA-256 sul telefono. Non salta un file soltanto perché nome o data sembrano invariati. La lettura locale per calcolare gli hash rimane necessaria anche quando sul PC non manca nulla.

Il telefono invia prima manifesti di massimo cento elementi con identità, nome, cartella, tipo, dimensione e hash. Il PC verifica i backup già presenti, inclusi gli ZIP del catalogo fotografico. Richiede soltanto i contenuti mancanti o con un backup non valido. Copie identiche con nomi o cartelle diversi conservano tutti i riferimenti, ma condividono un solo originale archiviato.

Ogni contenuto nuovo viene trasferito in streaming e conservato in un **ZIP per SHA-256**, con Zip64, verifica di dimensione, CRC e SHA-256 prima della conferma. Per i nuovi media il contenitore ZIP usa `ZIP_STORED`: audio e video sono spesso già compressi e non vengono ricodificati. Gli ZIP preesistenti restano invariati. Il limite tecnico per singolo file è 64 GiB, configurabile sul PC tramite `REGISTA_MEDIA_BACKUP_MAX_BYTES`.

I file sono sotto `INDEX_DIR/backup-originali/<prefisso>/<sha256>.zip`. Nome originale e byte recuperabili sono nel contenitore; i riferimenti completi alle cartelle e ai nomi delle copie sono conservati anche nei manifesti di sessione sotto `backup-originali/sessioni/<identità-telefono>/<sessione>.json`. Un giornale `.jsonl` registra i checkpoint durante l'operazione. Il registro operativo è `INDEX_DIR/media-backup.sqlite`.

Interruzioni, file modificati durante lettura o invio, errori di rete e permessi mancanti non vengono presentati come backup completo. Alla ripetizione vengono saltati gli ZIP già confermati. **Interrompi backup** chiude la richiesta attiva; un file non confermato viene verificato nuovamente alla prossima esecuzione. Gli originali sul telefono non vengono spostati o eliminati.

L'app deve restare aperta. Durante il backup tiene acceso il proprio schermo e sospende il normale scambio di foto; uscendo dall'app l'operazione viene interrotta. Alla fine ripristina il collegamento normale. I timeout ordinari del catalogo e dell'AI rimangono separati: i trasferimenti di backup grandi sono annullabili senza un limite arbitrario alla verifica dello ZIP.

## Collegamento tramite USB

Il canale implementato è la rete locale creata dal **tethering USB**, con lo stesso pairing TLS e certificato del collegamento Wi-Fi. La sola modalità USB ricarica/MTP non trasferisce dati per questa funzione.

1. Collegare telefono e PC con un cavo dati e attivare **Tethering USB** nelle impostazioni Android.
2. Aprire Regista sul PC con il collegamento telefono abilitato. La rilevazione delle interfacce private include la rete USB e la aggiorna anche se compare dopo l'avvio.
3. Collegare il telefono al PC su quella rete; la ricerca considera anche le interfacce USB/RNDIS/NCM. Se è già collegato via Wi-Fi, quel collegamento può rimanere preferito: per verificare il passaggio sul cavo, disattivare il Wi-Fi del telefono e ricollegarlo.
4. Controllare l'indirizzo del PC mostrato nelle impostazioni del backup, quindi avviare l'operazione.

Windows deve consentire la connessione a Regista sulla rete USB e sulla porta configurata, normalmente 8443. Non viene modificato automaticamente il firewall o attivato il tethering. La velocità effettiva dipende da cavo, porta, memoria, lettura per gli hash e verifiche sul PC; non è ancora stata misurata su un dispositivo reale.

## Recupero e verifica

Per recuperare un file, aprire il relativo ZIP ed estrarre il membro sotto `original/`. I manifesti permettono di ricostruire nomi e cartelle delle copie. Conservare l'intera cartella `backup-originali`, inclusa `sessioni`, su un altro disco protegge anche dal guasto del disco del PC. I nuovi ZIP di immagini di questo backup non avviano da soli la catalogazione: l'importazione foto e l'analisi rimangono comandi separati.

Quando viene richiesta successivamente l'importazione delle foto, un originale già presente in uno ZIP verificato viene ripristinato localmente sul PC, senza ritrasferirlo dal telefono. Un archivio corrotto richiede una nuova copia; un problema di spazio o formato durante il ripristino viene segnalato, senza richiedere inutilmente gli stessi byte.

Le API sono protette dal pairing e separate per telefono e sessione. Lo stato PC è disponibile in `/api/media-backup/status`; operazioni di scrittura rifiutate se l'archivio è configurato in sola lettura. I download degli ZIP passano attraverso gli endpoint autenticati, senza accettare percorsi arbitrari dal client.

## Collaudo del 19 novembre

- **511 test backend**, inclusi backup media, ZIP verificati, deduplica, interruzioni/troncamenti, accessi e ripristino foto senza ritrasmissione.
- **119 test web**, TypeScript, lint e compilazione della pagina telefono.
- **15 test JVM Android** su ricerca, rilevazione, hash, classificazione dei tipi e cancellazione dei flussi.
- APK release **0.7 / 464228**, circa 4,49 MB, per arm64-v8a, armeabi-v7a e x86_64; firma verificata con lo stesso certificato precedente, asset aggiornati e nessun peso neurale.
- Verifica sul Python del pacchetto PC: ZIP media, duplicati saltati, manifesti portabili, scoperta delle interfacce private e ripristino foto da ZIP, senza chiamate al modello.

Non sono stati scanditi media personali né eseguiti un trasferimento fisico telefono–PC o una misura della velocità USB. Restano da collaudare sul dispositivo reale permessi, cartelle accessibili, rete tethering/firewall e trasferimenti grandi.
