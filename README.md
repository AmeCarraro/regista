# Regista

A personal assistant that runs on your own computer, with local models only. You write what you need in a chat; a small model, the "director", decides what to do with the request and the app does it. "Regista" is Italian for director.

What it does today:

- **Finds your pictures from a sentence.** "Trovami le foto con un cane", then "solo quelli neri". The pictures are read once by a model that understands images and text, and searched by meaning.
- **Finds them by when they were taken.** "Le foto dal 20 maggio al 20 luglio", "le foto del mare di agosto 2024", "quelle dell'anno scorso". The day is the one the camera wrote in the picture.
- **Puts them in order, without ever deleting one.** "Eliminale" moves the pictures to a trash folder; "copia le foto delle chiese in una cartella Chiese" copies them; "annulla" takes the last change back. Each of these is first proposed, with the pictures in front of you, and happens only after your yes.
- **Reaches the pictures on your phone.** An Android app, paired with the computer by pointing the camera at a code, shows the same chat on the phone and lets the computer search the phone's pictures: "trovami sul telefono le foto del mare", "salvale sul computer in una cartella Mare".
- **Answers questions**, with the local model you choose or with the one the app picks.
- **Chooses the model for you.** It looks at the computer (graphics card or processor only, memory), at what each installed model can do, and, after a test you can start from the page, at how each model actually did on this machine. It also says which model the computer should have: with a graphics card the largest that fits in its memory, without one the smallest. If it is not installed, the page gives the command to get it; the app downloads nothing by itself.

Nothing leaves your devices: the models run in Ollama, the page is reachable from this PC alone, and a phone talks only to the computer it was paired with.

## Run it

You need Docker Desktop, and Ollama with at least one model that can use tools, for example `granite4.1:3b`.

```powershell
.\run.ps1
```

Then open http://127.0.0.1:8090/. The first start builds the image, which downloads PyTorch and the picture model: a few minutes. By default the app works on the pictures in `foto\`; to use another folder:

```powershell
.\run.ps1 -Photos D:\Immagini
```

To let it look and never touch, add `-ReadOnly`: the folder is then mounted read-only, and it is Docker that enforces it, not the app.

Stop it with `docker compose down`.

### With the phone

```powershell
.\run.ps1 -Phone        # opens the door of the phones to the home network (port 8443)
.\android.ps1 build     # makes android\app\build\outputs\apk\debug\app-debug.apk
```

Install the APK on the phone. On the page, under "Telefono", choose "Collega un telefono" and point the phone's camera at the code: the app opens, pairs, asks for the permission to see the pictures and tells the computer what the phone has. From then on the phone finds the computer by itself whenever the app is open and both are on the same network. If the phone does not find the PC, Windows Firewall may be blocking port 8443 on that network.

To reach the computer from elsewhere it needs an address that works from there, for example the one a private network such as Tailscale gives the PC: `.\run.ps1 -Phone -Address 100.x.y.z`, then pair again.

## What it may do to your pictures

