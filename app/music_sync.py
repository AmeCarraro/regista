"""Pairing-scoped additive music sync and the PC's local playlists."""
import asyncio
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import threading
import time
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

SHA = r"^[a-f0-9]{64}$"
JOB = r"^[a-f0-9]{32}$"
ACTIVE = {"scanning", "copying"}
LIMIT = 100_000


class DeviceChoice(BaseModel):
    device: str = Field(default="", max_length=100)


class Start(BaseModel):
    request: str = Field(default="", max_length=64)


class Plan(BaseModel):
    job: str = Field(pattern=JOB)
    hashes: list[Annotated[str, Field(pattern=SHA)]] = Field(max_length=LIMIT)


class Progress(BaseModel):
    job: str = Field(pattern=JOB)
    state: Literal["scanning", "copying", "ready", "error"]
    sent: int = Field(default=0, ge=0, le=LIMIT)
    received: int = Field(default=0, ge=0, le=LIMIT)
    error: str = Field(default="", max_length=400)


class TrackTags(BaseModel):
    track: str = Field(pattern=r"^[a-f0-9]{16}$")
    tags: str = Field(default="", max_length=1200)


class Playlist(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    query: str = Field(default="", max_length=200)
    tag: str = Field(default="", max_length=1200)


@dataclass
class SyncJob:
    id: str
    device: str
    state: str
    updated: float = field(default_factory=time.monotonic)
    sent: int = 0
    received: int = 0
    to_pc: int = 0
    to_phone: int = 0
    error: str = ""
    wanted: set[str] = field(default_factory=set)

    def summary(self):
        state = self.state
        error = self.error
        if state in ACTIVE and time.monotonic() - self.updated > 900:
            state, error = "error", "Il telefono si è scollegato. Premi Sincronizza per riprendere."
        return {key: getattr(self, key) for key in ("id", "device", "sent", "received", "to_pc", "to_phone")} | {
            "state": state, "error": error,
        }


class MusicSync:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs: dict[str, SyncJob] = {}

    def queue(self, phone: str):
        with self.lock:
            job = self.jobs.get(phone)
            if not job or job.summary()["state"] not in ACTIVE | {"requested"}:
                job = self.jobs[phone] = SyncJob(uuid.uuid4().hex, phone, "requested")
            return job.summary()

    def pending(self, phone: str):
        with self.lock:
            job = self.jobs.get(phone)
            return job.id if job and job.state == "requested" else ""

    def start(self, phone: str, request: str):
        with self.lock:
            pending = self.pending(phone)
            if request and request != pending:
                raise HTTPException(409, "La richiesta di sincronizzazione è cambiata.")
            job = self.jobs[phone] = SyncJob(pending or uuid.uuid4().hex, phone, "scanning")
            return job.summary()

    def current(self, phone, identifier):
        job = self.jobs.get(phone)
        if job is None or job.id != identifier or job.state not in ACTIVE:
            raise HTTPException(409, "Avvia di nuovo Sincronizza nella scheda Musica.")
        return job

    def plan(self, phone, body, music):
        with self.lock:
            self.current(phone, body.job)
        try:
            tracks = music.sync_catalog()
        except OSError as error:
            raise HTTPException(409, "Un brano sul PC è cambiato durante il controllo. Riprova.") from error
        existing = set(body.hashes)
        wanted = existing - tracks.keys()
        download = [tracks[sha] for sha in tracks if sha not in existing]
        with self.lock:
            job = self.current(phone, body.job)
            job.state = "copying"
            job.to_pc, job.to_phone, job.wanted = len(wanted), len(download), wanted
            job.updated = time.monotonic()
        return {"wanted": sorted(wanted), "download": download}

    def progress(self, phone, body):
        with self.lock:
            job = self.current(phone, body.job)
            job.state, job.sent, job.received, job.error = body.state, body.sent, body.received, body.error
            job.updated = time.monotonic()
            return job.summary()

    def upload(self, phone, identifier, sha):
        with self.lock:
            job = self.current(phone, identifier)
            if job.state != "copying" or sha not in job.wanted:
                raise HTTPException(409, "Il brano non appartiene alla sincronizzazione.")
            job.updated = time.monotonic()

    def status(self, phones):
        with self.lock:
            devices = [{"id": phone["id"], "name": phone["name"]} for phone in phones.devices]
            jobs = [self.jobs[phone["id"]].summary() for phone in devices if phone["id"] in self.jobs]
            return {"devices": devices, "jobs": jobs}


class MusicCollections:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {"tags": {}, "playlists": {}}

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pending = self.path.with_suffix(".tmp")
        try:
            with pending.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            pending.replace(self.path)
        finally:
            pending.unlink(missing_ok=True)
        return data

    def label(self, body):
        with self.lock:
            data = self.read()
            tags = {part.strip().casefold(): part.strip() for part in body.tags.split(",") if part.strip()}
            if tags:
                data["tags"][body.track] = list(tags.values())[:30]
            else:
                data["tags"].pop(body.track, None)
            return self.save(data)

    def playlist(self, body):
        name = body.name.strip()
        if not name or not (body.tag.strip() or body.query.strip()):
            raise HTTPException(400, "Dai un nome alla playlist e scegli un tag, un genere o una ricerca.")
        with self.lock:
            data = self.read()
            data["playlists"][name.casefold()] = {"name": name, "query": body.query.strip(), "tag": body.tag.strip()}
            return self.save(data)


def routes(sync, get_music, get_phones, index):
    router = APIRouter()
    collections = MusicCollections(Path(index) / "music-library.json")

    def local(request):
        if getattr(request.state, "device", None):
            raise HTTPException(403, "Questo comando si usa dal PC.")

    def device(request):
        phone = getattr(request.state, "device", None)
        if not phone:
            raise HTTPException(403, "Serve un telefono collegato.")
        return phone

    @router.get("/api/music-sync")
    def status(request: Request):
        local(request)
        return sync.status(get_phones())

    @router.post("/api/music-sync")
    def request_sync(body: DeviceChoice, request: Request):
        local(request)
        devices = get_phones().devices
        target = body.device or (devices[0]["id"] if len(devices) == 1 else "")
        if not any(item["id"] == target for item in devices):
            raise HTTPException(409, "Scegli un telefono associato a Regista.")
        return sync.queue(target)

    @router.get("/phone/music-sync/pending")
    def pending(request: Request):
        return {"request": sync.pending(device(request))}

    @router.post("/phone/music-sync/start")
    def start(body: Start, request: Request):
        return sync.start(device(request), body.request)

    @router.post("/phone/music-sync/plan")
    async def plan(body: Plan, request: Request):
        return await asyncio.to_thread(sync.plan, device(request), body, get_music())

    @router.post("/phone/music-sync/progress")
    def progress(body: Progress, request: Request):
        return sync.progress(device(request), body)

    @router.get("/api/music-library")
    def labels(request: Request):
        local(request)
        return collections.read()

    @router.post("/api/music-library/tags")
    def label(body: TrackTags, request: Request):
        local(request)
        if get_music().path(body.track) is None:
            raise HTTPException(404, "Brano non disponibile.")
        return collections.label(body)

    @router.post("/api/music-library/playlists")
    def playlist(body: Playlist, request: Request):
        local(request)
        return collections.playlist(body)

    return router
