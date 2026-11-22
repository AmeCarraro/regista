"""Resumable media imports: verified normal copies, then one immutable ZIP per user request."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
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

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from photo_annotator import VERSION
from photo_catalog import fingerprint, FORMATS
from photo_files import move_new
from media_sources import source_group, source_parts, source_tag, document_category, document_label

IDENTITY = r'^[a-f0-9]{64}$'
BATCH = r'^[a-f0-9]{32}$'
MAX_FILE = 64 * 1024 ** 3


class StartImport(BaseModel):
    work_id: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9-]+$')
    request_id: str = Field(default='', max_length=64)
    scope: Literal['photos-videos', 'all-media', 'documents'] = 'photos-videos'
    total: int = Field(ge=0, le=1000000)
    transport: Literal['', 'usb', 'wifi', 'wired', 'local'] = ''
    source: Literal['', 'normal', 'whatsapp', 'telegram'] = ''
    document_type: Literal['', 'pdf', 'excel', 'word', 'csv', 'txt'] = ''

    @model_validator(mode='after')
    def category(self):
        if (self.scope=='documents') != bool(self.document_type):
            raise ValueError('Ogni blocco documenti deve indicare una sola sottocategoria PDF, Excel, Word, CSV o TXT.')
        return self


class ImportFile(BaseModel):
    media: str = Field(min_length=1, max_length=300)
    stamp: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(pattern=IDENTITY)
    name: str = Field(min_length=1, max_length=500)
    folder: str = Field(default='', max_length=2000)
    kind: Literal['image', 'video', 'audio', 'document']
    size: int = Field(ge=0, le=MAX_FILE)
    mime: str = Field(default='application/octet-stream', max_length=200)
    day: str = ''

    @field_validator('day')
    @classmethod
    def valid_day(cls, value):
        if value:
            date.fromisoformat(value)
        return value


class ImportManifest(BaseModel):
    batch_id: str = Field(pattern=BATCH)
    files: list[ImportFile] = Field(max_length=100)
    transport: Literal['', 'usb', 'wifi', 'wired', 'local'] = ''


class BatchRequest(BaseModel):
    batch_id: str = Field(pattern=BATCH)


def safe_name(name):
    name = Path(PureWindowsPath(name).name).name
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', name).strip(' .')[:180]
    return name or 'originale'


class ImportBatches:
    def __init__(self, catalog, import_dir, jobs=None):
        self.catalog, self.jobs = catalog, jobs
        self.database = catalog.database.parent / 'import-batches.sqlite'
        self.staging = catalog.database.parent.resolve() / 'media-staging'
        self.import_dir = Path(import_dir).resolve()
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='batch ZIP')
        self.building = set()
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS runs(
                id TEXT PRIMARY KEY,device TEXT NOT NULL,work TEXT NOT NULL,request_id TEXT NOT NULL,
                scope TEXT NOT NULL,total INTEGER NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,
                updated REAL NOT NULL,zip_sha TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',
                transport TEXT NOT NULL DEFAULT '',UNIQUE(device,work));
                CREATE TABLE IF NOT EXISTS files(
                batch_id TEXT NOT NULL,media TEXT NOT NULL,stamp TEXT NOT NULL,sha256 TEXT NOT NULL,
                name TEXT NOT NULL,folder TEXT NOT NULL,kind TEXT NOT NULL,size INTEGER NOT NULL,
                mime TEXT NOT NULL,day TEXT NOT NULL,state TEXT NOT NULL,uploaded INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(batch_id,media));
                CREATE INDEX IF NOT EXISTS import_files_sha ON files(sha256);
                CREATE TABLE IF NOT EXISTS normal_files(sha256 TEXT PRIMARY KEY,path TEXT NOT NULL,size INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS origins(sha256 TEXT NOT NULL,device TEXT NOT NULL,media TEXT NOT NULL,
                stamp TEXT NOT NULL,name TEXT NOT NULL,folder TEXT NOT NULL,kind TEXT NOT NULL,day TEXT NOT NULL,
                PRIMARY KEY(sha256,device,media,stamp));''')
            if 'source' not in {row['name'] for row in db.execute('PRAGMA table_info(runs)')}:
                db.execute("ALTER TABLE runs ADD COLUMN source TEXT NOT NULL DEFAULT ''")
            if 'document_type' not in {row['name'] for row in db.execute('PRAGMA table_info(runs)')}:
                db.execute("ALTER TABLE runs ADD COLUMN document_type TEXT NOT NULL DEFAULT ''")
        from documents import DocumentLibrary
        self.documents=DocumentLibrary(self)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def run(self, batch, device=None):
        if not re.fullmatch(BATCH, batch):
            raise HTTPException(400, 'Blocco non valido.')
        with self.connect() as db:
            value = db.execute('SELECT * FROM runs WHERE id=?', (batch,)).fetchone()
        if value is None or (device is not None and value['device'] != device):
            raise HTTPException(404, 'Importazione non disponibile per questo telefono.')
        return dict(value)

    def zip_path(self, batch):
        if not re.fullmatch(BATCH, batch):
            raise ValueError('Blocco non valido.')
        root = self.catalog.archive.root
        path = root / 'blocchi' / (batch + '.zip')
        if root.resolve() != root.absolute() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Archivio fuori dalla cartella autorizzata.')
        return path

    def normal_path(self, sha, *, verify=True):
        if not re.fullmatch(IDENTITY, sha):
            return None
        with self.connect() as db:
            known = db.execute('SELECT * FROM normal_files WHERE sha256=?', (sha,)).fetchone()
        candidates = [Path(known['path'])] if known else []
        catalog_path = self.catalog.verified_path_of(sha)
        if catalog_path and catalog_path not in candidates:
            candidates.append(catalog_path)
        for path in candidates:
            # Paths are generated here or obtained from the PC's authorized catalog roots.
            if path.is_symlink() or not path.is_file():
                continue
            authorized = path.resolve().is_relative_to(self.staging) or path.resolve().is_relative_to(self.import_dir)
            if not authorized and path != catalog_path:
                continue
            if (not known or path.stat().st_size == known['size']) and (not verify or fingerprint(path) == sha):
                return path
        return None

    def start(self, device, body):
        with self.connect() as db:
            old = db.execute('SELECT * FROM runs WHERE device=? AND work=?', (device, body.work_id)).fetchone()
            if old:
                if old['total'] != body.total or old['scope'] != body.scope or old['source'] != body.source or old['document_type'] != body.document_type:
                    raise HTTPException(409, 'La selezione del blocco è cambiata: avvia una nuova importazione.')
                if body.request_id and old['request_id']!=body.request_id:
                    db.execute('UPDATE runs SET request_id=? WHERE id=?',(body.request_id,old['id']))
                batch = old['id']
                db.execute('UPDATE runs SET transport=?,updated=? WHERE id=?',(body.transport,time.time(),batch))
            else:
                batch = uuid.uuid4().hex
                now = time.time()
                db.execute('INSERT INTO runs(id,device,work,request_id,scope,total,state,created,updated,transport,source,document_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (batch, device, body.work_id, body.request_id, body.scope, body.total, 'copying', now, now,body.transport,body.source,body.document_type))
        if self.jobs:
            self.jobs.pause()
        return self.status(batch, device)

    def manifest(self, device, body):
        run = self.run(body.batch_id, device)
        if run['state'] in ('ready', 'finalizing'):
            raise HTTPException(409, 'Il manifesto del blocco è già chiuso.')
        if len({item.media for item in body.files}) != len(body.files):
            raise HTTPException(400, 'Identificativi ripetuti nel blocco.')
        confirmed, wanted = {}, []
        with self.lock:
            checked = {item.sha256:self.normal_path(item.sha256) for item in body.files}
            with self.connect() as db:
                for item in body.files:
                    if run['scope'] == 'photos-videos' and item.kind not in ('image','video'):
                        raise HTTPException(400, 'Questo blocco contiene solo foto e video.')
                    if run['scope']=='documents' and item.kind!='document':
                        raise HTTPException(400,'Questo blocco contiene solo documenti.')
                    if run['source'] and source_group(item.folder)!=run['source']:
                        raise HTTPException(400,'La provenienza appartiene a un altro blocco di importazione.')
                    if item.kind=='document':
                        if run['scope']!='documents':
                            raise HTTPException(400,'I documenti richiedono blocchi separati per sottocategoria.')
                        from documents import DOCUMENT_FORMATS
                        if Path(item.name).suffix.casefold() not in DOCUMENT_FORMATS:
                            raise HTTPException(400,'Formato documento non supportato.')
                        if run['document_type'] and document_category(item.name)!=run['document_type']:
                            raise HTTPException(400,'Questo documento appartiene a un’altra sottocategoria ZIP.')
                    old = db.execute('SELECT * FROM files WHERE batch_id=? AND media=?', (body.batch_id,item.media)).fetchone()
                    values = item.model_dump()
                    if old and any(old[key] != values[key] for key in values):
                        raise HTTPException(409, 'Un file del blocco è cambiato; i dati precedenti restano conservati.')
                    present = checked[item.sha256] is not None
                    uploaded = int(old['uploaded']) if old else 0
                    state = 'received' if present else 'wanted'
                    db.execute('''INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(batch_id,media) DO UPDATE SET state=excluded.state''',
                        (body.batch_id,item.media,item.stamp,item.sha256,item.name,item.folder,item.kind,item.size,item.mime,item.day,state,uploaded))
                    db.execute('INSERT OR IGNORE INTO origins VALUES (?,?,?,?,?,?,?,?)',
                        (item.sha256,device,item.media,item.stamp,item.name,item.folder,item.kind,item.day))
                    if present:
                        path = checked[item.sha256]
                        if path.stat().st_size != item.size:
                            raise HTTPException(409, 'Dimensione del file incoerente con il suo SHA.')
                        db.execute('INSERT OR REPLACE INTO normal_files VALUES (?,?,?)', (item.sha256,str(path),item.size))
                        confirmed[item.media] = 'copied' if uploaded else 'duplicate'
                    else:
                        wanted.append(item.media)
                count = db.execute('SELECT count(*) FROM files WHERE batch_id=?',(body.batch_id,)).fetchone()[0]
                if count > run['total']:
                    raise HTTPException(409, 'Il manifesto supera la selezione iniziale.')
                db.execute('UPDATE runs SET updated=?,transport=? WHERE id=?',(time.time(),body.transport or run['transport'],body.batch_id))
        return {'wanted':wanted,'confirmed':confirmed}

    def receive(self, device, batch, media, source, sha):
        run = self.run(batch, device)
        if run['state'] in ('ready','finalizing'):
            raise HTTPException(409, 'Il blocco è già chiuso.')
        with self.connect() as db:
            item = db.execute('SELECT * FROM files WHERE batch_id=? AND media=?',(batch,media)).fetchone()
        if item is None or item['sha256'] != sha:
            raise HTTPException(409, 'Il file non appartiene al manifesto autorizzato.')
        if fingerprint(source) != sha or source.stat().st_size != item['size']:
            raise HTTPException(409, 'File incompleto o SHA non corrispondente; nessuna conferma.')
        with self.lock:
            existing = self.normal_path(sha)
            copied = not bool(existing)
            if not existing:
                extension = Path(safe_name(item['name'])).suffix.lower()
                if not re.fullmatch(r'\.[a-z0-9]{1,10}',extension):
                    extension = '.bin'
                existing = self.staging / sha[:2] / (sha + extension)
                if not existing.resolve().is_relative_to(self.staging):
                    raise HTTPException(400,'Destinazione non valida.')
                existing.parent.mkdir(parents=True,exist_ok=True)
                move_new(source,existing,sha)
            with self.connect() as db:
                db.execute('INSERT OR REPLACE INTO normal_files VALUES (?,?,?)',(sha,str(existing),item['size']))
                db.execute("UPDATE files SET state='received' WHERE batch_id=? AND sha256=?",(batch,sha))
                db.execute('UPDATE files SET uploaded=max(uploaded,?) WHERE batch_id=? AND media=?',(int(copied),batch,media))
                db.execute('UPDATE runs SET updated=? WHERE id=?',(time.time(),batch))
                outcomes = {row['media']:'copied' if row['uploaded'] else 'duplicate' for row in db.execute(
                    "SELECT media,uploaded FROM files WHERE batch_id=? AND sha256=? AND state='received'",(batch,sha))}
        return {'kept':True,'id':sha,'confirmed':outcomes}

    def status(self, batch=None, device=None):
        if batch is None:
            with self.connect() as db:
                ids = [row[0] for row in db.execute('SELECT id FROM runs ORDER BY created DESC LIMIT 100')]
            return {'imports':[self.status(identifier) for identifier in ids], 'protocol':2}
        run = self.run(batch,device)
        with self.connect() as db:
            counts = dict(db.execute("""SELECT count(*) listed,coalesce(sum(state='received'),0) confirmed,
                coalesce(sum(state='received' AND uploaded=1),0) copied,
                coalesce(sum(state='received' AND uploaded=0),0) duplicates,
                coalesce(sum(kind='image'),0) images,coalesce(sum(kind='video'),0) videos,
                coalesce(sum(kind='audio'),0) audio,coalesce(sum(size),0) bytes FROM files WHERE batch_id=?""",(batch,)).fetchone())
            counts['documents']=db.execute("SELECT count(*) FROM files WHERE batch_id=? AND kind='document'",(batch,)).fetchone()[0]
        return {**{key:run[key] for key in ('id','device','source','document_type','scope','total','state','created','updated','error','transport','zip_sha')},
                **counts, 'protocol':2, 'zip_ready':run['state']=='ready', 'max_file_bytes':MAX_FILE}

    def finalize(self, batch, device):
        value = self.run(batch,device)
        with self.lock:
            if value['state'] != 'ready' and batch not in self.building:
                with self.connect() as db:
                    count = db.execute("SELECT count(*) FROM files WHERE batch_id=? AND state='received'",(batch,)).fetchone()[0]
                    if count != value['total']:
                        raise HTTPException(409,'Importazione incompleta: lo ZIP verrà creato quando tutti i file saranno confermati.')
                    db.execute("UPDATE runs SET state='finalizing',error='',updated=? WHERE id=?",(time.time(),batch))
                self.building.add(batch)
                self.pool.submit(self._build_guarded,batch)
        return self.status(batch,device)

    def _build_guarded(self,batch):
        try:
            self.finalize_sync(batch)
        except BaseException as error:
            with self.connect() as db:
                db.execute("UPDATE runs SET state='error',error=?,updated=? WHERE id=?",(str(error)[:1000],time.time(),batch))
        finally:
            with self.lock:
                self.building.discard(batch)

    def finalize_sync(self,batch):
        value = self.run(batch)
        with self.connect() as db:
            files = [dict(row) for row in db.execute('SELECT * FROM files WHERE batch_id=? ORDER BY media',(batch,))]
        if len(files) != value['total'] or any(item['state']!='received' for item in files):
            raise ValueError('Il blocco non è completo.')
        originals = {}
        for item in files:
            path = self.normal_path(item['sha256'])
            if not path or path.stat().st_size != item['size']:
                raise ValueError('Una copia normale è mancante o modificata: nessuna pulizia del telefono sarà autorizzata.')
            originals.setdefault(item['sha256'],{'sha256':item['sha256'],'size':item['size'],
                'filename':safe_name(item['name']), 'original':f"original/{item['kind']}/{item['sha256']}--{safe_name(item['name'])}"})
        archive = self.zip_path(batch)
        archive.parent.mkdir(parents=True,exist_ok=True)
        if not archive.exists():
            descriptor, temporary = tempfile.mkstemp(suffix='.part',dir=archive.parent)
            os.close(descriptor)
            temporary = Path(temporary)
            try:
                with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as target:
                    target.writestr('manifest.json',json.dumps({'version':2,'batch_id':batch,'created':value['created'],'source':value['source'],'scope':value['scope'],'document_type':value['document_type'],
                        'originals':list(originals.values()),'sources':files},ensure_ascii=False))
                    for sha,item in originals.items():
                        target.write(self.normal_path(sha),item['original'])
                self.verify_zip(temporary,originals)
                with temporary.open('r+b') as synced:
                    os.fsync(synced.fileno())
                move_new(temporary,archive)
            finally:
                temporary.unlink(missing_ok=True)
        # Existing archives are verified and reused, never modified, appended to or replaced.
        self.verify_zip(archive,originals)
        archive_sha = fingerprint(archive)
        stamp = archive.stat()
        with self.catalog.connect() as db:
            for sha,item in originals.items():
                db.execute('INSERT INTO original_backups VALUES (?,?,?,?,?,?) ON CONFLICT(asset_id) DO NOTHING',
                    (sha,archive.relative_to(self.catalog.archive.root).as_posix(),item['size'],stamp.st_size,stamp.st_mtime_ns,time.time()))
        self.import_dir.mkdir(parents=True,exist_ok=True)
        root_id = self.catalog.add_root(self.import_dir)
        catalog_root = Path(next(root['path'] for root in self.catalog.roots(local=True) if root['id']==root_id))
        for item in files:
            sha = item['sha256']
            source = self.normal_path(sha)
            subfolder = {'image':'Da catalogare','video':'Video','audio':'Audio','document':'Documenti'}[item['kind']]
            extension = Path(safe_name(item['name'])).suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,10}',extension):
                extension='.bin'
            destination = self.import_dir / subfolder / (sha+extension)
            group=source_group(item['folder'])
            if item['kind']=='document':
                destination=self.import_dir/'Documenti'/document_label(document_category(item['name']))/(sha+'--'+safe_name(item['name']))
            if group!='normal':
                base=self.import_dir/'Documenti' if item['kind']=='document' else self.import_dir
                destination=base/source_tag(group)
                if item['kind']=='document': destination/=document_label(document_category(item['name']))
                for part in source_parts(item['folder']):
                    destination/=safe_name(part)
                destination/=safe_name(item['name'])
                if destination.exists() and fingerprint(destination)!=sha:
                    destination=destination.with_name(sha[:16]+'--'+destination.name)
            if not destination.resolve().is_relative_to(self.import_dir):
                raise ValueError('Cartella di importazione non autorizzata.')
            destination.parent.mkdir(parents=True,exist_ok=True)
            if source != destination:
                if destination.exists():
                    if fingerprint(destination)!=sha:
                        raise ValueError('Destinazione già occupata: nessuna sovrascrittura.')
                elif source.resolve().is_relative_to(self.staging):
                    move_new(source,destination,sha)
                else:
                    # A second provenance can refer to one physical original through a hard link.
                    try:
                        os.link(source,destination)
                    except OSError:
                        self.copy_verified(source,destination,sha)
            if fingerprint(destination)!=sha:
                raise ValueError('Copia normale non verificata.')
            with self.connect() as db:
                db.execute('INSERT OR REPLACE INTO normal_files VALUES (?,?,?)',(sha,str(destination),item['size']))
            if item['kind']=='document':
                self.documents.register(item,destination,value['device'])
            if item['kind'] in ('image','video') and destination.suffix.lower() in FORMATS:
                self.catalog.register(root_id,destination,VERSION)
                with self.catalog.connect() as db:
                    if item['kind']=='image' and group=='normal':
                        db.execute('INSERT OR IGNORE INTO managed_imports VALUES (?,?,?)',(sha,root_id,self.import_dir.relative_to(catalog_root).as_posix()))
                    relative=destination.relative_to(catalog_root).as_posix()
                    row=db.execute('SELECT metadata FROM file_locations WHERE root_id=? AND relative=?',(root_id,relative)).fetchone()
                    notes=json.loads(row[0])
                    notes.update(original_filename=item['name'],source_folder=item['folder'],media_kind=item['kind'],source_media=item['media'])
                    with self.connect() as origins:
                        notes['source_folders']=[row[0] for row in origins.execute('SELECT DISTINCT folder FROM origins WHERE sha256=? ORDER BY folder',(sha,))]
                    if item['day'] and (not notes.get('date') or notes.get('date_source')=='path'):
                        notes.update(date=item['day'],date_source='phone_media',precision='day')
                    db.execute('UPDATE file_locations SET metadata=? WHERE root_id=? AND relative=?',(json.dumps(notes,ensure_ascii=False),root_id,relative))
                    for other in db.execute('SELECT id,metadata FROM file_locations WHERE asset_id=?',(sha,)).fetchall():
                        other_notes=json.loads(other['metadata']); other_notes['source_folders']=notes['source_folders']
                        db.execute('UPDATE file_locations SET metadata=? WHERE id=?',(json.dumps(other_notes,ensure_ascii=False),other['id']))
                    db.execute('INSERT INTO import_receipts VALUES (?,?,?,?) ON CONFLICT(device,media) DO UPDATE SET stamp=excluded.stamp,asset_id=excluded.asset_id',
                        (value['device'],item['media'],item['stamp'],sha))
                    self.catalog.refresh_text(db,sha)
                if group!='normal':
                    self.catalog.override(sha,source_tag(group),True,source='phone_folder')
        with self.connect() as db:
            db.execute("UPDATE runs SET state='ready',zip_sha=?,error='',updated=? WHERE id=?",(archive_sha,time.time(),batch))
        return self.status(batch)

    @staticmethod
    def copy_verified(source,destination,sha):
        descriptor,temporary_name = tempfile.mkstemp(suffix='.part',dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with source.open('rb') as original,os.fdopen(descriptor,'wb') as landed:
                import shutil
                shutil.copyfileobj(original,landed)
                landed.flush(); os.fsync(landed.fileno())
            move_new(temporary,destination,sha)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def verify_zip(path, expected=None):
        with zipfile.ZipFile(path) as archive:
            if archive.getinfo('manifest.json').file_size>64*1024*1024:
                raise ValueError('Manifesto ZIP troppo grande.')
            manifest=json.loads(archive.read('manifest.json'))
            if manifest.get('version')!=2:
                raise ValueError('Formato del blocco non riconosciuto.')
            entries={entry['sha256']:entry for entry in manifest['originals']}
            if expected is not None and entries!=expected:
                raise ValueError('ZIP diverso dalla selezione del blocco.')
            if len(archive.namelist())!=len(set(archive.namelist())):
                raise ValueError('ZIP con nomi di membri ripetuti.')
            for sha,entry in entries.items():
                member=entry['original']
                if not re.fullmatch(IDENTITY,sha) or not member.startswith('original/') or '..' in Path(member).parts:
                    raise ValueError('Membro ZIP non valido.')
                if archive.getinfo(member).file_size!=entry['size']:
                    raise ValueError('Dimensione ZIP non corrispondente.')
                with archive.open(member) as source:
                    if hashlib.file_digest(source,'sha256').hexdigest()!=sha:
                        raise ValueError('SHA del contenuto ZIP non corrispondente.')
        return manifest


def routes(catalog,jobs,import_dir,read_only=False,phones=None):
    router=APIRouter()
    manager=ImportBatches(catalog,import_dir,jobs)
    catalog.batch_imports=manager

    def phone(request):
        device=getattr(request.state,'device',None)
        if not device:
            raise HTTPException(403,'Serve un telefono collegato.')
        if read_only:
            raise HTTPException(409,'Importazione disabilitata in sola lettura.')
        return device

    def local(request):
        if getattr(request.state,'device',None):
            raise HTTPException(403,'Questo comando si usa dal computer.')

    @router.post('/phone/imports/start')
    async def start(request:Request,body:StartImport):
        return await asyncio.to_thread(manager.start,phone(request),body)

    @router.post('/phone/imports/manifest')
    async def manifest(request:Request,body:ImportManifest):
        return await asyncio.to_thread(manager.manifest,phone(request),body)

    @router.put('/phone/imports/upload')
    async def upload(request:Request,batch_id:str=Query(pattern=BATCH),media:str=Query(max_length=300)):
        device=phone(request)
        manager.run(batch_id,device)
        sha=request.headers.get('x-regista-sha256','')
        if not re.fullmatch(IDENTITY,sha):
            raise HTTPException(400,'Serve SHA-256 originale.')
        with manager.connect() as db:
            expected=db.execute('SELECT sha256,size FROM files WHERE batch_id=? AND media=?',(batch_id,media)).fetchone()
        if not expected or expected['sha256']!=sha:
            raise HTTPException(409,'Il file non appartiene al manifesto autorizzato.')
        declared=request.headers.get('content-length','')
        if declared.isdigit() and int(declared)!=expected['size']:
            raise HTTPException(409,'Dimensione diversa dal manifesto.')
        manager.staging.mkdir(parents=True,exist_ok=True)
        descriptor,name=tempfile.mkstemp(suffix='.part',dir=manager.staging)
        path=Path(name)
        try:
            with os.fdopen(descriptor,'wb') as target:
                size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>expected['size']:
                        raise HTTPException(413,'Il file supera la dimensione dichiarata nel manifesto.')
                    target.write(chunk)
                target.flush(); os.fsync(target.fileno())
            return await asyncio.to_thread(manager.receive,device,batch_id,media,path,sha)
        finally:
            path.unlink(missing_ok=True)

    @router.post('/phone/imports/finalize')
    def finalize(request:Request,body:BatchRequest):
        return manager.finalize(body.batch_id,phone(request))

    @router.get('/phone/imports/status')
    def status(request:Request,batch_id:str=Query(pattern=BATCH)):
        return manager.status(batch_id,phone(request))

    @router.get('/api/imports')
    def pc_status(request:Request):
        local(request)
        return manager.status()

    @router.get('/api/imports/{batch}/zip')
    def download(request:Request,batch:str):
        local(request)
        value=manager.run(batch)
        if value['state']!='ready':
            raise HTTPException(409,'Lo ZIP del blocco non è ancora pronto.')
        from datetime import datetime
        stats=manager.status(batch)
        label=document_label(value['document_type']) if value['document_type'] else 'Audio' if stats['audio'] and not(stats['images'] or stats['videos']) else 'Foto-video'
        origin=source_tag(value['source']) or 'Telefono'
        day=datetime.fromtimestamp(value['created']).strftime('%Y-%m-%d')
        return FileResponse(manager.zip_path(batch),media_type='application/zip',filename=f'Regista-{origin}-{label}-{day}-{batch[:8]}.zip')

    @router.get('/api/imports/{batch}')
    def detail(request:Request,batch:str,offset:int=Query(default=0,ge=0)):
        local(request)
        value=manager.status(batch)
        with manager.connect() as db:
            files=[dict(row) for row in db.execute('SELECT media,name,folder,kind,day,sha256,size,state FROM files WHERE batch_id=? ORDER BY day,media LIMIT 100 OFFSET ?',(batch,offset))]
            jobs=[dict(row) for row in db.execute('SELECT id,state,device FROM cleanup_jobs WHERE batch_id=? ORDER BY created DESC LIMIT 1',(batch,))]
        return {**value,'files':files,'offset':offset,'cleanup':jobs[0] if jobs else None}

    from archive_cleanup import routes as cleanup_routes
    router.include_router(cleanup_routes(manager,phones))
    from documents import routes as document_routes
    router.include_router(document_routes(manager.documents,phones,read_only))
    return router