- **A model never changes a picture.** The director can only *propose* a change. The page shows the proposal, with every picture it would touch; you can untick some, or rename the folder. Only your yes, a click or a plain "sì" read by the page from a fixed list of words, sends the change to the service.
- **Nothing is deleted.** Throwing a picture away moves it to `.regista\cestino\` inside the picture folder, under the same subfolders it was in. A move is a rename: the content of the file is never rewritten.
- **Everything can be taken back.** Each change is one line in `.regista\registro.jsonl`. "Annulla" moves trashed pictures home, and moves unwanted copies to the trash. A picture coming home never overwrites one that took its name meanwhile: it gets a name with "(2)".
- **Copies go to `Raccolte\<name>\`** inside the picture folder. The originals stay where they are.
- The app never empties its trash. To free the space, delete `.regista\cestino` yourself when you are sure.
- **Only the app's own page can ask for a change.** The service answers only to its own names, and refuses a request to change something when the browser says another page made it: a site you happen to have open cannot move your pictures or let a phone in.

And on the phone:

- **The phone app only reads.** It cannot change or delete a picture: there is no code in it that does. Pictures on the phone can be copied to the computer, not thrown away.
- **The computer gets a small copy of each picture**, a few hundred pixels wide, to know what it shows. The originals stay on the phone until you ask for some; then they arrive in `Raccolte\<name>\`, and that too can be taken back.
- **The app asks before pairing**, showing the name and the address of the computer, and it refuses a computer that is not inside a private network. A pairing link can reach the app from any page or app, not only from your camera: without your yes nothing is paired, and a pairing that fails leaves the one there was.
- **A phone is let in once, by you, from the PC.** The code is good for five minutes and for one phone. It carries the fingerprint of the computer's certificate, so the phone talks only to that computer, encrypted; the phone gets a key of its own, of which the computer keeps only a hash. "Scollega" on the page shuts a phone out at once.
- **The door of the phones is separate** from the one of the PC and closed to the network unless you start the app with `-Phone`. Without the key of a paired phone it answers to one thing only: the code that lets a phone in.

## How it is made

| Part | Where | What it is |
|---|---|---|
| Director | `app/orchestrator.py` | One model decides what to do with a request: answer, search the pictures, count them, or propose a change to them. It replies with a small form, not free text, so the decision is always one the app can carry out. What happened is said by the app, from the result: the numbers are never written by a model. Whether a request is about the phone is read in its words, not asked to the model. |
| Periods | `app/period.py` | Reads a period of time in the words of a request, in Italian, and says it back. Not asked to the model: a small model gets dates wrong. |
| Changes | `app/actions.py` | The trash, the copies, the journal and the undo. Called only by the service, after a yes in the page, with pictures named by the index and never by a path. |
| Phones | `app/phone.py` | Pairing, the certificate, what is known of the pictures of each phone, and the requests for originals. |
| Models | `app/llm.py`, `app/catalog.py` | What Ollama has installed, what each model is for, whether it fits this computer, who gets each job, and which model is worth having here. |
| Model test | `app/selftest.py` | Gives every model the same requests and counts how often it does the right thing, and how fast. The choice of the director then rests on what was measured here. |
| Pictures | `app/photos.py`, `app/embedder.py` | An index of the pictures of a folder, searched with a sentence (CLIP ViT-B/32, on the processor). |
| Service | `app/main.py` | Two doors on one service: the PC's, which answers only to its own names, and the encrypted one of the phones, which answers only to a paired phone. |
| Page | `web/` | TypeScript and React: the chat, the picture results, the proposals, the panel with the computer, the models, the pictures and the phones. |
| Phone app | `android/` | Kotlin, with no libraries beyond Android's own. It pairs, shows the computer's page, tells the computer which pictures the phone has, and sends the ones asked for. It works while it is open. |

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
# a script that behaves as the app does, with a folder as its gallery
python tools\pretend_phone.py "regista://pair?..." --gallery some\folder --address 127.0.0.1

# the real app on an Android emulator in a container (needs virtualization; about 1.3 GB the first time)
.\android.ps1 phone
.\android.ps1 install
.\android.ps1 pictures some\folder
.\android.ps1 pair "regista://pair?..."
.\android.ps1 screen phone.png
```

The emulator reaches the door of the phones at `10.0.2.2`, so start the app with that address in the link: set `HOST_ADDRESSES=10.0.2.2` and `PHONE_OPEN=1` before `docker compose up -d`. The door then stays reachable from this PC only.

## Limits, as measured

- The picture model was tried on 200 pictures of 10 kinds. For a plain subject ("a dog") the first 20 results were right. For a detail ("a black and white dog") the right ones come first and then mix with the others. A proposal to trash or copy takes the pictures the search is sure about, so look at them before saying yes.
- It understands English, so the director translates the request. A 3B model sometimes translates badly: "macchina rossa" became "a red machine", "motosega" became "a motorcycle chain".
- The director decides right most of the time, not always: with the form `granite4.1:3b` got 59 of 60 test requests right, among them all 20 that ask to trash, copy or undo and all 8 about the phone.
- "Sposta" is understood as "copia": the app has no move yet.
- A period is understood when it is said in one of the ways `app/period.py` lists (days, months and years by name or number, "ieri", "il mese scorso", "l'anno scorso"); seasons and "l'estate del 2023" are not. A picture with no date written in it counts as taken on the date of its file, which for pictures copied from elsewhere is the day they were copied. Tried with the model on 15 requests that name a period, all read right, and on the emulator with 60 pictures two days apart: "dal 20 maggio al 20 luglio" found the 31 it should.
- Pictures are not found by where they were taken: "le foto del Giappone" finds the ones that look like Japan.
- The model the app suggests comes from a list of three, the sizes of the one it was measured with (`granite4.1` 3B, 8B, 30B; names and sizes read from the Ollama library on 2026-10-11). Only the 3B one was tried here. Graphics cards other than NVIDIA are not detected: on those computers the app reasons as if there were none.
- The phone app was tried on an Android 15 emulator, not on a real phone: pairing, the pictures becoming known to the computer, a search from the phone, and four originals arriving on the PC identical to the ones on the phone. Reading the code with a real camera, and the home network with its firewall, were not tried.
- What protects the pictures was written and tried by one author: nobody else has reviewed it. Tried on the running app: a stranger at the door of the phones gets nothing without a key, old encryption versions are refused, and the PC's own door does not answer from the network. A paired phone can do what the PC's page can, so a lost phone must be shut out from the page ("Scollega"); the small copies of the phone's pictures sit on the PC unencrypted, like the PC's own pictures.
- The phone works for the computer only while the app is open in front. A search looks either at the computer or at the phone, not at both at once.
- Reading the pictures takes about 18 per second on a laptop processor, once.

## Not there yet

Using the phone away from home without setting up a private network, the phone app working by itself without the computer, deleting on the phone, and models outside this computer.
