"""Catalog API behind Regista's existing host/pairing gate."""
import asyncio
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import zipfile
import zlib

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from photo_annotator import VERSION
from photo_search import SearchPlan, natural_plan, search

PROTOCOL = 2
MAX_UPLOAD = 400 * 1024 * 1024


class Root(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    label: str = Field(default='', max_length=100)


class Control(BaseModel):
    command: str = Field(pattern='^(start|pause|resume|idle|retry|reanalyze)$')
    ids: list[str] = Field(default_factory=list, max_length=1000)


class Correction(BaseModel):
    tag: str = Field(min_length=1, max_length=100)
    included: bool


class Natural(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class ImportPhoto(BaseModel):
    media: str = Field(min_length=1, max_length=100)
    stamp: str = Field(max_length=100)
    sha256: str = Field(pattern='^[a-f0-9]{64}$')
    name: str = Field(default='', max_length=300)


class Manifest(BaseModel):
    protocol: int
    photos: list[ImportPhoto] = Field(max_length=500)


class ImportProgress(BaseModel):
    request_id: str = Field(max_length=64)
    total: int = Field(ge=0)
    copied: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    done: bool = False
    error: str = Field(default='', max_length=1000)


def computer_only(request):
    if getattr(request.state, 'device', None):
        raise HTTPException(403, 'Questo comando si usa dal computer.')


def phone_only(request):
    device = getattr(request.state, 'device', None)
    if not device:
        raise HTTPException(403, 'Serve un telefono collegato.')
    return device


def routes(catalog, jobs, import_dir: Path, read_only=False, phones=None):
    router = APIRouter()
    catalog.organize_imports = not read_only
    from photo_storage import adopt
    adopt(catalog, import_dir)

    @router.get('/api/catalog/status')
    def status(request: Request):
        local = not getattr(request.state, 'device', None)
        state = jobs.status()
        if not local:
            state.update(errors=[], problem='', scan_error='')
        with catalog.connect() as db:
            imports = [dict(row) for row in db.execute('SELECT state,total,copied,duplicates,error FROM phone_import_requests')]
            incoming = [dict(row) for row in db.execute('''SELECT sha256,max(name) name,count(*) copies,
                CASE WHEN max(length(error))>0 THEN 'error' ELSE 'wanted' END state,max(error) error
                FROM phone_import_items WHERE state!='received' GROUP BY sha256 ORDER BY name LIMIT 20''')] if local else []
        return {**state, 'protocol': PROTOCOL, 'roots': catalog.roots(local=local), 'imports': imports if local else [],
                'incoming': incoming, 'computer': local}

    @router.post('/api/catalog/phone-import')
    def request_import(request: Request):
        computer_only(request)
        if read_only:
            raise HTTPException(409, 'Importazione disabilitata: cartella in sola lettura.')
        devices = phones.devices if phones else []
        if not devices:
            raise HTTPException(409, 'Nessun telefono collegato. Esegui prima il collegamento dal pannello Telefono.')
        import uuid
        jobs.pause()
        with catalog.connect() as db:
            for device in devices:
                db.execute('''INSERT INTO phone_import_requests(device,request_id) VALUES (?,?) ON CONFLICT(device)
                    DO UPDATE SET request_id=excluded.request_id,state='requested',total=0,copied=0,duplicates=0,error='' ''',
                           (device['id'], uuid.uuid4().hex))
        return {'devices': len(devices), 'tagging': 'paused'}

    @router.get('/phone/catalog/import-request')
    def import_request(request: Request):
        device = phone_only(request)
        with catalog.connect() as db:
            row = db.execute("SELECT request_id FROM phone_import_requests WHERE device=? AND state!='done'", (device,)).fetchone()
        return {'request_id': row[0] if row else '', 'protocol': PROTOCOL}

    @router.post('/phone/catalog/progress')
    def import_progress(body: ImportProgress, request: Request):
        device = phone_only(request)
        with catalog.connect() as db:
            db.execute('''UPDATE phone_import_requests SET state=?,total=?,copied=?,duplicates=?,error=?
                WHERE device=? AND request_id=?''', ('done' if body.done else 'copying', body.total, body.copied, body.duplicates,
                                                  body.error, device, body.request_id))
            if body.done and body.error:
                db.execute("UPDATE phone_import_items SET state='error',error=? WHERE device=? AND state!='received'",
                           (body.error, device))
        return {'noted': True}

    @router.post('/api/catalog/roots')
    def root(body: Root, request: Request):
        computer_only(request)
        try:
            return {'id': catalog.add_root(body.path, body.label)}
        except (OSError, ValueError) as error:
            raise HTTPException(400, str(error))

    @router.post('/api/catalog/scan')
    async def scan(request: Request):
        computer_only(request)
        return await asyncio.to_thread(catalog.scan, VERSION)

    @router.post('/api/catalog/control')
    async def control(body: Control, request: Request):
        computer_only(request)
        try:
            if body.command == 'pause':
                jobs.pause()
            elif body.command == 'retry':
                jobs.retry()
            elif body.command == 'reanalyze':
                if not body.ids:
                    raise ValueError('Seleziona le foto da rianalizzare.')
                jobs.reanalyze(body.ids)
            else:
                await jobs.start('idle' if body.command == 'idle' else 'manual')
            return jobs.status()
        except (ValueError, RuntimeError, OSError) as error:
            raise HTTPException(409, str(error))

    @router.post('/api/catalog/search')
    def find(body: SearchPlan, request: Request):
        result = search(catalog, body)
        if getattr(request.state, 'device', None):
            for photo in result['photos']:
                if photo['processing']['error']:
                    photo['processing']['error'] = 'Da catalogare: consulta il motivo sul computer.'
        return result

    @router.post('/api/catalog/plan')
    async def plan(body: Natural):
        try:
            return (await natural_plan(body.query)).model_dump()
        except Exception as error:
            raise HTTPException(409, f'Ricerca naturale non disponibile: {error}')

    @router.put('/api/catalog/photos/{identifier}/tags')
    def correction(identifier: str, body: Correction, request: Request):
        computer_only(request)
        try:
            catalog.override(identifier, body.tag, body.included)
        except ValueError as error:
            raise HTTPException(400, str(error))
        return {'saved': True}

    @router.get('/api/catalog/photos/{identifier}/thumb')
    def thumb(identifier: str):
        path = catalog.path_of(identifier)
        if path is None:
            raise HTTPException(404, 'Foto non disponibile: ripeti la scansione.')
        try:
            with Image.open(path) as original:
                picture = ImageOps.exif_transpose(original).convert('RGB')
                picture.thumbnail((384, 384))
                buffer = io.BytesIO()
                picture.save(buffer, 'JPEG', quality=85)
            data = buffer.getvalue()
            return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'private,max-age=60', 'X-Regista-Sha256': hashlib.sha256(data).hexdigest()})
        except (OSError, ValueError):
            raise HTTPException(422, 'Immagine non leggibile.')

    @router.get('/api/catalog/photos/{identifier}/full')
    def original(identifier: str):
        path = catalog.path_of(identifier)
        if path is None:
            raise HTTPException(404, 'Foto non disponibile.')
        return FileResponse(path, filename=path.name, headers={'Cache-Control': 'private,no-cache', 'X-Regista-Sha256': identifier})

    @router.get('/api/catalog/photos/{identifier}/backup')
    def original_backup(identifier: str, request: Request):
        computer_only(request)
        try:
            path = catalog.archive.path(identifier)
            catalog.archive.inspect(path, identifier)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, EOFError, zlib.error):
            raise HTTPException(404, 'Backup ZIP verificato non disponibile.')
        return FileResponse(path, filename=identifier + '.zip', media_type='application/zip')

    @router.get('/phone/catalog/snapshot')
    def phone_snapshot(request: Request):
        device = phone_only(request)
        from phone_catalog import SnapshotResponse, snapshot
        from photo_catalog import fingerprint
        path = snapshot(catalog, device)
        try:
            digest = fingerprint(path)
            return SnapshotResponse(path, media_type='application/vnd.sqlite3', filename='catalogo.sqlite',
                headers={'Cache-Control': 'private,no-store', 'X-Regista-Sha256': digest})
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @router.get('/api/catalog/duplicates')
    def duplicates():
        with catalog.connect() as db:
            rows = db.execute('''SELECT asset_id,count(*) copies FROM file_locations WHERE present=1
                GROUP BY asset_id HAVING count(*)>1 ORDER BY copies DESC LIMIT 120''').fetchall()
            return {'groups': [{'id': row['asset_id'], 'copies': row['copies']} for row in rows], 'method': 'sha256'}

    @router.post('/phone/catalog/missing')
    def missing(body: Manifest, request: Request):
        device = phone_only(request)
        if body.protocol != PROTOCOL:
            raise HTTPException(426, 'Aggiorna Regista su telefono e PC.')
        if read_only:
            raise HTTPException(409, 'Importazione disabilitata: cartella in sola lettura.')
        jobs.pause()  # Import first, annotation only after another explicit Start.
        wanted = []
        for photo in body.photos:
            from photo_import import RestoreBackupError, restore_backup
            path = catalog.verified_path_of(photo.sha256)
            present, reason = False, ''
            restore_failed = False
            try:
                if path is not None:
                    catalog.archive.ensure(path, photo.sha256, photo.name, verify=True)
                    present = True
                else:
                    present = restore_backup(catalog, photo.sha256, import_dir, photo.name) is not None
            except RestoreBackupError as error:
                restore_failed = True
                reason = str(error)[:1000]
            except (OSError, ValueError) as error:
                reason = f'Originale o backup non disponibile: {error}'[:1000]
            with catalog.connect() as db:
                db.execute('''INSERT INTO phone_import_items(device,media,stamp,sha256,name,state,error) VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(device,media) DO UPDATE SET stamp=excluded.stamp,sha256=excluded.sha256,
                    name=excluded.name,state=excluded.state,error=excluded.error''',
                           (device, photo.media, photo.stamp, photo.sha256, Path(photo.name).name,
                            'received' if present else 'error' if restore_failed else 'wanted', reason))
            if restore_failed:
                raise HTTPException(409, reason)
            if not present:
                wanted.append(photo.media)
            else:
                with catalog.connect() as db:
                    db.execute('INSERT INTO import_receipts VALUES (?,?,?,?) ON CONFLICT(device,media) DO UPDATE SET stamp=excluded.stamp,asset_id=excluded.asset_id',
                               (device, photo.media, photo.stamp, photo.sha256))
        return {'protocol': PROTOCOL, 'wanted': wanted, 'tagging': 'paused'}

    @router.put('/phone/catalog/import')
    async def upload(request: Request, media: str = Query(min_length=1, max_length=100), stamp: str = Query(max_length=100), name: str = Query(default='', max_length=300)):
        device = phone_only(request)
        if read_only:
            raise HTTPException(409, 'Importazione disabilitata: cartella in sola lettura.')
        sha = request.headers.get('x-regista-sha256', '').lower()
        if not re.fullmatch('[a-f0-9]{64}', sha):
            raise HTTPException(400, 'Serve SHA-256 della foto originale.')
        jobs.pause()
        staging = catalog.database.parent / 'catalog-staging'
        staging.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(suffix='.part', dir=staging)
        partial = Path(temporary)
        digest, size = hashlib.sha256(), 0
        try:
            with os.fdopen(descriptor, 'wb') as target:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, 'Immagine troppo grande (massimo 400 MB).')
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if not size or digest.hexdigest() != sha:
                raise HTTPException(400, 'SHA-256 non corrisponde: copia rifiutata.')
            try:
                from photo_import import image_extension
                image_extension(partial, name)
            except (OSError, ValueError, KeyError, Image.DecompressionBombError):
                raise HTTPException(422, 'Formato immagine non supportato o file corrotto.')

            def commit():
                from photo_import import keep
                result = keep(catalog, partial, import_dir, name)
                with catalog.connect() as db:
                    db.execute('INSERT INTO import_receipts VALUES (?,?,?,?) ON CONFLICT(device,media) DO UPDATE SET stamp=excluded.stamp,asset_id=excluded.asset_id',
                               (device, media, stamp, result['id']))
                    db.execute("UPDATE phone_import_items SET state='received',error='' WHERE sha256=?", (result['id'],))
                    db.execute('''INSERT INTO import_receipts(device,media,stamp,asset_id)
                        SELECT device,media,stamp,sha256 FROM phone_import_items WHERE sha256=?
                        ON CONFLICT(device,media) DO UPDATE SET stamp=excluded.stamp,asset_id=excluded.asset_id''', (result['id'],))
                return result
            try:
                return await asyncio.to_thread(commit)
            except (ValueError, OSError) as error:
                with catalog.connect() as db:
                    db.execute("UPDATE phone_import_items SET state='error',error=? WHERE device=? AND media=?",
                               (str(error)[:1000], device, media))
                raise HTTPException(409, str(error))
        finally:
            partial.unlink(missing_ok=True)

    from media_backup import routes as media_routes
    router.include_router(media_routes(catalog, jobs, read_only=read_only))
    return router
