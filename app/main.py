"""The service behind the page: the models, the chat, the pictures, the phones. It also serves the page itself.

It has two doors. One is for this computer, and answers only here. The other is for the
phones the user has let in: encrypted, on a port of its own, and closed to everyone else.
"""
import asyncio
import hashlib
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Literal

import segno
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import catalog
import llm
import orchestrator
import selftest
from actions import Actions, Refused, collection_name
from embedder import ClipEmbedder
from phone import Phones, on_phone
from photos import BATCH, PhotoIndex, photo_id
from places import Places

logger = logging.getLogger("uvicorn.error")
INDEX_DIR = os.getenv("INDEX_DIR", "index")
PHOTOS_DIR = os.getenv("PHOTOS_DIR", "foto")
# the names this computer's door answers to
HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
# the door of the phones, inside the container and as it is seen from outside
PHONE_PORT = int(os.getenv("PHONE_PORT", "8443"))
# where that door listens: in a container, everywhere inside it, and Docker decides what reaches it from outside;
# as a program of the PC, on the PC's address in the home network alone (desktop.py), or on 127.0.0.1 when closed
PHONE_HOSTS = [host for host in os.getenv("PHONE_HOST", "0.0.0.0").split(",") if host]
# whether whoever started the app opened that door to the network (run.ps1 -Phone)
PHONE_OPEN = os.getenv("PHONE_OPEN", "") == "1"
# the largest picture a phone may send
LARGEST = 400 * 1024 * 1024
# The two models with which a phone looks at pictures by itself, and what they need: downloaded once
# into models/phone on this computer, the phone takes them from here. Nothing else in that folder is given.
PHONE_MODELS = Path(os.getenv("PHONE_MODELS", "/models/phone"))
MODEL_FILES = ("text.onnx", "vision.onnx", "vocab.txt", "dense.safetensors")
# The most any other request may carry. Without a limit, whoever reaches a door could fill this
# computer's memory with one endless request; at the door of the phones that is anyone on the
# network, since the request that lets a phone in is heard before any key is shown.
BODY = 32 * 1024 * 1024
# and the most for that request: a secret and a name
PAIRING_BODY = 4096
# What every answer tells the browser that shows it: load nothing from elsewhere, and do not
# let another page show this one inside itself, where a click meant for that page lands here.
BROWSER_RULES = [
    (b"content-security-policy", b"default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
                                 b"object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
]

# the table of the places of the world, to know in which country and near which city a picture was taken
places = Places(os.getenv("PLACES_DIR", "geonames"))
photos = PhotoIndex(PHOTOS_DIR, INDEX_DIR, ClipEmbedder(PHONE_MODELS), places)
# given to look at only, when whoever started the app said so: then the app refuses every change itself
actions = Actions(PHOTOS_DIR, read_only=os.getenv("PHOTOS_READ_ONLY", "") in ("1", "true"))
phones = Phones(
    str(Path(INDEX_DIR) / "phone"),
    photos.embedder,
    # where a phone finds this computer: only whoever started the app can know it
    [address for address in os.getenv("HOST_ADDRESSES", "").split(",") if address],
    int(os.getenv("PHONE_PUBLIC_PORT") or PHONE_PORT),
    os.getenv("HOST_NAME", ""),
    places,
)

# whether the folder is being read right now, and whether it changed meanwhile and must be read once more
_reader = threading.Lock()
_reading = _again = False


def read_photos() -> None:
    """Reads the pictures in a thread of its own: it takes minutes, and the page must answer meanwhile.

    Asked while a reading is under way, it makes that reading start over when it ends:
    what changed in the folder meanwhile may have been missed.
    """
    global _reading, _again
    with _reader:
        if _reading:
            _again = True
            return
        _reading = True
    threading.Thread(target=_read, daemon=True).start()


def _read() -> None:
    global _reading, _again
    try:
        while True:
            photos.build()
            with _reader:
                if not _again:
                    _reading = False
                    break
                _again = False
    except Exception:
        with _reader:
            _reading = _again = False
        raise
    # the model is in memory after reading new pictures, but not when there were none:
    # load it now, so that the first search does not have to wait for it
    photos.embedder.text("a photo")


def open_phone_door() -> None:
    """Starts the door of the phones: the same service, encrypted, on a port of its own, at each of its addresses."""
    certificate, key = phones.certificate()
    for host in PHONE_HOSTS:
        door = uvicorn.Config(app, host=host, port=PHONE_PORT, ssl_certfile=str(certificate), ssl_keyfile=str(key), lifespan="off", log_level="info")
        threading.Thread(target=uvicorn.Server(door).run, daemon=True).start()


async def ready_the_director() -> None:
    """The model that directs, and looks too, is put in memory as the app starts: the first request does not wait for it."""
    try:
        models = await llm.installed()
        tests = selftest.load(INDEX_DIR)
        director, _ = catalog.director_and_eyes(models, catalog.hardware(models, tests), tests)
        if director:
            share = await llm.ready(director, tests.get(director, {}).get("gpu_share"))
            logger.info("%s is in memory, %s of it in video memory", director, share)
    except Exception:
        # Ollama is off, or slow to start: the model is loaded at the first request instead
        logger.exception("the director could not be put in memory in advance")


@asynccontextmanager
async def lifespan(app: FastAPI):
    read_photos()
    try:
        open_phone_door()
    except Exception:
        # without it the app still does everything else: the page says that no phone can connect
        logger.exception("the door of the phones did not open")
    readying = asyncio.create_task(ready_the_director())
    yield
    readying.cancel()


# no page that lists what the service can do: nobody needs it, and it would load its parts from elsewhere
app = FastAPI(title="regista", docs_url=None, openapi_url=None, redoc_url=None, lifespan=lifespan)


# the only ways in for a phone with no key yet: asking to come in, and asking whether the yes came
PAIRING = ("/phone/pair", "/phone/pair/wait")
CALM = "Troppi tentativi sbagliati: riprova tra un minuto."

class Gate:
    """Who may come in, by the door they knock at.

    This computer's door answers only when it is called by one of its own names: without
    that, a page anywhere on the internet could point a name of its own at this computer
    and, from the user's browser, look at the pictures and move them.

    The door of the phones answers only to a phone that was let in, and that shows its key
    with every request. The one exception is the request that lets a phone in, which shows
    the secret of the link instead. A phone cannot let other phones in.

    At both doors, a request that changes something is refused when a browser says it was
    made by a page that is not the app's own, a request cannot carry more than it has reason
    to, and every answer tells the browser to keep the page to itself.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        headers = {name: value.decode("latin-1") for name, value in scope["headers"]}
        path = scope["path"]
        outer = send

        async def send(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *BROWSER_RULES]}
            await outer(message)

        # an original from a phone is counted by who writes it to disk, as it arrives
        if not (scope["method"] == "PUT" and path.startswith("/phone/transfers/")):
            most = PAIRING_BODY if path in PAIRING else BODY
            declared = headers.get(b"content-length", "")
            if declared.isdigit() and int(declared) > most:
                return await self._refuse(send, 413, "Questa richiesta è troppo grande.")
            receive = self._counted(receive, most)

        # A request that changes something must come from the app's own page. A browser says which page
        # made a request; if it is another one, a site that the user happens to have open is trying its luck.
        origin = headers.get(b"origin")
        if scope["method"] not in ("GET", "HEAD", "OPTIONS") and origin is not None and origin.split("://", 1)[-1] != headers.get(b"host", ""):
            return await self._refuse(send, 403, "Questa richiesta arriva da un'altra pagina.")

        if (scope.get("server") or ("", 0))[1] != PHONE_PORT:
            if headers.get(b"host", "").rsplit(":", 1)[0] not in HOSTS:
                return await self._refuse(send, 400, "Invalid host header")
            if path.startswith("/phone/"):
                return await self._refuse(send, 404, "Not Found")
            return await self.inner(scope, receive, send)

        if path in PAIRING:
            if phones.calm:
                return await self._refuse(send, 429, CALM)
            return await self.inner(scope, receive, send)
        shown = headers.get(b"authorization", "")
        key = shown[7:] if shown.startswith("Bearer ") else ""
        kept = SimpleCookie(headers.get(b"cookie", "")).get("regista")
        device = phones.device_of(key or (kept.value if kept else ""))
        if device is None:
            # who knocked cannot be told: Docker shows every phone as coming from the same address
            phones.knocked("una chiave sbagliata" if key or kept else "nessuna chiave")
            return await self._refuse(send, 429 if phones.calm else 401, CALM if phones.calm else "Questo telefono non è collegato.")
        phones.running(device, headers.get(b"x-regista-android", ""))
        if path.startswith("/api/phone"):
            return await self._refuse(send, 403, "I telefoni si collegano e si scollegano dal computer.")
        scope.setdefault("state", {})["device"] = device["id"]

        async def remembering(message):
            # the page inside the phone's app cannot show the key by itself: after the first
            # request, which the app makes with the key, the browser part carries it as a cookie
            if message["type"] == "http.response.start" and key and not kept:
                # only for as long as the app is open: not written on the phone, where the key is kept locked
                cookie = f"regista={key}; Path=/; HttpOnly; Secure; SameSite=Strict"
                message = {**message, "headers": [*message.get("headers", []), (b"set-cookie", cookie.encode())]}
            await send(message)

        await self.inner(scope, receive, remembering)

    @staticmethod
    def _counted(receive, most: int):
        """What a request sends, cut off when it is more than it may be: its size can be left unsaid."""
        got = 0

        async def counted():
            nonlocal got
            message = await receive()
            if message["type"] == "http.request":
                got += len(message.get("body", b""))
                if got > most:
                    # as if whoever was sending had gone away: nothing more is read
                    return {"type": "http.disconnect"}
            return message

        return counted

    @staticmethod
    async def _refuse(send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


app.add_middleware(Gate)


class Message(BaseModel):
    role: str
    content: str = Field(max_length=20000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=200)
    # "auto", or the name of the model that should do the talking
    model: str = "auto"
    # the pictures the user is looking at, by their short names: what "these" means in a request
    selection: list[str] = Field(default=[], max_length=1000)


class Change(BaseModel):
    # "fetch" asks a phone for the originals of pictures that are on it; "clear" asks for them and then
    # has the phone move them to its trash; "send" prepares pictures of this computer for the phone
    action: Literal["trash", "copy", "fetch", "clear", "send"]
    # pictures by their short names: the page never names a file
    ids: list[str] = Field(min_length=1, max_length=1000)
    folder: str = Field(default="", max_length=200)


class Undo(BaseModel):
    # the change to take back; empty for the last one
    of: str = Field(default="", max_length=40)


class Pairing(BaseModel):
    secret: str = Field(max_length=100)
    # what the phone calls itself
    name: str = Field(default="", max_length=100)


class Ticket(BaseModel):
    ticket: str = Field(max_length=100)


class Answer(BaseModel):
    yes: bool


class Listed(BaseModel):
    id: str = Field(max_length=40)
    stamp: str = Field(default="", max_length=60)


class Listing(BaseModel):
    photos: list[Listed] = Field(max_length=300_000)


class SmallCopy(Listed):
    name: str = Field(default="", max_length=300)
    # the day it was taken, as "2024-08-15"
    day: str = Field(default="", max_length=10)
    # where it was taken, in degrees, if the phone knows and is allowed to say
    lat: float | None = None
    lon: float | None = None
    # a JPEG a few hundred pixels wide, as base64
    jpeg: str


class SmallCopies(BaseModel):
    photos: list[SmallCopy] = Field(min_length=1, max_length=BATCH)


class Asked(BaseModel):
    photos: list[Listed] = Field(max_length=1000)


class Album(BaseModel):
    folder: str = Field(min_length=1, max_length=200)
    ids: list[str] = Field(min_length=1, max_length=10_000)


class Albums(BaseModel):
    albums: list[Album] = Field(min_length=1, max_length=500)


class Typed(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class NotSent(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=1000)


class Received(BaseModel):
    # the pictures the phone took into its album, and the ones it could not
    ids: list[str] = Field(default=[], max_length=1000)
    missing: list[str] = Field(default=[], max_length=1000)


class Offer(BaseModel):
    # pictures of the phone, by the phone's own names for them
    media: list[str] = Field(min_length=1, max_length=1000)
    folder: str = Field(default="", max_length=200)


class Trashed(BaseModel):
    # the pictures the phone moved to its trash; none when its user said no, or when it has no trash
    ids: list[str] = Field(default=[], max_length=1000)
    why: Literal["", "declined", "old"] = ""


def stream(events) -> StreamingResponse:
    """Events as JSON lines, one per event. Closing the connection stops what is producing them."""
    async def lines():
        try:
            async for event in events:
                yield json.dumps(event) + "\n"
        except Exception as exc:
            # the status code is already sent: the failure travels as the last event
            logger.exception("a stream failed")
            yield json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache"})


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


@app.get("/api/models")
async def models():
    """The local models, what each is for, how it did when tried, and who gets each job."""
    try:
        installed = await llm.installed()
    except Exception as exc:
        # Ollama is not running, or not reachable from here: the page says so instead of breaking
        return {**catalog.describe([], catalog.hardware(), {}), "problem": f"{type(exc).__name__}: {exc}"}
    tests = selftest.load(INDEX_DIR)
    return catalog.describe(installed, catalog.hardware(installed, tests), tests)


@app.post("/api/models/test")
async def test_models():
    """Tries the models on this computer, as a stream of progress. It takes about a minute per model."""
    return stream(selftest.run(INDEX_DIR))


@app.post("/api/chat")
async def chat(body: ChatRequest):
    """A reply to the conversation, as a stream of events: words, searches, pictures found, changes proposed.

    Nothing is changed from here: a change is only proposed, and POST /api/actions carries it out.
    """
    async def events():
        installed = await llm.installed()
        history = [message.model_dump() for message in body.messages]
        tests = selftest.load(INDEX_DIR)
        reply = orchestrator.reply(history, body.model, installed, catalog.hardware(installed, tests), tests, photos, actions, body.selection, phones, places)
        async for event in reply:
            yield event

    return stream(events())


@app.get("/api/photos")
def photo_library(request: Request):
    """How many pictures are known, and whether more are being read right now."""
    return {
        **photos.state,
        # "running" from the moment a reading is asked for, not only once it has counted the files:
        # the page asks again soon only while it is running
        "running": photos.state["running"] or _reading,
        "indexed": len(photos.photos),
        "folder": os.getenv("PHOTOS_LABEL", ""),
        # which door the page came through: inside a phone's app it does not show what is only the computer's business
        "door": "phone" if getattr(request.state, "device", None) else "computer",
    }


@app.post("/api/photos/read")
def read_again():
    """Looks at the folder again, for pictures that were added or removed."""
    read_photos()
    return {"started": True}


@app.get("/api/photos/{identifier}/thumb")
def thumbnail(identifier: str, request: Request):
    data = phones.thumbnail(identifier) if on_phone(identifier) else photos.thumbnail(identifier)
    if data is None:
        raise HTTPException(status_code=404, detail="no such picture")
    # the browser may keep a small copy, but asks every time whether it is still the right one:
    # a picture can be replaced by another with the same name
    tag = f'"{hashlib.sha1(data).hexdigest()[:16]}"'
    headers = {"Cache-Control": "private, no-cache", "ETag": tag}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    return Response(data, media_type="image/jpeg", headers=headers)


@app.get("/api/photos/{identifier}/full")
def full(identifier: str):
    if on_phone(identifier):
        # the picture itself is on the phone: what this computer has of it is the small copy
        data = phones.thumbnail(identifier)
        if data is None:
            raise HTTPException(status_code=404, detail="no such picture")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, no-cache"})
    path = photos.path_of(identifier)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="no such picture")
    return FileResponse(path, headers={"Cache-Control": "private, no-cache"})


@app.get("/api/actions")
def changes():
    """Whether the pictures can be changed, how much is in the trash, and the last change that can be taken back."""
    last = actions.last()
    return {
        "writable": actions.writable(),
        "trash": actions.in_trash(),
        "last": last and {"id": last["id"], "kind": last["kind"], "count": len(last["files"]), "folder": last.get("folder", ""), "when": last["when"]},
    }


def _carried_out(work):
    """Runs a change the user confirmed, and turns what can go wrong into an answer the page can show."""
    try:
        return work()
    except Refused as refused:
        raise HTTPException(status_code=409, detail=str(refused))
    except OSError as exc:
        logger.exception("a change failed")
        raise HTTPException(status_code=500, detail=f"Non riesco a scrivere nella cartella delle foto ({type(exc).__name__}: {exc}).")
    finally:
        # whatever happened, the folder may not be as the index remembers it
        read_photos()


@app.post("/api/actions")
def act(body: Change):
    """Carries out a change the user has confirmed in the page: pictures to the trash, copied into a folder, or asked of a phone.

    This is the only way a picture is ever moved or copied. No model can call it: the
    page does, when the user says yes to a proposal.
    """
    if body.action in ("fetch", "clear"):
        return _ask_phone(body)
    if body.action == "send":
        return _send_to_phone(body)
    known = {identifier: relative for identifier in dict.fromkeys(body.ids) if (relative := photos.relative_of(identifier))}
    result = _carried_out(lambda: actions.trash(list(known.values())) if body.action == "trash" else actions.copy(list(known.values()), body.folder))
    # a picture the index no longer knows is one that is no longer there
    result["missing"] += len(set(body.ids)) - len(known)
    gone = []
    if body.action == "trash":
        moved = {file["from"] for file in result["files"]}
        gone = [identifier for identifier, relative in known.items() if relative in moved]
        # at once, so that a search made right now does not show what was just thrown away
        photos.forget(gone)
    text, memory = orchestrator.done_in_words(result)
    return _outcome(result, gone, text, memory)


@app.post("/api/actions/albums")
def make_albums(body: Albums):
    """Copies pictures into an album for each trip, all at once: one change, taken back as one. Asked by the page after a yes."""
    groups = [(album.folder, [relative for identifier in dict.fromkeys(album.ids) if (relative := photos.relative_of(identifier))]) for album in body.albums]
    asked = sum(len(set(album.ids)) for album in body.albums)
    result = _carried_out(lambda: actions.albums([(folder, relatives) for folder, relatives in groups if relatives]))
    result["missing"] += asked - sum(len(relatives) for _, relatives in groups)
    text, memory = orchestrator.done_in_words(result)
    return _outcome(result, [], text, memory)


def _ask_phone(body: Change) -> dict:
    """Asks a phone for the originals of some of its pictures. They arrive later, when its app is open.

    With "clear" the phone is then asked to move them to its trash: the copies have a folder of their own.
    """
    if not actions.writable():
        raise HTTPException(status_code=409, detail=orchestrator.READ_ONLY)
    clear = body.action == "clear"
    try:
        folder = collection_name(orchestrator.REMOVED if clear else body.folder)
        asked = phones.ask(body.ids, folder, "trash" if clear else "")
    except Refused as refused:
        raise HTTPException(status_code=409, detail=str(refused))
    text, memory = orchestrator.asked_in_words(len(asked["photos"]), folder, clear)
    waiting = {"kind": body.action, "id": "", "count": 0, "missing": 0, "failed": 0, "folder": folder}
    # the page follows the request by this name, until the pictures have arrived
    return {**_outcome(waiting, [], text, memory), "transfer": asked["id"]}


def _send_to_phone(body: Change) -> dict:
    """Prepares pictures of this computer for the phone. It takes them into an album when its app is open."""
    receiver = phones.receiver()
    if receiver is None:
        raise HTTPException(status_code=409, detail=orchestrator.NO_PHONE)
    chosen = [{"id": identifier, "name": Path(relative).name} for identifier in dict.fromkeys(body.ids) if (relative := photos.relative_of(identifier))]
    if not chosen:
        raise HTTPException(status_code=409, detail="Quelle foto non le trovo più.")
    try:
        folder = collection_name(body.folder or orchestrator.FROM_COMPUTER)
    except Refused as refused:
        raise HTTPException(status_code=409, detail=str(refused))
    sending = phones.send(receiver["id"], chosen, folder)
    text, memory = orchestrator.sent_in_words(len(chosen), folder)
    waiting = {"kind": "send", "id": "", "count": 0, "missing": 0, "failed": 0, "folder": folder}
    # the page follows it as it follows a request to the phone, until the phone has taken them
    return {**_outcome(waiting, [], text, memory), "transfer": sending["id"]}


@app.post("/api/actions/undo")
def undo(body: Undo):
    """Takes back a change, the last one unless another is named. Asked by the page when the user says so."""
    result = _carried_out(lambda: actions.undo(body.of))
    # the pictures that came home have the short names they had: the page can show them again
    back = [photo_id(file["to"]) for file in result["files"]] if result["undid"] == "trash" else []
    text, memory = orchestrator.undone_in_words(result)
    return _outcome(result, back, text, memory)


def _outcome(result: dict, ids: list[str], text: str, memory: str) -> dict:
    """What the page learns of a change: what happened and to which pictures, never where the files are."""
    return {
        "kind": result["kind"],
        "id": result.get("id", ""),
        "count": result["count"],
        "missing": result["missing"],
        "failed": result["failed"],
        "ids": ids,
        "folder": result.get("folder", ""),
        "text": text,
        "memory": memory,
    }


@app.get("/api/transfers/{transfer}")
def transfer_state(transfer: str):
    """How far a request to a phone is: how many pictures have arrived, and what to say when all have."""
    sending = phones.sending(transfer)
    if sending is not None:
        received, total = len(sending["received"]), len(sending["photos"])
        if sending["state"] == "done":
            text, memory = orchestrator.delivered_in_words(received, len(sending["missing"]), sending["folder"])
        else:
            text, memory = f"Aspetto il telefono: {received} di {total} arrivate sul telefono. Tieni Regista aperto sul telefono.", ""
        return {"id": sending["id"], "state": sending["state"], "arrived": received, "total": total, "folder": sending["folder"],
                "entry": "", "gone": [], "text": text, "memory": memory}
    found = phones.transfer(transfer)
    if found is None:
        raise HTTPException(status_code=404, detail="no such request")
    arrived, total = len(found["arrived"]), len(found["photos"])
    clear, trashed = found.get("then") == "trash", found.get("trashed", [])
    if found["state"] == "confirming":
        text, memory = orchestrator.confirming_in_words(arrived, found["folder"]), ""
    elif found["state"] != "done":
        text, memory = f"Aspetto il telefono: {arrived} di {total} arrivate. Tieni Regista aperto sul telefono.", ""
    elif clear:
        text, memory = orchestrator.cleared_in_words(arrived, len(trashed), total - arrived, found.get("why", ""), found["folder"])
    else:
        text, memory = orchestrator.received_in_words(arrived, total - arrived, found["folder"])
    return {
        "id": found["id"],
        "state": found["state"],
        "arrived": arrived,
        "total": total,
        "folder": found["folder"],
        # "entry" names the arrival in the journal of changes: with it the page can take it back at a click.
        # Not when the pictures left the phone: then the copies here are the ones that stay, and taking
        # them away is asked in words, where it can be explained.
        "entry": "" if trashed else found["entry"],
        # the pictures that are no longer on the phone
        "gone": trashed,
        "text": text,
        "memory": memory,
    }


# ---- the phones, as this computer sees them: only from this computer's door


@app.get("/api/phone")
def phone_state():
    """Whether phones can connect, where they find this computer, and the ones that were let in."""
    return {"open": PHONE_OPEN, "addresses": phones.addresses, "devices": phones.described(), "pending": phones.waiting(), "refused": phones.knocks()}


@app.post("/api/phone/invite")
def invite():
    """A link that lets one phone in, good for a few minutes, also as a QR code to point the phone's camera at."""
    made = phones.invite()
    # as a picture the page can show as it is: dark on white, which is what a camera reads
    code = segno.make(made["link"], error="m").svg_data_uri(scale=5, border=2, dark="#17131f", light="#ffffff")
    return {**made, "qr": code}


@app.post("/api/phone/pending/{request}")
def answer_phone(request: str, body: Answer):
    """The user's answer to a phone that asks to come in. Given only here, on this computer: never from a phone."""
    if not phones.answer(request, body.yes):
        raise HTTPException(status_code=404, detail="Questa richiesta non c'è più: rifai il collegamento dal telefono.")
    return {"answered": body.yes}


@app.post("/api/phone/devices/{device}/forget")
def forget_phone(device: str):
    """Shuts a phone out. Its key stops working at once."""
    if not phones.forget_device(device):
        raise HTTPException(status_code=404, detail="no such phone")
    return {"forgotten": True}


# ---- what a phone says to this computer: only from the door of the phones


@app.post("/phone/pair")
def pair(body: Pairing):
    """A phone that shows the secret of a code still good asks to come in. It waits for a yes on this computer, and gets a ticket to learn it."""
    try:
        return phones.pair(body.secret, body.name)
    except Refused as refused:
        raise HTTPException(status_code=403, detail=str(refused))


@app.post("/phone/pair/wait")
def pair_wait(body: Ticket):
    """Whether the user said yes on this computer to the phone with this ticket; with the yes, once, the key it will show from now on."""
    try:
        return phones.collect(body.ticket)
    except Refused as refused:
        raise HTTPException(status_code=403, detail=str(refused))


@app.get("/phone/hello")
def hello(request: Request):
    """Tells a phone that its key is good, and how many of its pictures this computer knows."""
    device = request.state.device
    return {"computer": phones.computer, "photos": sum(1 for photo in phones.photos if photo["device"] == device)}


@app.post("/phone/library")
def library(body: Listing, request: Request):
    """A phone says which pictures it has; the answer is the ones this computer needs a small copy of."""
    return {"wanted": phones.wanted(request.state.device, [photo.model_dump() for photo in body.photos])}


@app.post("/phone/photos")
def small_copies(body: SmallCopies, request: Request):
    """A phone sends small copies of some of its pictures."""
    return {"kept": phones.add(request.state.device, [photo.model_dump() for photo in body.photos])}


@app.post("/phone/vectors")
def phone_vectors(body: Asked, request: Request):
    """What this computer has read in some pictures of a phone: an old phone takes a second to look at each, and this was done already."""
    return {"vectors": phones.vectors_of(request.state.device, [photo.model_dump() for photo in body.photos])}


@app.post("/phone/ask")
async def phone_ask(body: Typed, request: Request):
    """A request typed on a phone's own screen, understood by this computer's director: the pictures of that phone it asks for.

    "answer" is null when this computer has nothing to add, or cannot ask its models now: then the phone answers alone.
    """
    try:
        installed = await llm.installed()
        tests = selftest.load(INDEX_DIR)
        found = await orchestrator.on_the_phone(body.text, request.state.device, phones, places, installed, catalog.hardware(installed, tests), tests)
    except Exception:
        # Ollama is off, or a model failed: the phone has its own answer already
        logger.exception("a request from a phone could not be understood here")
        found = None
    return {"answer": found}


@app.post("/phone/library/done")
def library_done():
    """A phone says it has sent everything: what was learned is written down."""
    phones.save()
    return {"saved": True}


@app.get("/phone/work")
def work(request: Request):
    """What a phone is asked to do: send the pictures the user wanted on this computer, and take the ones this computer prepared for it."""
    device = request.state.device
    return {"transfers": phones.work(device), "incoming": phones.incoming(device)}


@app.get("/phone/incoming/{sending}/photos/{identifier}")
def picture_for_the_phone(sending: str, identifier: str, request: Request):
    """The original of a picture this computer sends to a phone, with what it is, for the phone to check what arrives."""
    if not phones.offered(sending, request.state.device, identifier):
        raise HTTPException(status_code=409, detail="Questa foto non è stata mandata a questo telefono.")
    path = photos.path_of(identifier)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="no such picture")
    seen = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            seen.update(chunk)
    return FileResponse(path, headers={"X-Regista-Sha256": seen.hexdigest(), "Cache-Control": "no-store"})


