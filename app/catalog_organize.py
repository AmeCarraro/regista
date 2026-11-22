"""Reviewed bulk tags, virtual albums and visibility. Original media and ZIP bytes never change."""
from datetime import date
import json
import time
from typing import Literal
import uuid

from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field

import llm
from photo_annotator import MODEL
from photo_catalog import normalized
from photo_search import SearchPlan,search


class BulkEdit(BaseModel):
    ids:list[str]=Field(default_factory=list,max_length=50000)
    plan:SearchPlan|None=None
    select_all:bool=False
    tags:str=Field(default='',max_length=4000)
    album:str=Field(default='',max_length=120)
    hidden:bool|None=None


class ApplyPreview(BaseModel):
    preview_id:str=Field(pattern=r'^[a-f0-9]{32}$')


class AlbumVisibility(BaseModel):
    hidden:bool


class Command(BaseModel):
    text:str=Field(min_length=1,max_length=4000)


class BulkCommand(BaseModel):
    model_config=ConfigDict(extra='forbid')
    search:SearchPlan
    tags:list[str]=Field(max_length=30)
    album:str=Field(default='',max_length=120)
    hidden:bool|None=None


def split_tags(text):
    values=list(dict.fromkeys(normalized(item) for item in text.split(',') if item.strip()))
    if len(values)>30 or any(len(item)>100 for item in values):
        raise ValueError('Usa al massimo 30 tag di 100 caratteri, separati da virgole.')
    return values


