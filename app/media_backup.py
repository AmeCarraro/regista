"""Explicit, resumable backup of Android media to the existing verified ZIP store."""
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import tempfile
import threading
import time
from typing import Literal
import uuid
import zipfile
import zlib

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

RUN = r'^[a-f0-9]{32}$'
SHA = r'^[a-f0-9]{64}$'


def max_bytes():
    value = int(os.getenv('REGISTA_MEDIA_BACKUP_MAX_BYTES', str(64 * 1024 ** 3)))
    if value <= 0:
        raise ValueError('REGISTA_MEDIA_BACKUP_MAX_BYTES deve essere maggiore di zero.')
    return value


class MediaFile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    media: str = Field(min_length=1, max_length=300)
    stamp: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(pattern=SHA)
    name: str = Field(min_length=1, max_length=500)
    folder: str = Field(default='', max_length=2000)
    kind: Literal['image', 'audio', 'video']
    size: int = Field(ge=0, le=2 ** 63 - 1)
    mime: str = Field(default='', max_length=200)

    @field_validator('name')
    @classmethod
    def filename(cls, value):
        name = Path(PureWindowsPath(value).name).name
        if name in ('', '.', '..') or any(ord(char) < 32 for char in name):
            raise ValueError('Nome media non valido.')
        return name


class Manifest(BaseModel):
    run_id: str = Field(pattern=RUN)
    files: list[MediaFile] = Field(max_length=100)