@app.post("/phone/incoming/{sending}/received")
def taken_by_the_phone(sending: str, body: Received, request: Request):
    """A phone says which of the pictures prepared for it it took, and which it could not."""
    return {"noted": phones.delivered(sending, request.state.device, body.ids, body.missing) is not None or bool(phones.sending(sending))}


# what each model file is, worked out once: they are hundreds of MB
_fingerprints: dict[tuple, str] = {}


def _fingerprint(path: Path) -> str:
    known = (path.name, path.stat().st_size, path.stat().st_mtime)
    if known not in _fingerprints:
        seen = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1 << 20), b""):
                seen.update(chunk)
        _fingerprints[known] = seen.hexdigest()
    return _fingerprints[known]


@app.get("/phone/models")
def models_for_the_phone():
    """The models a phone can take from this computer to look at pictures by itself: each with its size and what it is.
    None when this computer does not have all of them."""
    paths = [PHONE_MODELS / name for name in MODEL_FILES]
    if not all(path.is_file() for path in paths):
        return {"models": []}
    return {"models": [{"name": path.name, "size": path.stat().st_size, "sha256": _fingerprint(path)} for path in paths]}


@app.get("/phone/models/{name}")
def model_for_the_phone(name: str):
    """One of those models, with what it is, for the phone to check what arrives."""
    path = PHONE_MODELS / name
    if name not in MODEL_FILES or not path.is_file():
        raise HTTPException(status_code=404, detail="no such model")
    return FileResponse(path, headers={"X-Regista-Sha256": _fingerprint(path), "Cache-Control": "no-store"})