class CatalogOrganization:
    def __init__(self,catalog):
        self.catalog=catalog

    def albums(self):
        with self.catalog.connect() as db:
            rows=[dict(row) for row in db.execute('''SELECT c.*,count(ci.asset_id) count FROM collections c
                LEFT JOIN collection_items ci ON ci.collection_id=c.id GROUP BY c.id ORDER BY c.name_key''')]
        return {'albums':rows}

    def select(self,body):
        if body.select_all:
            if body.plan is None:
                raise ValueError('Scegli prima i filtri della selezione.')
            ids=[]
            offset=0
            while True:
                result=search(self.catalog,body.plan.model_copy(update={'offset':offset,'limit':120}))
                ids.extend(item['id'] for item in result['photos'])
                if offset+120>=result['total']:
                    break
                offset+=120
                if offset>=50000:
                    raise ValueError('Selezione oltre 50.000 elementi: restringi le date o i filtri.')
            return list(dict.fromkeys(ids))
        ids=list(dict.fromkeys(body.ids))
        with self.catalog.connect() as db:
            if any(not db.execute('SELECT 1 FROM assets WHERE id=?',(asset,)).fetchone() for asset in ids):
                raise ValueError('La selezione contiene elementi non presenti nel catalogo.')
        return ids

    def preview(self,body):
        tags=split_tags(body.tags)
        album=body.album.strip()
        if not tags and not album and body.hidden is None:
            raise ValueError('Indica almeno un tag, un album o un cambiamento di visibilità.')
        ids=self.select(body)
        if not ids:
            raise ValueError('Nessun elemento nella selezione.')
        payload={'ids':ids,'tags':tags,'album':album,'hidden':body.hidden}
        token=uuid.uuid4().hex
        with self.catalog.connect() as db:
            db.execute('DELETE FROM bulk_previews WHERE created<?',(time.time()-3600,))
            db.execute('INSERT INTO bulk_previews VALUES (?,?,?)',(token,time.time(),json.dumps(payload,ensure_ascii=False)))
        return {'preview_id':token,'count':len(ids),'tags':tags,'album':album,'hidden':body.hidden,'sample_ids':ids[:12]}

    def apply(self,token):
        with self.catalog.connect() as db:
            row=db.execute('SELECT * FROM bulk_previews WHERE id=?',(token,)).fetchone()
            if row is None or row['created']<time.time()-3600:
                raise ValueError('Anteprima scaduta o già applicata. Ricontrolla la selezione.')
            payload=json.loads(row['payload'])
            album_id=None
            if payload['album']:
                album_id=uuid.uuid4().hex
                db.execute('INSERT INTO collections VALUES (?,?,?,0,?) ON CONFLICT(name_key) DO NOTHING',
                    (album_id,payload['album'],normalized(payload['album']),time.time()))
                album_id=db.execute('SELECT id FROM collections WHERE name_key=?',(normalized(payload['album']),)).fetchone()[0]
            changed=0
            for asset in payload['ids']:
                if not db.execute('SELECT 1 FROM assets WHERE id=?',(asset,)).fetchone():
                    continue
                for tag in payload['tags']:
                    db.execute("INSERT INTO overrides VALUES (?,?,1,'user') ON CONFLICT(asset_id,tag) DO UPDATE SET included=1,source='user'",(asset,tag))
                if album_id:
                    db.execute('INSERT OR IGNORE INTO collection_items VALUES (?,?)',(album_id,asset))
                if payload['hidden'] is True:
                    db.execute('INSERT OR IGNORE INTO hidden_media VALUES (?)',(asset,))
                elif payload['hidden'] is False:
                    db.execute('DELETE FROM hidden_media WHERE asset_id=?',(asset,))
                self.catalog.refresh_text(db,asset)
                changed+=1
            db.execute('DELETE FROM bulk_previews WHERE id=?',(token,))
        return {'updated':changed,'album_id':album_id}

    def hide_album(self,identifier,hidden):
        with self.catalog.connect() as db:
            if not db.execute('SELECT 1 FROM collections WHERE id=?',(identifier,)).fetchone():
                raise ValueError('Album non disponibile.')
            db.execute('UPDATE collections SET hidden=? WHERE id=?',(int(hidden),identifier))
        return self.albums()

    async def propose(self,text):
        response=await llm.structured(MODEL,[
            {'role':'system','content':'Prepara una proposta di organizzazione di foto e video, senza eseguire azioni. '
             'Usa search per selezionare gli elementi esistenti e tags per i tag esplicitamente richiesti, separati: '
             'non usare i nuovi tag come termini di ricerca se servono solo come destinazione. '
             'Le date sono estremi ISO inclusivi; rispetta foto/video e usa kind all quando sono entrambi. '
             'album è una cartella virtuale opzionale richiesta dall’utente, mai un percorso filesystem. '
             'hidden è null se non è richiesto un cambiamento di visibilità. Non inventare luoghi o date. '
             'Non eliminare file. Oggi: '+date.today().isoformat()},
            {'role':'user','content':text}],BulkCommand.model_json_schema(),max_tokens=1600)
        if not response.get('done') or response.get('done_reason')=='length':
            raise ValueError('Proposta Qwen incompleta. Usa i filtri e i tag manuali.')
        proposal=BulkCommand.model_validate_json(response.get('message',{}).get('content',''))
        return self.preview(BulkEdit(plan=proposal.search,select_all=True,tags=', '.join(proposal.tags),album=proposal.album,hidden=proposal.hidden))


def routes(catalog,read_only=False):
    router=APIRouter()
    organizer=CatalogOrganization(catalog)
    def local(request):
        if getattr(request.state,'device',None):
            raise HTTPException(403,'Le modifiche del catalogo si fanno dal PC.')
        if read_only:
            raise HTTPException(409,'Catalogo in sola lettura.')
    def attempt(callback,*args):
        try:
            return callback(*args)
        except ValueError as error:
            raise HTTPException(400,str(error)) from error

    @router.get('/api/catalog/albums')
    def albums():
        return organizer.albums()

    @router.post('/api/catalog/bulk/preview')
    def preview(request:Request,body:BulkEdit):
        local(request)
        return attempt(organizer.preview,body)

    @router.post('/api/catalog/bulk/apply')
    def apply(request:Request,body:ApplyPreview):
        local(request)
        return attempt(organizer.apply,body.preview_id)

    @router.post('/api/catalog/albums/{album}/visibility')
    def visibility(request:Request,album:str,body:AlbumVisibility):
        local(request)
        return attempt(organizer.hide_album,album,body.hidden)

    @router.post('/api/catalog/bulk/propose')
    async def propose(request:Request,body:Command):
        local(request)
        try:
            return await organizer.propose(body.text)
        except ValueError as error:
            raise HTTPException(400,str(error)) from error

    return router
