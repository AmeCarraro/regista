"""Document originals, provenance and local full-text search; no model is needed for retrieval."""
import asyncio
from contextlib import contextmanager
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from photo_catalog import normalized, fingerprint
from media_sources import source_group, source_tag

DOCUMENT_FORMATS={'.pdf','.xlsx','.xls','.docx','.doc','.csv','.txt'}
MONTHS=['gennaio','febbraio','marzo','aprile','maggio','giugno','luglio','agosto','settembre','ottobre','novembre','dicembre']


class DocumentSearch(BaseModel):
    query:str=Field(default='',max_length=1000)
    kind:str=Field(default='',max_length=10,pattern=r'^(|pdf|excel|word|xlsx|xls|docx|doc|csv|txt)$')
    since:str=''
    until:str=''
    tag:str=Field(default='',max_length=100)
    source:str=Field(default='',pattern='^(|normal|whatsapp|telegram)$')
    offset:int=Field(default=0,ge=0,le=1_000_000)
    limit:int=Field(default=40,ge=1,le=100)
    @field_validator('since','until')
    @classmethod
    def dates(cls,value):
        if value:
            from datetime import date
            date.fromisoformat(value)
        return value


class DocumentTags(BaseModel):
    tags:str=Field(max_length=4000)

class DocumentImportTarget(BaseModel):
    device:str=Field(default='',max_length=100)


