"""The service behind the page: the models, the chat, the pictures. It also serves the page itself."""
import hashlib
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

import catalog
import llm
import orchestrator
import selftest
from actions import Actions, Refused
from embedder import ClipEmbedder
from photos import PhotoIndex, photo_id

logger = logging.getLogger("uvicorn.error")
INDEX_DIR = os.getenv("INDEX_DIR", "index")
PHOTOS_DIR = os.getenv("PHOTOS_DIR", "foto")
photos = PhotoIndex(PHOTOS_DIR, INDEX_DIR, ClipEmbedder())
actions = Actions(PHOTOS_DIR)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    read_photos()
    yield


app = FastAPI(title="regista", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None, lifespan=lifespan)
# The service answers only when it is called by one of its own names. Without this, a page
# anywhere on the internet could point a name of its own at this computer and, from the user's
# browser, look at the pictures and move them.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(","))


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
    action: Literal["trash", "copy"]
    # pictures by their short names: the page never names a file
    ids: list[str] = Field(min_length=1, max_length=1000)
    folder: str = Field(default="", max_length=200)


class Undo(BaseModel):
    # the change to take back; empty for the last one
    of: str = Field(default="", max_length=40)


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
        reply = orchestrator.reply(history, body.model, installed, catalog.hardware(), selftest.load(INDEX_DIR), photos, actions, body.selection)
        async for event in reply:
            yield event

    return stream(events())


@app.get("/api/photos")
def photo_library():
    """How many pictures are known, and whether more are being read right now."""
    # "running" from the moment a reading is asked for, not only once it has counted the files:
    # the page asks again soon only while it is running
    return {**photos.state, "running": photos.state["running"] or _reading, "indexed": len(photos.photos), "folder": os.getenv("PHOTOS_LABEL", "")}


@app.post("/api/photos/read")
def read_again():
    """Looks at the folder again, for pictures that were added or removed."""
    read_photos()
    return {"started": True}


@app.get("/api/photos/{identifier}/thumb")
def thumbnail(identifier: str, request: Request):
    data = photos.thumbnail(identifier)
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
    """Carries out a change the user has confirmed in the page: pictures to the trash, or copied into a folder.

    This is the only way a picture is ever moved or copied. No model can call it: the
    page does, when the user says yes to a proposal.
    """
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


# The page, built into "static" when the image is made. Mounted last: everything above wins.
if Path("static").is_dir():
    app.mount("/", StaticFiles(directory="static", html=True), name="page")