class Progress(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: str = Field(pattern=RUN)
    total: int = Field(default=0, ge=0)
    scanned: int = Field(default=0, ge=0)
    copied: int = Field(default=0, ge=0)  # Accepted for old clients; receipts determine durable counts.
    duplicates: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    done: bool = False
    cancelled: bool = False
    error: str = Field(default='', max_length=2000)


class MediaBackup:
    def __init__(self, catalog):
        self.catalog = catalog
        self.metadata_lock = threading.RLock()
        self.database = catalog.database.parent.resolve() / 'media-backup.sqlite'
        if self.database.resolve().parent != self.database.parent:
            raise ValueError('Registro backup fuori dalla cartella indice.')
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs(device TEXT NOT NULL,run_id TEXT NOT NULL,state TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,scanned INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',
                    started REAL NOT NULL,updated REAL NOT NULL,PRIMARY KEY(device,run_id));
                CREATE TABLE IF NOT EXISTS files(device TEXT NOT NULL,run_id TEXT NOT NULL,media TEXT NOT NULL,
                    stamp TEXT NOT NULL,sha256 TEXT NOT NULL,name TEXT NOT NULL,folder TEXT NOT NULL,
                    kind TEXT NOT NULL,size INTEGER NOT NULL,mime TEXT NOT NULL,state TEXT NOT NULL,
                    duplicate INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(device,run_id,media));
                CREATE INDEX IF NOT EXISTS files_hash ON files(sha256,state);
                CREATE INDEX IF NOT EXISTS files_run ON files(device,run_id,state);''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def start(self, device):
        run = uuid.uuid4().hex
        now = time.time()
        with self.connect() as db:
            db.execute('INSERT INTO runs(device,run_id,state,started,updated) VALUES (?,?,?,?,?)', (device, run, 'running', now, now))
        self.checkpoint(device, run, {'type': 'start', 'created': now, 'coverage': 'Media e cartelle accessibili con le autorizzazioni Android concesse.'})
        return {'run_id': run, 'protocol': 1, 'max_file_bytes': max_bytes()}

    def session_path(self, device, run, suffix):
        if not re.fullmatch(RUN, run):
            raise ValueError('Identità del backup non valida.')
        root = self.catalog.archive.root
        directory = root / 'sessioni' / hashlib.sha256(device.encode()).hexdigest()
        path = directory / (run + suffix)
        if root.resolve() != root.absolute() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Manifest del backup fuori dall’archivio.')
        directory.mkdir(parents=True, exist_ok=True)
        return path

    def checkpoint(self, device, run, event):
        # Append-only discovery journal preserves aliases even if a run loses connectivity
        # before its final progress message. It travels with the original ZIP directory.
        with self.metadata_lock:
            path = self.session_path(device, run, '.jsonl')
            with path.open('ab') as target:
                target.write((json.dumps({'version': 1, 'run_id': run, **event}, ensure_ascii=False) + '\n').encode('utf-8'))
                target.flush(); os.fsync(target.fileno())

    def finish_manifest(self, device, run):
        with self.metadata_lock, self.connect() as db:
            db.execute('BEGIN')
            summary = dict(db.execute('SELECT * FROM runs WHERE device=? AND run_id=?', (device, run)).fetchone())
            summary.pop('device', None)
            files = [dict(row) for row in db.execute('SELECT media,stamp,sha256,name,folder,kind,size,mime,state,duplicate,error FROM files WHERE device=? AND run_id=? ORDER BY media', (device, run))]
            path = self.session_path(device, run, '.json')
            fd, name = tempfile.mkstemp(prefix=run + '-', suffix='.part', dir=path.parent)
            partial = Path(name)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as target:
                    json.dump({'version': 1, 'archive_layout': '<sha256[:2]>/<sha256>.zip', 'run': summary,
                               'coverage': 'File accessibili con le autorizzazioni Android; dati privati delle altre app esclusi.',
                               'files': files}, target, ensure_ascii=False, indent=2)
                    target.write('\n'); target.flush(); os.fsync(target.fileno())
                os.replace(partial, path)
            finally:
                partial.unlink(missing_ok=True)

    @staticmethod
    def require_run(db, device, run):
        result = db.execute('SELECT * FROM runs WHERE device=? AND run_id=?', (device, run)).fetchone()
        if result is None:
            raise HTTPException(404, 'Sessione di backup non presente per questo telefono.')
        if result['state'] in ('completed', 'cancelled'):
            raise HTTPException(409, 'Sessione terminata: avvia un nuovo backup.')
        return result

    def archived(self, sha, size=None):
        path = self.catalog.archive.path(sha)
        if path.is_file():
            try:
                manifest = self.catalog.archive.inspect(path, sha)
                if size is not None and manifest['size'] != size:
                    raise HTTPException(409, 'Dimensione del manifesto diversa dall’originale già verificato.')
                return True
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, EOFError, zlib.error):
                pass
        # A PC photo may already be present but not have reached the archive queue yet.
        source = self.catalog.verified_path_of(sha)
        if source is not None:
            if size is not None and source.stat().st_size != size:
                raise HTTPException(409, 'Dimensione del manifesto diversa dall’originale già presente.')
            self.catalog.archive.ensure(source, sha, verify=True)
            return True
        return False

    def manifest(self, device, body):
        with self.connect() as db:
            self.require_run(db, device, body.run_id)
        if len({item.media for item in body.files}) != len(body.files):
            raise HTTPException(400, 'Identificativi ripetuti nel manifesto.')
        sizes = {}
        for item in body.files:
            if item.sha256 in sizes and sizes[item.sha256] != item.size:
                raise HTTPException(400, 'Lo stesso contenuto ha dimensioni incoerenti nel manifesto.')
            sizes[item.sha256] = item.size
        if any(item.size > max_bytes() for item in body.files):
            raise HTTPException(413, 'Un file supera il limite tecnico configurato sul PC.')
        known = {}
        for item in body.files:
            if item.sha256 not in known:
                known[item.sha256] = self.archived(item.sha256, item.size)
        with self.connect() as db:
            self.require_run(db, device, body.run_id)
            for item in body.files:
                old = db.execute('SELECT * FROM files WHERE device=? AND run_id=? AND media=?',
                                 (device, body.run_id, item.media)).fetchone()
                already = old is not None and old['sha256'] == item.sha256 and old['stamp'] == item.stamp and old['state'] == 'received'
                state = 'received' if known[item.sha256] else 'wanted'
                duplicate = old['duplicate'] if already and known[item.sha256] else int(known[item.sha256])
                db.execute('''INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(device,run_id,media)
                    DO UPDATE SET stamp=excluded.stamp,sha256=excluded.sha256,name=excluded.name,folder=excluded.folder,
                    kind=excluded.kind,size=excluded.size,mime=excluded.mime,state=excluded.state,
                    duplicate=excluded.duplicate,error='' ''',
                    (device, body.run_id, item.media, item.stamp, item.sha256, item.name, item.folder,
                     item.kind, item.size, item.mime, state, duplicate, ''))
            # At most one original is requested for each unknown hash; upload acknowledges all aliases.
            wanted, requested = [], set()
            for item in body.files:
                if not known[item.sha256] and item.sha256 not in requested:
                    wanted.append(item.media)
                    requested.add(item.sha256)
            db.execute('UPDATE runs SET updated=? WHERE device=? AND run_id=?', (time.time(), device, body.run_id))
        self.checkpoint(device, body.run_id, {'type': 'manifest', 'files': [item.model_dump() for item in body.files]})
        return {'wanted': wanted, 'protocol': 1}

    def named(self, device, run, media, stamp):
        with self.connect() as db:
            self.require_run(db, device, run)
            result = db.execute('SELECT * FROM files WHERE device=? AND run_id=? AND media=? AND stamp=?',
                                (device, run, media, stamp)).fetchone()
        if result is None:
            raise HTTPException(409, 'File cambiato o non presente nel manifesto: ripeti il backup.')
        return dict(result)

    def error(self, device, run, media, reason):
        with self.connect() as db:
            db.execute("UPDATE files SET state='error',error=? WHERE device=? AND run_id=? AND media=? AND state!='received'",
                       (reason[:2000], device, run, media))

    def keep(self, device, run, media, source, expected):
        with self.catalog.archive.lock:
            duplicate = self.archived(expected, media['size'])
            self.catalog.archive.ensure(source, expected, media['name'], verify=True, compression=zipfile.ZIP_STORED)
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                self.require_run(db, device, run)
                previous = db.execute('SELECT state,stamp,sha256 FROM files WHERE device=? AND run_id=? AND media=?',
                    (device, run, media['media'])).fetchone()
                if previous is None or previous['stamp'] != media['stamp'] or previous['sha256'] != expected:
                    raise HTTPException(409, 'Il manifesto è cambiato durante il trasferimento. Ripeti il backup.')
                db.execute("UPDATE files SET state='error',error='Dimensione incoerente per lo stesso SHA-256' WHERE device=? AND run_id=? AND sha256=? AND size!=?", (device, run, expected, media['size']))
                db.execute("UPDATE files SET state='received',duplicate=1,error='' WHERE device=? AND run_id=? AND sha256=? AND size=? AND state!='received'",
                           (device, run, expected, media['size']))
                if previous['state'] != 'received':
                    db.execute('UPDATE files SET duplicate=? WHERE device=? AND run_id=? AND media=?',
                               (int(duplicate), device, run, media['media']))
                db.execute('UPDATE runs SET updated=? WHERE device=? AND run_id=?', (time.time(), device, run))
            self.checkpoint(device, run, {'type': 'received', 'media': media['media'], 'sha256': expected, 'duplicate': duplicate})
            return {'kept': True, 'duplicate': duplicate, 'id': expected}

    def status(self, device=None, run=None, *, local=False):
        with self.connect() as db:
            where, params = [], []
            if device is not None:
                where.append('device=?'); params.append(device)
            if run is not None:
                where.append('run_id=?'); params.append(run)
            sql = 'SELECT * FROM runs' + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY started DESC LIMIT 20'
            results = []
            for row in db.execute(sql, params).fetchall():
                counts = db.execute('''SELECT sum(CASE WHEN state='received' AND duplicate=0 THEN 1 ELSE 0 END) copied,
                    sum(CASE WHEN state='received' AND duplicate=1 THEN 1 ELSE 0 END) duplicates,
                    sum(CASE WHEN state!='received' THEN 1 ELSE 0 END) pending,
                    sum(CASE WHEN state='error' THEN 1 ELSE 0 END) errors,
                    sum(CASE WHEN state='received' THEN size ELSE 0 END) bytes FROM files WHERE device=? AND run_id=?''',
                    (row['device'], row['run_id'])).fetchone()
                result = dict(row)
                result.update({key: counts[key] or 0 for key in ('copied', 'duplicates', 'pending', 'bytes')})
                result['failed'] = max(result['failed'], counts['errors'] or 0)
                if not local:
                    result.pop('device', None)
                    if result['error']:
                        result['error'] = 'Backup non completo. Consulta il motivo sul PC o riprova.'
                else:
                    result['errors'] = [dict(item) for item in db.execute("SELECT media,name,folder,error FROM files WHERE device=? AND run_id=? AND state='error' LIMIT 20", (row['device'], row['run_id']))]
                results.append(result)
        if local:
            return {'runs': results, 'archive_root': str(self.catalog.archive.root), 'format': 'zip-per-sha256', 'protocol': 1}
        return results[0] if results else {'run_id': '', 'state': 'idle', 'total': 0, 'scanned': 0, 'copied': 0, 'duplicates': 0, 'failed': 0, 'pending': 0, 'bytes': 0, 'error': ''}

    def progress(self, device, body):
        with self.connect() as db:
            self.require_run(db, device, body.run_id)
            counted = db.execute("SELECT count(*) FROM files WHERE device=? AND run_id=? AND state='received'", (device, body.run_id)).fetchone()[0]
            complete = counted == body.total and body.scanned >= body.total and body.failed == 0 and not body.error
            state = 'cancelled' if body.cancelled else ('completed' if complete else 'incomplete') if body.done else 'running'
            error = body.error or ('Alcuni file non sono stati conservati. Ripeti il backup per riprenderli.' if body.done and not complete and not body.cancelled else '')
            failed = max(body.failed, body.total - counted) if body.done and not complete and not body.cancelled else body.failed
            db.execute('UPDATE runs SET state=?,total=?,scanned=?,failed=?,error=?,updated=? WHERE device=? AND run_id=?',
                (state, body.total, body.scanned, failed, error, time.time(), device, body.run_id))
        if body.done or body.cancelled:
            self.finish_manifest(device, body.run_id)
        return self.status(device, body.run_id)