@app.post("/phone/offer")
def offered_by_the_phone(body: Offer, request: Request):
    """A phone asks this computer to take some of its pictures. They arrive as the ones the computer asks for do,
    and can be taken back as those can."""
    if not actions.writable():
        raise HTTPException(status_code=409, detail=orchestrator.READ_ONLY)
    device = request.state.device
    known = {photo["media"]: photo["id"] for photo in phones.photos if photo["device"] == device}
    chosen = [known[media] for media in dict.fromkeys(body.media) if media in known]
    if not chosen:
        raise HTTPException(status_code=409, detail="Il computer non conosce ancora queste foto: riprova tra poco.")
    try:
        folder = collection_name(body.folder or orchestrator.FROM_THE_PHONE)
        asked = phones.ask(chosen, folder)
    except Refused as refused:
        raise HTTPException(status_code=409, detail=str(refused))
    return {"transfer": asked["id"], "count": len(asked["photos"]), "unknown": len(body.media) - len(chosen), "folder": folder}


@app.put("/phone/transfers/{transfer}/photos/{identifier}")
async def original(transfer: str, identifier: str, request: Request):
    """A phone sends a picture it was asked for. It lands in the folder the user chose, under a name that is free."""
    device = request.state.device
    try:
        expected = phones.expected(transfer, device, identifier)
        partial = actions.incoming(expected["folder"])
    except Refused as refused:
        raise HTTPException(status_code=409, detail=str(refused))
    # What the phone says the picture is, as the SHA-256 of its bytes. A picture that is to leave the
    # phone must come with it: what arrives is then known to be the picture, whole, before the phone is
    # told that it may throw its own away.
    said = request.headers.get("x-regista-sha256", "").lower()
    if expected["then"] == "trash" and not said:
        raise HTTPException(status_code=400, detail="Per togliere foto dal telefono serve la versione nuova dell'app.")
    size, seen = 0, hashlib.sha256()
    try:
        with partial.open("wb") as file:
            async for chunk in request.stream():
                size += len(chunk)
                if size > LARGEST:
                    raise HTTPException(status_code=413, detail="too large")
                seen.update(chunk)
                file.write(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="nothing arrived")
        if said and said != seen.hexdigest():
            raise HTTPException(status_code=400, detail="La foto non è arrivata intera.")
        where = actions.land(partial, expected["name"])
    except BaseException:
        # what stopped halfway is not a picture
        partial.unlink(missing_ok=True)
        raise
    _arrived(phones.settle(transfer, device, arrived={identifier: where}))
    return {"kept": True}