class DocumentLibrary:
    def __init__(self,batches):
        self.batches=batches
        self.database=batches.catalog.database.parent/'documents.sqlite'
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS documents(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,extension TEXT NOT NULL,day TEXT NOT NULL,
                size INTEGER NOT NULL,text TEXT NOT NULL DEFAULT '',text_state TEXT NOT NULL DEFAULT 'pending',
                reason TEXT NOT NULL DEFAULT '',updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS origins(id TEXT NOT NULL,media TEXT NOT NULL,device TEXT NOT NULL,
                    name TEXT NOT NULL,folder TEXT NOT NULL,day TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(id,device,media));
                CREATE TABLE IF NOT EXISTS tags(id TEXT NOT NULL,tag TEXT NOT NULL,PRIMARY KEY(id,tag));
                CREATE VIRTUAL TABLE IF NOT EXISTS search_text USING fts5(id UNINDEXED,body,tokenize='unicode61 remove_diacritics 2');
                CREATE TABLE IF NOT EXISTS requests(device TEXT PRIMARY KEY,id TEXT NOT NULL,state TEXT NOT NULL);''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.database,timeout=30)
        db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def refresh(self,db,sha):
        row=db.execute('SELECT name,text FROM documents WHERE id=?',(sha,)).fetchone()
        aliases=db.execute('SELECT name,folder FROM origins WHERE id=?',(sha,)).fetchall()
        tags=[row[0] for row in db.execute('SELECT tag FROM tags WHERE id=?',(sha,))]
        body=' '.join([row['name'],row['text'],*tags,*[str(value) for alias in aliases for value in alias]])
        db.execute('DELETE FROM search_text WHERE id=?',(sha,))
        db.execute('INSERT INTO search_text VALUES (?,?)',(sha,body))

    def register(self,item,path,device):
        sha=item['sha256']
        extension=Path(item['name']).suffix.casefold()
        if extension not in DOCUMENT_FORMATS:
            raise ValueError('Formato documento non supportato.')
        group=source_group(item['folder'])
        with self.connect() as db:
            old=db.execute('SELECT text_state FROM documents WHERE id=?',(sha,)).fetchone()
            db.execute('''INSERT INTO documents(id,name,extension,day,size,updated) VALUES (?,?,?,?,?,?) ON CONFLICT(id)
                DO UPDATE SET updated=excluded.updated''',(sha,item['name'],extension,item['day'],item['size'],time.time()))
            db.execute('INSERT OR REPLACE INTO origins VALUES (?,?,?,?,?,?,?)',(sha,item['media'],device,item['name'],item['folder'],item['day'],group))
            tag=source_tag(group)
            if tag: db.execute('INSERT OR IGNORE INTO tags VALUES (?,?)',(sha,tag))
        if old is None or old['text_state']=='pending':
            flags={'creationflags':0x08000000} if os.name=='nt' else {}
            try:
                executable=Path(sys.executable)
                if executable.name.casefold()=='pythonw.exe' and executable.with_name('python.exe').is_file():
                    executable=executable.with_name('python.exe')
                result=subprocess.run([str(executable),str(Path(__file__).with_name('document_extract.py')),str(path),extension],
                    timeout=45,capture_output=True,**flags)
                if result.returncode: raise ValueError('Estrazione del testo non riuscita.')
                extracted=json.loads(result.stdout.decode('utf-8'))
            except Exception as error:
                extracted={'text':'','state':'error','reason':f'Testo non disponibile: {error}'}
            with self.connect() as db:
                db.execute('UPDATE documents SET text=?,text_state=?,reason=? WHERE id=?',
                    (extracted['text'][:500000],extracted['state'],extracted['reason'][:1000],sha))
        with self.connect() as db: self.refresh(db,sha)

    def path(self,sha):
        with self.connect() as db:
            row=db.execute('SELECT * FROM documents WHERE id=?',(sha,)).fetchone()
        path=self.batches.normal_path(sha)
        if row is None or path is None:
            raise HTTPException(404,'Originale non disponibile. Le informazioni restano nel catalogo.')
        return path,dict(row)

    def search(self,body):
        clauses,parameters=[],[]
        terms=re.findall(r'[^\W_]+',normalized(body.query),flags=re.UNICODE)
        if terms:
            expression=' AND '.join('"'+term.replace('"','""')+'"*' for term in terms)
            clauses.append('d.id IN (SELECT id FROM search_text WHERE search_text MATCH ?)')
            parameters.append(expression)
        if body.kind:
            kinds={'excel':['.xlsx','.xls'],'word':['.doc','.docx']}.get(body.kind,['.'+body.kind])
            clauses.append('d.extension IN ('+','.join('?' for _ in kinds)+')'); parameters+=kinds
        for key,operator in [('since','>='),('until','<=')]:
            if getattr(body,key):
                clauses.append(f'EXISTS(SELECT 1 FROM origins o WHERE o.id=d.id AND o.day{operator}?)'); parameters.append(getattr(body,key))
        if body.tag:
            clauses.append('EXISTS(SELECT 1 FROM tags t WHERE t.id=d.id AND lower(t.tag)=?)'); parameters.append(normalized(body.tag))
        if body.source:
            clauses.append('EXISTS(SELECT 1 FROM origins o WHERE o.id=d.id AND o.source=?)'); parameters.append(body.source)
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        with self.connect() as db:
            total=db.execute('SELECT count(*) FROM documents d'+where,parameters).fetchone()[0]
            files=[]
            for row in db.execute('SELECT d.id,d.name,d.extension,d.day,d.size,d.text_state,d.reason FROM documents d'+where+' ORDER BY d.day DESC,d.name LIMIT ? OFFSET ?',parameters+[body.limit,body.offset]):
                item=dict(row)
                item['tags']=[t[0] for t in db.execute('SELECT tag FROM tags WHERE id=? ORDER BY tag',(row['id'],))]
                item['origins']=[dict(o) for o in db.execute('SELECT name,folder,day,source FROM origins WHERE id=?',(row['id'],))]
                files.append(item)
        return {'files':files,'total':total,'offset':body.offset,'limit':body.limit}

    def requested(self,device):
        with self.connect() as db:
            row=db.execute("SELECT id FROM requests WHERE device=? AND state='requested'",(device,)).fetchone()
        return {'request_id':row[0] if row else ''}

    def request(self,devices):
        with self.connect() as db:
            for device in devices:
                db.execute("INSERT INTO requests VALUES (?,?,'requested') ON CONFLICT(device) DO UPDATE SET id=excluded.id,state=excluded.state",(device['id'],uuid.uuid4().hex))
        return {'devices':len(devices)}

    def chat(self,text):
        if not re.search(r'\b(pdf|excel|xlsx|xls|word|docx|document[oi]|csv|txt|bollett[ae])\b',text,re.I): return None
        if not re.search(r'\b(apri|mand\w*|invi\w*|trova\w*|cerca\w*|mostra\w*|scarica\w*|recupera\w*)\b',text,re.I): return None
        lowered=normalized(text)
        kind=next((word for word in ('pdf','excel','xlsx','xls','word','docx','csv','txt') if re.search(r'\b'+word+r'\b',lowered)),'')
        stop={'apri','aprimi','mandami','mandi','manda','inviami','invia','trovami','trova','cerca','cercami','mostra','mostrami','scarica','recupera','recuperami',
              'il','lo','la','l','i','gli','le','un','uno','una','del','dello','della','dell','delle','degli','dei','di','d','per','con','mi','documento','documenti','file','pdf','excel','xlsx','xls','word','docx','csv','txt'}
        terms=[word for word in re.findall(r'[^\W_]+',lowered) if word not in stop]
        # Month names stay textual; filenames and extracted content are searched together.
        result=self.search(DocumentSearch(query=' '.join(terms),kind=kind,limit=40))
        return {'type':'documents','description':text,**result}


