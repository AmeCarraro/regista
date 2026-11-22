"""Archive-scoped phone cleanup proposals. Nothing here deletes PC originals or archives."""
import asyncio
import json
import sqlite3
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from photo_catalog import fingerprint
from import_batches import BATCH, IDENTITY


class CleanupTarget(BaseModel):
    device: str = Field(min_length=1,max_length=100)


class Candidate(BaseModel):
    media: str = Field(min_length=1,max_length=300)
    stamp: str = Field(min_length=1,max_length=1000)
    sha256: str = Field(pattern=IDENTITY)
    name: str = Field(max_length=500)
    folder: str = Field(default='',max_length=2000)
    kind: str = Field(pattern='^(image|video)$')


class Matched(BaseModel):
    job_id: str = Field(pattern=BATCH)
    files: list[Candidate] = Field(max_length=50000)


class ConfirmCleanup(BaseModel):
    yes: bool


class CleanupChunk(BaseModel):
    job_id: str = Field(pattern=BATCH)
    media: list[str] = Field(max_length=2000)


class CleanupResult(CleanupChunk):
    cancelled: bool = False
    error: str = Field(default='',max_length=1000)
    done: bool = False


class ArchiveCleanup:
    def __init__(self,batches):
        self.batches=batches
        with batches.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS cleanup_jobs(
                id TEXT PRIMARY KEY,batch_id TEXT NOT NULL,device TEXT NOT NULL,state TEXT NOT NULL,
                created REAL NOT NULL,updated REAL NOT NULL,allowed TEXT NOT NULL DEFAULT '[]',
                matched TEXT NOT NULL DEFAULT '[]',removed TEXT NOT NULL DEFAULT '[]',error TEXT NOT NULL DEFAULT '')''')

    def job(self,identifier,device=None):
        with self.batches.connect() as db:
            row=db.execute('SELECT * FROM cleanup_jobs WHERE id=?',(identifier,)).fetchone()
        if row is None or (device is not None and row['device']!=device):
            raise HTTPException(404,'Richiesta di pulizia non disponibile per questo telefono.')
        return dict(row)

    def status(self,identifier):
        row=self.job(identifier)
        matches=json.loads(row['matched'])
        removed=json.loads(row['removed'])
        return {key:row[key] for key in ('id','batch_id','device','state','created','updated','error')} | {
            'count':len(matches),'images':sum(item['kind']=='image' for item in matches),
            'videos':sum(item['kind']=='video' for item in matches),'removed':len(removed),
            'files':matches,'pc_copies_verified':row['state'] not in ('verifying','error')}

    def verify_copies(self,batch,selected=None):
        value=self.batches.run(batch)
        if value['state']!='ready':
            raise HTTPException(409,'Prima completa l’importazione e la creazione dello ZIP.')
        archive=self.batches.zip_path(batch)
        if fingerprint(archive)!=value['zip_sha']:
            raise HTTPException(409,'Lo ZIP è cambiato o non è verificabile. Nessuna eliminazione autorizzata.')
        manifest=self.batches.verify_zip(archive)
        allowed={item['sha256'] for item in manifest['sources'] if item['kind'] in ('image','video')}
        if selected is not None and not set(selected)<=allowed:
            raise HTTPException(409,'Un file non appartiene a questo ZIP.')
        for sha in allowed if selected is None else set(selected):
            if self.batches.normal_path(sha) is None:
                raise HTTPException(409,'Manca la copia normale verificata di un file. Nessuna eliminazione autorizzata.')
        return allowed

    def prepare(self,batch,device):
        self.batches.run(batch)
        identifier=uuid.uuid4().hex
        now=time.time()
        with self.batches.connect() as db:
            active=db.execute("SELECT id FROM cleanup_jobs WHERE device=? AND state IN ('verifying','finding','matched','approved')",(device,)).fetchone()
            if active:
                raise HTTPException(409,'Concludi o annulla prima l’altra richiesta di pulizia per questo telefono.')
            db.execute('INSERT INTO cleanup_jobs(id,batch_id,device,state,created,updated) VALUES (?,?,?,?,?,?)',
                       (identifier,batch,device,'verifying',now,now))
        self.batches.pool.submit(self.prepare_sync,identifier)
        return self.status(identifier)

    def prepare_sync(self,identifier):
        value=self.job(identifier)
        try:
            allowed=self.verify_copies(value['batch_id'])
            with self.batches.connect() as db:
                db.execute("UPDATE cleanup_jobs SET state='finding',allowed=?,updated=? WHERE id=? AND state='verifying'",
                           (json.dumps(sorted(allowed)),time.time(),identifier))
        except Exception as error:
            with self.batches.connect() as db:
                db.execute("UPDATE cleanup_jobs SET state='error',error=?,updated=? WHERE id=?",(str(error)[:1000],time.time(),identifier))

    def pending(self,device):
        with self.batches.connect() as db:
            row=db.execute("SELECT * FROM cleanup_jobs WHERE device=? AND state IN ('finding','matched','approved') ORDER BY created LIMIT 1",(device,)).fetchone()
        if row is None:
            return {'job':None}
        result={'id':row['id'],'batch_id':row['batch_id'],'state':row['state']}
        if row['state']=='finding':
            result['allowed']=json.loads(row['allowed'])
        if row['state']=='approved':
            removed=set(json.loads(row['removed']))
            result['files']=[item for item in json.loads(row['matched']) if item['media'] not in removed]
        return {'job':result}

    def matched(self,device,body):
        value=self.job(body.job_id,device)
        if value['state']!='finding':
            raise HTTPException(409,'La selezione della richiesta è già chiusa.')
        allowed=set(json.loads(value['allowed']))
        if len({item.media for item in body.files})!=len(body.files) or any(item.sha256 not in allowed for item in body.files):
            raise HTTPException(409,'Il telefono ha proposto file estranei allo ZIP.')
        with self.batches.connect() as db:
            db.execute("UPDATE cleanup_jobs SET state='matched',matched=?,updated=? WHERE id=? AND state='finding'",
                (json.dumps([item.model_dump() for item in body.files],ensure_ascii=False),time.time(),body.job_id))
        return self.status(body.job_id)

    def confirm(self,identifier,yes):
        value=self.job(identifier)
        if not yes:
            with self.batches.connect() as db:
                db.execute("UPDATE cleanup_jobs SET state='cancelled',updated=? WHERE id=?",(time.time(),identifier))
            return self.status(identifier)
        if value['state']!='matched':
            raise HTTPException(409,'Attendi prima il riepilogo dei file trovati sul telefono.')
        selected={item['sha256'] for item in json.loads(value['matched'])}
        if not selected:
            raise HTTPException(409,'Nessun file corrispondente trovato sul telefono.')
        self.verify_copies(value['batch_id'],selected)
        with self.batches.connect() as db:
            db.execute("UPDATE cleanup_jobs SET state='approved',updated=? WHERE id=? AND state='matched'",(time.time(),identifier))
        return self.status(identifier)

    def authorize(self,device,body):
        value=self.job(body.job_id,device)
        if value['state']!='approved':
            raise HTTPException(409,'Manca la conferma esplicita sul PC.')
        selected={item['media']:item for item in json.loads(value['matched'])}
        already=set(json.loads(value['removed']))
        if not body.media or len(body.media)!=len(set(body.media)) or any(media not in selected or media in already for media in body.media):
            raise HTTPException(409,'Selezione diversa da quella confermata.')
        self.verify_copies(value['batch_id'],{selected[media]['sha256'] for media in body.media})
        return {'authorized':True,'files':[selected[media] for media in body.media], 'requires_android_confirmation':True}

    def result(self,device,body):
        value=self.job(body.job_id,device)
        if value['state']!='approved':
            raise HTTPException(409,'Richiesta non approvata.')
        selected={item['media'] for item in json.loads(value['matched'])}
        if not set(body.media)<=selected:
            raise HTTPException(409,'Risultato estraneo alla selezione confermata.')
        removed=set(json.loads(value['removed']))|set(body.media)
        state='cancelled' if body.cancelled else 'finished' if body.done else 'approved'
        with self.batches.connect() as db:
            db.execute('UPDATE cleanup_jobs SET state=?,removed=?,error=?,updated=? WHERE id=?',
                       (state,json.dumps(sorted(removed)),body.error,time.time(),body.job_id))
        return self.status(body.job_id)

    def revoke(self,device):
        with self.batches.connect() as db:
            db.execute("UPDATE cleanup_jobs SET state='cancelled',updated=? WHERE device=? AND state NOT IN ('finished','cancelled')",(time.time(),device))


def routes(batches,phones=None):
    router=APIRouter()
    cleanup=ArchiveCleanup(batches)
    batches.cleanup=cleanup
    def local(request):
        if getattr(request.state,'device',None):
            raise HTTPException(403,'La conferma si dà dal PC.')
    def phone(request):
        device=getattr(request.state,'device',None)
        if not device:
            raise HTTPException(403,'Serve un telefono collegato.')
        return device

    @router.post('/api/imports/{batch}/cleanup')
    def prepare(request:Request,batch:str,body:CleanupTarget):
        local(request)
        if phones is None or not any(item['id']==body.device for item in phones.devices):
            raise HTTPException(409,'Collega il telefono da cui vuoi rimuovere i file.')
        return cleanup.prepare(batch,body.device)

    @router.get('/api/import-cleanup/{job}')
    def status(request:Request,job:str):
        local(request)
        return cleanup.status(job)

    @router.post('/api/import-cleanup/{job}/confirm')
    async def confirm(request:Request,job:str,body:ConfirmCleanup):
        local(request)
        return await asyncio.to_thread(cleanup.confirm,job,body.yes)

    @router.get('/phone/import-cleanup')
    def pending(request:Request):
        return cleanup.pending(phone(request))

    @router.post('/phone/import-cleanup/matched')
    def matched(request:Request,body:Matched):
        return cleanup.matched(phone(request),body)

    @router.post('/phone/import-cleanup/authorize')
    async def authorize(request:Request,body:CleanupChunk):
        return await asyncio.to_thread(cleanup.authorize,phone(request),body)

    @router.post('/phone/import-cleanup/result')
    def result(request:Request,body:CleanupResult):
        return cleanup.result(phone(request),body)

    return router
