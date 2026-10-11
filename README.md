# Regista

A personal assistant that runs on your own computer, with local models only. You write what you need in a chat; a small model, the "director", decides what to do with the request and the app does it. "Regista" is Italian for director.

What it does today:

- **Finds your pictures from a sentence.** "Trovami le foto con un cane", then "solo quelli neri". The pictures are read once by a model that understands images and text, and searched by meaning.
- **Puts them in order, without ever deleting one.** "Eliminale" moves the pictures to a trash folder; "copia le foto delle chiese in una cartella Chiese" copies them; "annulla" takes the last change back. Each of these is first proposed, with the pictures in front of you, and happens only after your yes.
- **Answers questions**, with the local model you choose or with the one the app picks.
- **Chooses the model for you.** It looks at the computer (graphics card or processor only, memory), at what each installed model can do, and, after a test you can start from the page, at how each model actually did on this machine. It also says which model the computer should have: with a graphics card the largest that fits in its memory, without one the smallest. If it is not installed, the page gives the command to get it; the app downloads nothing by itself.

Nothing leaves the computer: the models run in Ollama, and the page is reachable from this PC alone.

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

## What it may do to your pictures

- **A model never changes a picture.** The director can only *propose* a change. The page shows the proposal, with every picture it would touch; you can untick some, or rename the folder. Only your yes, a click or a plain "sì" read by the page from a fixed list of words, sends the change to the service.
- **Nothing is deleted.** Throwing a picture away moves it to `.regista\cestino\` inside the picture folder, under the same subfolders it was in. A move is a rename: the content of the file is never rewritten.
- **Everything can be taken back.** Each change is one line in `.regista\registro.jsonl`. "Annulla" moves trashed pictures home, and moves unwanted copies to the trash. A picture coming home never overwrites one that took its name meanwhile: it gets a name with "(2)".
- **Copies go to `Raccolte\<name>\`** inside the picture folder. The originals stay where they are.
- The app never empties its trash. To free the space, delete `.regista\cestino` yourself when you are sure.

## How it is made

| Part | Where | What it is |
|---|---|---|
| Director | `app/orchestrator.py` | One model decides what to do with a request: answer, search the pictures, count them, or propose a change to them. It replies with a small form, not free text, so the decision is always one the app can carry out. What happened is said by the app, from the result: the numbers are never written by a model. |
| Changes | `app/actions.py` | The trash, the copies, the journal and the undo. Called only by the service, after a yes in the page, with pictures named by the index and never by a path. |
| Models | `app/llm.py`, `app/catalog.py` | What Ollama has installed, what each model is for, whether it fits this computer, who gets each job, and which model is worth having here. |
| Model test | `app/selftest.py` | Gives every model the same requests and counts how often it does the right thing, and how fast. The choice of the director then rests on what was measured here. |
| Pictures | `app/photos.py`, `app/embedder.py` | An index of the pictures of a folder, searched with a sentence (CLIP ViT-B/32, on the processor). |
| Page | `web/` | TypeScript and React: the chat, the picture results, the proposals, the panel with the computer, the models and the pictures. |

The app runs in one container (`compose.yaml`). It cannot see the computer it runs on, so `run.ps1` measures it and passes it in.

## Develop

```powershell
pip install -r requirements-dev.txt
pytest
.\npm.ps1 test
```

The Python tests need neither Ollama nor the picture model: both are replaced by fakes, and the changes are tried on folders made for the test. `.\npm.ps1 run dev` serves the page on http://127.0.0.1:5174 with live reload, taking the service from the running app.

## Limits, as measured

- The picture model was tried on 200 pictures of 10 kinds. For a plain subject ("a dog") the first 20 results were right. For a detail ("a black and white dog") the right ones come first and then mix with the others. A proposal to trash or copy takes the pictures the search is sure about, so look at them before saying yes.
- It understands English, so the director translates the request. A 3B model sometimes translates badly: "macchina rossa" became "a red machine", "motosega" became "a motorcycle chain".
- The director decides right most of the time, not always: with the form `granite4.1:3b` got 51 of 52 test requests right, among them all 20 that ask to trash, copy or undo. Left free to call tools it had got 14 of 18, searching the pictures also when asked for advice on photography.
- "Sposta" is understood as "copia": the app has no move yet.
- The model the app suggests comes from a list of three, the sizes of the one it was measured with (`granite4.1` 3B, 8B, 30B; names and sizes read from the Ollama library on 2026-10-11). Only the 3B one was tried here. Graphics cards other than NVIDIA are not detected: on those computers the app reasons as if there were none.
- Reading the pictures takes about 18 per second on a laptop processor, once.

## Not there yet

The phone app, moving files between phone and computer, and models outside this computer.