def routes(library,phones=None,read_only=False):
    router=APIRouter()
    def local(request):
        if getattr(request.state,'device',None): raise HTTPException(403,'Questo comando si usa dal PC.')
        if read_only: raise HTTPException(409,'Archivio in sola lettura.')

    @router.post('/api/documents/search')
    def search(body:DocumentSearch): return library.search(body)

    @router.get('/api/documents/{sha}/file')
    def original(sha:str,download:bool=False):
        path,row=library.path(sha)
        return FileResponse(path,filename=row['name'],content_disposition_type='attachment' if download else 'inline',
            media_type=mimetypes.guess_type(row['name'])[0] or 'application/octet-stream',
            headers={'Cache-Control':'private,no-store','X-Regista-Sha256':sha})

    @router.put('/api/documents/{sha}/tags')
    def tags(request:Request,sha:str,body:DocumentTags):
        local(request)
        from catalog_organize import split_tags
        library.path(sha)
        try: values=split_tags(body.tags)
        except ValueError as error: raise HTTPException(400,str(error))
        with library.connect() as db:
            db.executemany('INSERT OR IGNORE INTO tags VALUES (?,?)',((sha,tag) for tag in values))
            library.refresh(db,sha)
        return {'saved':True}

    @router.get('/api/documents/{sha}')
    def information(sha:str):
        _,row=library.path(sha)
        return {key:row[key] for key in ('id','name','extension','day','size','text_state','reason')}

    @router.post('/api/documents/import-request')
    def request_import(request:Request,body:DocumentImportTarget):
        local(request)
        devices=phones.devices if phones else []
        if body.device:
            devices=[device for device in devices if device['id']==body.device]
            if not devices: raise HTTPException(409,'Collega prima il telefono richiesto.')
        return library.request(devices)

    @router.get('/phone/documents/import-request')
    def pending(request:Request):
        device=getattr(request.state,'device',None)
        if not device: raise HTTPException(403,'Serve un telefono collegato.')
        return library.requested(device)

    @router.post('/phone/documents/import-request/seen')
    def seen(request:Request):
        device=getattr(request.state,'device',None)
        if not device: raise HTTPException(403,'Serve un telefono collegato.')
        with library.connect() as db: db.execute("UPDATE requests SET state='seen' WHERE device=?",(device,))
        return {'seen':True}

    return router
