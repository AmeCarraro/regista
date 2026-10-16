# Regista

A personal assistant that runs on your own computer, with local models only. You write what you need in a chat; a small model, the "director", decides what to do with the request and the app does it. "Regista" is Italian for director.

What it does today:

- **Finds your pictures from a sentence.** "Trovami le foto con un cane", then "solo quelli neri". The pictures are read once by a model that understands images and text, and searched by meaning.
- **Finds them by when they were taken.** "Le foto dal 20 maggio al 20 luglio", "le foto del mare di agosto 2024", "quelle dell'anno scorso". The day is the one the camera wrote in the picture.
- **Finds them by where they were taken.** "Le foto del Giappone", "un cane a Roma", "le foto di Parigi di giugno". The place is the one the camera wrote in the picture, as a position; a table of the world's cities says which country and city that is.
- **Puts them in order, without ever deleting one.** "Eliminale" moves the pictures to a trash folder; "copia le foto delle chiese in una cartella Chiese" copies them; "annulla" takes the last change back. Each of these is first proposed, with the pictures in front of you, and happens only after your yes.
- **Reaches the pictures on your phone.** An Android app, paired with the computer by pointing the camera at a code, shows the same chat on the phone and lets the computer search the phone's pictures: "trovami sul telefono le foto del mare", "salvale sul computer in una cartella Mare". "Elimina dal telefono le foto di Parigi" copies them to the computer first and then has the phone move them to its own trash.
- **Works on the phone by itself, too.** The app has a screen of its own that finds the phone's pictures with no computer and no network: by when and where they were taken, "le foto di Parigi dal 10 al 12 giugno", and, once it has taken two small models from the computer, by what they show, "un cane bianco e nero". From it, "Manda al computer" puts pictures in line for the computer: they go now if it answers, as soon as it does otherwise.
- **Moves pictures both ways.** "Mandami sul telefono le foto del mare" prepares pictures of the computer for the phone, which takes them into an album of its own, `Pictures/Regista/<name>`.
- **Answers questions**, with the local model you choose or with the one the app picks.
- **Chooses the model for you.** It looks at the computer (graphics card or processor only, memory), at what each installed model can do, and, after a test you can start from the page, at how each model actually did on this machine. It also says which model the computer should have: with a graphics card the largest that fits in its memory, without one the smallest. If it is not installed, the page gives the command to get it; the app downloads nothing by itself.

Nothing leaves your devices: the models run in Ollama, the page is reachable from this PC alone, and a phone talks only to the computer it was paired with.

## Run it

You need Docker Desktop, and Ollama with at least one model that can use tools, for example `granite4.1:3b`.

On a PC that has none of this, double-click `install.cmd`. It says what is there and what is missing, offers to install Docker Desktop and Ollama with winget and to download the model, asking before each download, asks which folder of pictures to work on, starts the app and leaves an icon on the desktop that starts it again. `.\install.ps1 -Check` only looks.

It also asks whether the app will be used from a phone, and if so the icon opens the door of the phones too, and it offers to download the two models the phone takes from the computer to look at pictures by itself (about 230 MB, from Hugging Face; `tools\phone-models.ps1` does the same, and keeps only the files whose SHA-256 is the one written in it).

Windows runs a `.ps1` file only when asked for that one time: `install.cmd` and the icon do so, and nothing in the settings of Windows has to change. In a terminal of your own the same is:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

The commands below are written short, as `.\run.ps1`, for a terminal where scripts may run.

Then open http://127.0.0.1:8090/ (or add `-Open`). The first start builds the image, which downloads PyTorch and the picture model: a few minutes. By default the app works on the pictures in `foto\`; to use another folder:

```powershell
.\run.ps1 -Photos D:\Immagini
```

To let it look and never touch, add `-ReadOnly`: the folder is then mounted read-only, and it is Docker that enforces it, not the app.

Stop it with `docker compose down`.

### With the phone

```powershell
.\run.ps1 -Phone        # opens the door of the phones to the home network (port 8443)
.\android.ps1 build     # makes android\app\build\outputs\apk\release\app-release.apk
```

Install the APK on the phone. The app opens on its own screen, "Telefono", and asks for the permission to see the pictures and where they were taken: from then on it finds them by day and by place, with or without a computer. To pair it, on the computer's page, under "Telefono", choose "Collega un telefono" and point the phone's camera at the code: the app opens on its other screen, "Computer", pairs, and tells the computer what the phone has; that screen then shows the computer's page. From then on the phone finds the computer by itself whenever the app is open and both are on the same network. If the phone does not find the PC, Windows Firewall may be blocking port 8443 on that network.

To reach the computer from elsewhere it needs an address that works from there, for example the one a private network such as Tailscale gives the PC: `.\run.ps1 -Phone -Address 100.x.y.z`, then pair again.