def routes(catalog, *, read_only=False):
    router = APIRouter()
    backup = MediaBackup(catalog)

    def device(request):
        selected = getattr(request.state, 'device', None)
        if not selected:
            raise HTTPException(403, 'Serve un telefono collegato.')
        return selected

    def writable():
        if read_only:
            raise HTTPException(409, 'Backup disabilitato: archivio configurato in sola lettura.')

    @router.post('/phone/media-backup/start')
    def start(request: Request):
        selected = device(request)
        writable()
        return backup.start(selected)

    @router.post('/phone/media-backup/manifest')
    def manifest(body: Manifest, request: Request):
        selected = device(request)
        writable()
        try:
            return backup.manifest(selected, body)
        except (OSError, ValueError) as error:
            raise HTTPException(409, 'Verifica degli originali non riuscita sul PC.') from error

    @router.put('/phone/media-backup/upload')
    async def upload(request: Request, run_id: str, media: str, stamp: str):
        selected = device(request)
        writable()
        if not re.fullmatch(RUN, run_id) or not media or len(media) > 300 or len(stamp) > 1000:
            raise HTTPException(400, 'Identità del trasferimento non valida.')
        item = backup.named(selected, run_id, media, stamp)
        expected = request.headers.get('x-regista-sha256', '')
        if expected != item['sha256']:
            backup.error(selected, run_id, media, 'SHA-256 assente o diverso dal manifesto.')
            raise HTTPException(400, 'SHA-256 assente o diverso dal manifesto.')
        length = request.headers.get('content-length')
        if length is not None and (not length.isdigit() or int(length) != item['size']):
            backup.error(selected, run_id, media, 'Dimensione diversa dal manifesto.')
            raise HTTPException(400, 'Dimensione diversa dal manifesto.')
        descriptor, filename = tempfile.mkstemp(prefix='media-backup-', suffix='.part', dir=catalog.database.parent)
        partial = Path(filename)
        try:
            digest, size = hashlib.sha256(), 0
            with os.fdopen(descriptor, 'wb') as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > max_bytes() or size > item['size']:
                        raise HTTPException(413, 'File più grande del manifesto o del limite configurato.')
                    digest.update(chunk); output.write(chunk)
                output.flush(); os.fsync(output.fileno())
            if size != item['size'] or digest.hexdigest() != expected:
                raise HTTPException(400, 'Trasferimento incompleto o SHA-256 non corrispondente. Nessun file confermato.')
            committing = asyncio.create_task(asyncio.to_thread(backup.keep, selected, run_id, item, partial, expected))
            try:
                return await asyncio.shield(committing)
            except asyncio.CancelledError:
                # The ZIP writer may still hold the original open on Windows. Let it finish
                # before removing the temporary file; a retry deduplicates its verified result.
                try:
                    await asyncio.shield(committing)
                except Exception:
                    pass
                raise
        except BaseException as error:
            backup.error(selected, run_id, media, f'{type(error).__name__}: {error}')
            if isinstance(error, HTTPException):
                raise
            if isinstance(error, (OSError, ValueError, zipfile.BadZipFile)):
                raise HTTPException(409, 'Salvataggio ZIP non riuscito sul PC. L’originale resta sul telefono.') from error
            raise
        finally:
            partial.unlink(missing_ok=True)

    @router.post('/phone/media-backup/progress')
    def progress(body: Progress, request: Request):
        selected = device(request); writable()
        return backup.progress(selected, body)

    @router.get('/phone/media-backup/status')
    def status(request: Request):
        return backup.status(device(request))

    @router.get('/api/media-backup/status')
    def pc_status(request: Request):
        if getattr(request.state, 'device', None):
            raise HTTPException(403, 'Questo riepilogo si consulta sul computer.')
        return backup.status(local=True)

    @router.get('/api/media-backup/{sha256}/archive')
    def archive(sha256: str, request: Request):
        if getattr(request.state, 'device', None):
            raise HTTPException(403, 'Il ripristino del backup si esegue sul computer.')
        try:
            path = catalog.archive.path(sha256)
            catalog.archive.inspect(path, sha256)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, EOFError, zlib.error):
            raise HTTPException(404, 'ZIP originale verificato non disponibile.')
        return FileResponse(path, filename=sha256 + '.zip', media_type='application/zip')

    return router