@app.post("/phone/transfers/{transfer}/trashed")
def moved_to_its_trash(transfer: str, body: Trashed, request: Request):
    """A phone says what it did with the pictures it could move to its trash: which ones, or why none."""
    found = phones.trashed(transfer, request.state.device, body.ids, body.why)
    if found is not None and found["trashed"] and found["entry"]:
        actions.cleared(found["entry"], len(found["trashed"]))
    return {"noted": found is not None}


@app.post("/phone/transfers/{transfer}/missing")
def not_sent(transfer: str, body: NotSent, request: Request):
    """A phone says which of the pictures it was asked for it cannot send: they are no longer waited for."""
    _arrived(phones.settle(transfer, request.state.device, missing=body.ids))
    return {"noted": True}


def _arrived(finished: dict | None) -> None:
    """When the last picture of a request has arrived, the arrival is written in the journal: it can be taken back like any copy."""
    if finished is None:
        return
    files = [{"from": f"telefono:{identifier}", "to": where} for identifier, where in finished["arrived"].items()]
    phones.close(finished["id"], actions.arrived(files, finished["folder"])["id"])


# The page, built into "static" when the image is made, or where the program of the PC keeps it. Mounted last: everything above wins.
PAGE_DIR = os.getenv("PAGE_DIR", "static")
if Path(PAGE_DIR).is_dir():
    app.mount("/", StaticFiles(directory=PAGE_DIR, html=True), name="page")