## What it may do to your pictures

- **A model never changes a picture.** The director can only *propose* a change. The page shows the proposal, with every picture it would touch; you can untick some, or rename the folder. Only your yes, a click or a plain "sì" read by the page from a fixed list of words, sends the change to the service.
- **Nothing is deleted.** Throwing a picture away moves it to `.regista\cestino\` inside the picture folder, under the same subfolders it was in. A move is a rename: the content of the file is never rewritten.
- **Everything can be taken back.** Each change is one line in `.regista\registro.jsonl`. "Annulla" moves trashed pictures home, and moves unwanted copies to the trash. A picture coming home never overwrites one that took its name meanwhile: it gets a name with "(2)".
- **Copies go to `Raccolte\<name>\`** inside the picture folder. The originals stay where they are.
- The app never empties its trash. To free the space, delete `.regista\cestino` yourself when you are sure.
- **Only the app's own page can ask for a change.** The service answers only to its own names, and refuses a request to change something when the browser says another page made it: a site you happen to have open cannot move your pictures or let a phone in.

And on the phone:

- **The phone app cannot delete a picture, and cannot move one to the trash by itself.** It can ask Android to, and Android asks you, on the phone, showing the pictures: only your yes there moves them, and to the phone's own trash, where they stay 30 days.
- **A picture leaves the phone only after its copy is on the computer.** "Elimina dal telefono" first brings the originals to `Raccolte\Tolte dal telefono\`. The phone says what each picture is (the SHA-256 of its bytes) and the computer keeps only what arrives as that: the phone is told which pictures it may throw away only when they are all here, and only those. So it takes two yeses, one in the page and one to Android, and in between a copy that was checked. It needs Android 11 or later; on older Android the copies are made and the pictures stay, and the app says so.
- **Pictures from the computer arrive checked.** The computer says what each picture is (its SHA-256); the phone writes it into a hidden file and shows it in the gallery only if all of it arrived as that.
- **The phone's models come from the computer, checked**, and stay in the app's own files. With them the phone reads its own pictures, in the background, one at a time: nothing of what it sees leaves the phone.
- **The phone's own screen is a page that travels inside the app**, shown from the app's files with no server and no network. It is the only page that can call the app, and it can only read what the app knows of the pictures, show one, and put some in line for the computer.
- **That copy is the picture as the camera wrote it**, place included. For this the app asks Android for the original, which Android gives only with the permission to see where pictures were taken.
- **The computer gets a small copy of each picture**, a few hundred pixels wide, to know what it shows, with the day and the position the camera wrote in it. The originals stay on the phone until you ask for some; then they arrive in `Raccolte\<name>\`, and that too can be taken back.
- **The app asks before pairing**, showing the name and the address of the computer, and it refuses a computer that is not inside a private network. A pairing link can reach the app from any page or app, not only from your camera: without your yes nothing is paired, and a pairing that fails leaves the one there was.
- **A phone is let in once, by you, from the PC.** The code is good for five minutes and for one phone. It carries the fingerprint of the computer's certificate, so the phone talks only to that computer, encrypted; the phone gets a key of its own, of which the computer keeps only a hash. "Scollega" on the page shuts a phone out at once.
- **The door of the phones is separate** from the one of the PC and closed to the network unless you start the app with `-Phone`. Without the key of a paired phone it answers to one thing only: the code that lets a phone in.

## How it is made

| Part | Where | What it is |
|---|---|---|
| Director | `app/orchestrator.py` | One model decides what to do with a request: answer, search the pictures, count them, or propose a change to them. It replies with a small form, not free text, so the decision is always one the app can carry out. What happened is said by the app, from the result: the numbers are never written by a model. Whether a request is about the phone is read in its words, not asked to the model. |
| Periods | `app/period.py` | Reads a period of time in the words of a request, in Italian, and says it back. Not asked to the model: a small model gets dates wrong. |
| Places | `app/places.py`, `data/geonames/` | Reads the position a camera wrote in a picture, and knows which country and city it is from a table of the cities with more than 15,000 inhabitants. The table is from [GeoNames](https://www.geonames.org/), under the licence CC BY 4.0; it is in the repository, so nothing is asked to the network. |
| Changes | `app/actions.py` | The trash, the copies, the journal and the undo. Called only by the service, after a yes in the page, with pictures named by the index and never by a path. |
| Phones | `app/phone.py` | Pairing, the certificate, what is known of the pictures of each phone, the requests for originals, and the pictures prepared for a phone. |
| Models | `app/llm.py`, `app/catalog.py` | What Ollama has installed, what each model is for, whether it fits this computer, who gets each job, and which model is worth having here. A graphics card that is not NVIDIA is counted on only once a model was seen running on it. |
| Model test | `app/selftest.py` | Gives every model the same requests and counts how often it does the right thing, and how fast. The choice of the director then rests on what was measured here. |
| Pictures | `app/photos.py`, `app/embedder.py` | An index of the pictures of a folder, searched with a sentence (CLIP ViT-B/32, on the processor). |
| Service | `app/main.py` | Two doors on one service: the PC's, which answers only to its own names, and the encrypted one of the phones, which answers only to a paired phone. |
| Page | `web/` | TypeScript and React: the chat, the picture results, the proposals, the panel with the computer, the models, the pictures and the phones. |
| Phone app | `android/` | Kotlin, with no libraries beyond Android's own, in two screens. "Telefono" is a page that travels inside the app (`web/src/telefono`, built by `android.ps1 build`): it reads the request on the phone, a period with the same rules as `app/period.py` and a place with the table of places the app carries, and chooses among the pictures the app has read (`Library.kt`, a small database of the day and the place of each). With the two models of `Sight.kt` it also sees what pictures show: a picture model (CLIP ViT-B/32, the computer's own, made small) and a sentence model taught to answer as CLIP does in many languages, so that Italian needs no translation; they run on ONNX Runtime. "Computer" pairs and shows the computer's page. Meanwhile the app tells the computer which pictures the phone has, sends the ones asked for, takes the ones prepared for it, and asks Android to move to the trash the ones the user wanted off the phone. It works while it is open. |
| Installer | `install.cmd`, `install.ps1` | Checks what the app needs on a Windows PC, offers to get what is missing, and leaves an icon that starts the app. |

The app runs in one container (`compose.yaml`). It cannot see the computer it runs on, so `run.ps1` measures it and passes it in.

## Develop

```powershell
pip install -r requirements-dev.txt
pytest
.\npm.ps1 test
```

The Python tests need neither Ollama nor the picture model nor a phone: all are replaced by fakes, and the changes are tried on folders made for the test. `.\npm.ps1 run dev` serves the page on http://127.0.0.1:5174 with live reload, taking the service from the running app.

The phone side can be tried without a phone, in two ways:

```powershell
# a script that behaves as the app does, with a folder as its gallery (--trash yes: its user says yes when asked about the trash)
python tools\pretend_phone.py "regista://pair?..." --gallery some\folder --address 127.0.0.1

