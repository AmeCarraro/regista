# Ripristinare foto e video sul telefono

Regista pubblica gli originali nella cartella `Importate dal telefono` della libreria PC. Gli ZIP verificati si trovano in `index/backup-originali`, con gli archivi dei blocchi in `blocchi`. I backup mantengono i byte originali, compresi i metadati incorporati. Il manifesto del blocco registra nome, cartella di provenienza, data e SHA-256. Le ricevute in `index/import-batches.sqlite` conservano anche le provenienze dei duplicati e le rimozioni confermate.

## Prima di rimuovere i file dal telefono

Apri **Foto e video → Importazioni e archivi → Rivedi cosa togliere dal telefono** sul PC. Usa il filtro **Foto e video** per comprendere entrambi. In un'anteprima WhatsApp già avviata per le foto, puoi mettere in pausa e scegliere **Includi anche i video WhatsApp**.

Apri Regista sul telefono per avviare il lotto. Con la notifica di verifica attiva, puoi spegnere lo schermo. La verifica può usare il Wi-Fi quando il PC rimane raggiungibile. Regista salva la posizione dopo ogni pagina e si ferma per la revisione del lotto. Per la rimozione, apri la lista sul PC e conferma poi anche sul telefono.

## Controllare cosa manca

Collega un solo Android via USB, autorizza il debug e apri PowerShell nella cartella del repository. Controlla prima il modello del telefono e il numero di file riportati dallo script.

Per rimettere i file dell'ultima rimozione registrata da Regista:

```powershell
.\.venv\Scripts\python.exe .\tools\restore_phone_media.py --cleanup latest
```

Puoi sostituire `latest` con l'ID della rimozione. In alternativa puoi scegliere uno ZIP di importazione con manifesto e ripristinare i file contenuti in quel blocco:

```powershell
.\.venv\Scripts\python.exe .\tools\restore_phone_media.py --zip 'D:\Backup\blocco.zip'
```

Ripeti `--zip` per più blocchi. Il ripristino per rimozione usa l'indice, anche quando due provenienze rimandano allo stesso ZIP già esistente. Se l'installazione di Regista è in un'altra cartella, indica quella che contiene `index` con `--regista-dir`.

## Copiare i file mancanti

L'anteprima è in sola lettura. Per eseguire il piano ripeti il comando con `--apply` e scrivi `RIPRISTINA` quando richiesto. Lo script usa il nome e il percorso registrati, verifica lo SHA-256 del file nello ZIP e sul telefono, poi pubblica la copia. Tiene i file già presenti e segnala i percorsi ambigui o sconosciuti. Puoi rilanciarlo se stacchi il cavo. I file già ripristinati risultano presenti.

Per WhatsApp vengono riutilizzate le sottocartelle originali sotto `Android/media/com.whatsapp/WhatsApp/Media` o il percorso equivalente salvato nel manifesto. Il riconoscimento dell'allegato dipende dal riferimento ancora presente nella chat. Per recuperare messaggi e conversazioni serve il ripristino del backup di WhatsApp. [Guida ufficiale WhatsApp](https://faq.whatsapp.com/589979312881396)
