"""The service behind the page: the models, the chat, the pictures, the phones. It also serves the page itself.

It has two doors. One is for this computer, and answers only here. The other is for the
phones the user has let in: encrypted, on a port of its own, and closed to everyone else.
"""
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

logger = logging.getLogger("uvicorn.error")
INDEX_DIR = os.getenv("INDEX_DIR", "index")
PHOTOS_DIR = os.getenv("PHOTOS_DIR", "foto")
# the names this computer's door answers to
HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
# the door of the phones, inside the container and as it is seen from outside
PHONE_PORT = int(os.getenv("PHONE_PORT", "8443"))
# whether whoever started the app opened that door to the network (run.ps1 -Phone)
PHONE_OPEN = os.getenv("PHONE_OPEN", "") == "1"
# the largest picture a phone may send
LARGEST = 400 * 1024 * 1024

photos = PhotoIndex(PHOTOS_DIR, INDEX_DIR, ClipEmbedder())
actions = Actions(PHOTOS_DIR)
phones = Phones(
    str(Path(INDEX_DIR) / "phone"),
    photos.embedder,
    # where a phone finds this computer: only whoever started the app can know it
    [address for address in os.getenv("HOST_ADDRESSES", "").split(",") if address],
    int(os.getenv("PHONE_PUBLIC_PORT") or PHONE_PORT),
    os.getenv("HOST_NAME", ""),
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
    """Starts the door of the phones: the same service, encrypted, on a port of its own."""
    certificate, key = phones.certificate()
    door = uvicorn.Config(app, host="0.0.0.0", port=PHONE_PORT, ssl_certfile=str(certificate), ssl_keyfile=str(key), lifespan="off", log_level="info")
    threading.Thread(target=uvicorn.Server(door).run, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    read_photos()
    try:
        open_phone_door()
    except Exception:
        # without it the app still does everything else: the page says that no phone can connect
        logger.exception("the door of the phones did not open")
    yield


app = FastAPI(title="regista", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None, lifespan=lifespan)


class Gate:
    """Who may come in, by the door they knock at.

    This computer's door answers only when it is called by one of its own names: without
    that, a page anywhere on the internet could point a name of its own at this computer
    and, from the user's browser, look at the pictures and move them.

    The door of the phones answers only to a phone that was let in, and that shows its key
    with every request. The one exception is the request that lets a phone in, which shows
    the secret of the link instead. A phone cannot let other phones in.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        headers = {name: value.decode("latin-1") for name, value in scope["headers"]}
        path = scope["path"]

        if (scope.get("server") or ("", 0))[1] != PHONE_PORT:
            if headers.get(b"host", "").rsplit(":", 1)[0] not in HOSTS:
                return await self._refuse(send, 400, "Invalid host header")
            if path.startswith("/phone/"):
                return await self._refuse(send, 404, "Not Found")
            return await self.inner(scope, receive, send)

        if path == "/phone/pair":
            return await self.inner(scope, receive, send)
        shown = headers.get(b"authorization", "")
        key = shown[7:] if shown.startswith("Bearer ") else ""
        kept = SimpleCookie(headers.get(b"cookie", "")).get("regista")
        device = phones.device_of(key or (kept.value if kept else ""))
        if device is None:
            return await self._refuse(send, 401, "Questo telefono non è collegato.")
        if path.startswith("/api/phone"):
            return await self._refuse(send, 403, "I telefoni si collegano e si scollegano dal computer.")
        scope.setdefault("state", {})["device"] = device["id"]

        async def remembering(message):
            # the page inside the phone's app cannot show the key by itself: after the first
            # request, which the app makes with the key, the browser part carries it as a cookie
            if message["type"] == "http.response.start" and key and not kept:
                cookie = f"regista={key}; Path=/; Max-Age=31536000; HttpOnly; Secure; SameSite=Strict"
                message = {**message, "headers": [*message.get("headers", []), (b"set-cookie", cookie.encode())]}
            await send(message)

        await self.inner(scope, receive, remembering)

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
    # "fetch" asks a phone for the originals of pictures that are on it
    action: Literal["trash", "copy", "fetch"]
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


class Listed(BaseModel):
    id: str = Field(max_length=40)
    stamp: str = Field(default="", max_length=60)


class Listing(BaseModel):
    photos: list[Listed] = Field(max_length=300_000)


class SmallCopy(Listed):
    name: str = Field(default="", max_length=300)
    # when it was taken, in milliseconds
    taken: int = 0
    # a JPEG a few hundred pixels wide, as base64
    jpeg: str


class SmallCopies(BaseModel):
    photos: list[SmallCopy] = Field(min_length=1, max_length=BATCH)


class NotSent(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=1000)


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
    return catalog.describe(installed, catalog.hardware(), selftest.load(INDEX_DIR))


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
        reply = orchestrator.reply(history, body.model, installed, catalog.hardware(), selftest.load(INDEX_DIR), photos, actions, body.selection, phones)
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
    if body.action == "fetch":
        return _ask_phone(body)
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


def _ask_phone(body: Change) -> dict:
    """Asks a phone for the originals of some of its pictures. They arrive later, when its app is open."""
    if not actions.writable():
        raise HTTPException(status_code=409, detail=orchestrator.READ_ONLY)
    try:
        folder = collection_name(body.folder)
        asked = phones.ask(body.ids, folder)
    except Refused as refused:
        raise HTTPException(status_code=409, detail=str(refused))
    text, memory = orchestrator.asked_in_words(len(asked["photos"]), folder)
    waiting = {"kind": "fetch", "id": "", "count": 0, "missing": 0, "failed": 0, "folder": folder}
    # the page follows the request by this name, until the pictures have arrived
    return {**_outcome(waiting, [], text, memory), "transfer": asked["id"]}


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
    found = phones.transfer(transfer)
    if found is None:
        raise HTTPException(status_code=404, detail="no such request")
    arrived, total = len(found["arrived"]), len(found["photos"])
    if found["state"] == "done":
        text, memory = orchestrator.received_in_words(arrived, total - arrived, found["folder"])
    else:
        text, memory = f"Aspetto il telefono: {arrived} di {total} arrivate. Tieni Regista aperto sul telefono.", ""
    # "entry" names the arrival in the journal of changes: with it the page can take it back
    return {"id": found["id"], "state": found["state"], "arrived": arrived, "total": total, "folder": found["folder"], "entry": found["entry"], "text": text, "memory": memory}


# ---- the phones, as this computer sees them: only from this computer's door


@app.get("/api/phone")
def phone_state():
    """Whether phones can connect, where they find this computer, and the ones that were let in."""
    return {"open": PHONE_OPEN, "addresses": phones.addresses, "devices": phones.described()}


@app.post("/api/phone/invite")
def invite():
    """A link that lets one phone in, good for a few minutes, also as a QR code to point the phone's camera at."""
    made = phones.invite()
    # as a picture the page can show as it is: dark on white, which is what a camera reads
    code = segno.make(made["link"], error="m").svg_data_uri(scale=5, border=2, dark="#17131f", light="#ffffff")
    return {**made, "qr": code}


@app.post("/api/phone/devices/{device}/forget")
def forget_phone(device: str):
    """Shuts a phone out. Its key stops working at once."""
    if not phones.forget_device(device):
        raise HTTPException(status_code=404, detail="no such phone")
    return {"forgotten": True}


# ---- what a phone says to this computer: only from the door of the phones


@app.post("/phone/pair")
def pair(body: Pairing):
    """Lets in the phone that shows the secret of a link still good. It answers with the key the phone will show from now on."""
    try:
        return phones.pair(body.secret, body.name)
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


@app.post("/phone/library/done")
def library_done():
    """A phone says it has sent everything: what was learned is written down."""
    phones.save()
    return {"saved": True}


@app.get("/phone/work")
def work(request: Request):
    """What a phone is asked to send: the pictures the user wanted on this computer and that have not arrived yet."""
    return {"transfers": phones.work(request.state.device)}


@app.put("/phone/transfers/{transfer}/photos/{identifier}")
async def original(transfer: str, identifier: str, request: Request):
    """A phone sends a picture it was asked for. It lands in the folder the user chose, under a name that is free."""
    device = request.state.device
    try:
        expected = phones.expected(transfer, device, identifier)
        partial = actions.incoming(expected["folder"])
    except Refused as refused:
        raise HTTPException(status_code=409, detail=str(refused))
    size = 0
    try:
        with partial.open("wb") as file:
            async for chunk in request.stream():
                size += len(chunk)
                if size > LARGEST:
                    raise HTTPException(status_code=413, detail="too large")
                file.write(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="nothing arrived")
        where = actions.land(partial, expected["name"])
    except BaseException:
        # what stopped halfway is not a picture
        partial.unlink(missing_ok=True)
        raise
    _arrived(phones.settle(transfer, device, arrived={identifier: where}))
    return {"kept": True}


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


# The page, built into "static" when the image is made. Mounted last: everything above wins.
if Path("static").is_dir():
    app.mount("/", StaticFiles(directory="static", html=True), name="page")