# the real app on an Android emulator in a container (needs virtualization; about 1.3 GB the first time)
.\android.ps1 phone
.\android.ps1 install
.\android.ps1 pictures some\folder
.\android.ps1 pair "regista://pair?..."
.\android.ps1 screen phone.png
```

A real phone or tablet can be driven the same way through its cable, once USB debugging is on in its settings: `.\android.ps1 tablet` (then `install`, `pictures <folder>`, `pair "<link>"`, `screen <file>`). It uses Google's adb for Windows, kept in `android\.tools`; trial pictures go into an album of their own, "Regista prova".

The emulator reaches the door of the phones at `10.0.2.2`, so start the app with that address in the link: set `HOST_ADDRESSES=10.0.2.2` and `PHONE_OPEN=1` before `docker compose up -d`. The door then stays reachable from this PC only.

## Limits, as measured

- The picture model was tried on 200 pictures of 10 kinds. For a plain subject ("a dog") the first 20 results were right. For a detail ("a black and white dog") the right ones come first and then mix with the others. A proposal to trash or copy takes the pictures the search is sure about, so look at them before saying yes.
- It understands English, so the director translates the request. A 3B model sometimes translates badly: "macchina rossa" became "a red machine", "motosega" became "a motorcycle chain".
- The director decides right most of the time, not always: with the form `granite4.1:3b` got 59 of 60 test requests right, among them all 20 that ask to trash, copy or undo and all 8 about the phone. Of 10 more about taking pictures off the phone, said in different ways, it read all 10 right.
- "Sposta" is understood as "copia": the app has no move yet.
- A period is understood when it is said in one of the ways `app/period.py` lists (days, months and years by name or number, "ieri", "il mese scorso", "l'anno scorso"); seasons and "l'estate del 2023" are not. A picture with no date written in it counts as taken on the date of its file, which for pictures copied from elsewhere is the day they were copied. Tried with the model on 15 requests that name a period, all read right, and on the emulator with 60 pictures two days apart: "dal 20 maggio al 20 luglio" found the 31 it should.
- A place is understood when it is a country or a city of more than 15,000 inhabitants: regions ("la Sardegna"), mountains, lakes and villages are not. A picture is in the country of the city nearest to it, which near a border can be the wrong one, and in a city when it was taken within 50 km of its centre. A picture with no position in it, as a screenshot, one received in a chat, or one taken with the position turned off, is in no place: when no picture says it was taken where asked, the app says so and shows the ones that look like it. The answer names a country in English ("scattate in Japan"). Tried with the model on 15 requests, 11 with a place and 4 without, all read right, and on the emulator with 60 pictures of three trips: "le foto del Giappone" found the 20 it should, "di Venezia" the 6, "del Giappone dal 3 al 4 maggio" the 8.
- The model the app suggests comes from a list of three, the sizes of the one it was measured with (`granite4.1` 3B, 8B, 30B; names and sizes read from the Ollama library on 2026-10-11). Only the 3B one was tried here. A graphics card that is not NVIDIA is found (by `run.ps1`, in Windows' own list, if it has at least 2 GB of memory of its own) but Ollama uses only some of those cards: the app counts on it only after a model was seen running on it, when the models are tried from the page or while one is loaded. This was tried on a PC with an NVIDIA card and with made-up numbers, not on a PC with another card.
- The app runs on Android 7 and later. It was tried on a real tablet, a Huawei MediaPad M3 Lite with Android 7.0 and a processor of 2017, over the home Wi-Fi: with no computer it found by day and place what it should ("foto di Parigi dal 10 al 12 giugno" 12 of 12, "di Venezia" 6, "della Spagna" none); it took the 227 MB of models from the computer in about 80 seconds and then looked at its 93 pictures at about one a second; by what they show, 42 of the 46 pictures shown as sure were right, and with the computer off "una chiesa", "le palline da golf" and "un cane bianco e nero" were all right; 6 pictures chosen on the tablet arrived on the computer identical, place included, and 3 of the computer arrived in its album identical; "elimina dal telefono" made the copies and, as Android 7 has no trash an app can use, left the pictures where they were and said so. The question before it still says that Android will ask, which on Android 7 it does not.
- The phone app was also tried on an Android 15 emulator: pairing, the pictures becoming known to the computer, a search from the phone, and originals arriving on the PC. Taking pictures off the phone was tried there too: 20 pictures arrived identical to the ones on the phone, place included, Android asked, and after the yes they were in its trash and no longer among the phone's; after a no they stayed, and the copies with them. Reading the code with a real camera, the home network with its firewall, and Android 10 and 11 were not tried.
- A change made on the phone is not taken back from the chat: pictures moved to the phone's trash are restored from the phone's gallery, within 30 days. "Annulla" after it offers only to remove the copies from the computer, and says so.
- The installer was tried on a PC that already had everything, and with the programs hidden from it up to the point where it would install them. Installing Docker Desktop and Ollama through it, on a PC without them, was not tried.
- What protects the pictures was written, read again with an attacker's eye and tried by one author: nobody else has reviewed it. Tried on the running app: a stranger at the door of the phones gets nothing without a key, old encryption versions are refused, the PC's own door does not answer from the network, a request larger than it has reason to be is refused or cut off (before that, anyone on the network could fill the computer's memory through the request that pairs), and every answer forbids other pages to show this one inside themselves. The phone app is built as a release, not as a debug app, from which the key of the computer could be read with a cable. The key with which the app is signed is made on the PC that builds it, with a password written in the build file: fine for one's own phones, not for giving the app to others. A paired phone can do what the PC's page can, so a lost phone must be shut out from the page ("Scollega"); the small copies of the phone's pictures sit on the PC unencrypted, like the PC's own pictures.
- The phone works for the computer only while the app is open in front. A search looks either at the computer or at the phone, not at both at once.
- On its own, the phone finds pictures by day and by place and, with its models, by what they show. The models were first measured on the computer with the 200 sample pictures and 20 requests in Italian: 338 of 400 right in the first 20 of each, against 335 with the computer's own picture fingerprints; "motosega" is the word they know least (8 of 20). On the emulator, with no computer: 226 MB of models arrived in under a minute and the 200 pictures were looked at in about a minute; of the pictures shown as sure, 149 of 177 were right ("un cane" 12 of 12, "una chiesa" 18 of 18, "una pallina da golf" 20 of 20, "un corno" 3 of 6). An old phone will be slower: how much was not measured. The app is 95 MB, most of it the engine that runs the models. Tried on the emulator with no computer: "foto del Giappone" found the 20 it should, "di Parigi dal 10 al 12 giugno" the 12, "di Venezia" the 6, "di luglio" the 20, "della Spagna" none. With the computer: 5 and then 7 pictures chosen on the phone arrived identical, the 7 after the computer had been off, by themselves when it came back; 3 pictures of the computer arrived in the phone's album, identical. The words of a request are understood by rules, not by a model: "foto di Natale" is not Natal, in Brazil, but a name the rules do not know is not a place either.
- Reading the pictures takes about 18 per second on a laptop processor, once.

## Not there yet

Using the phone away from home without setting up a private network, and models outside this computer.
