"""HTTP round trips with synthetic phone originals, including a hidden WhatsApp directory."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from openpyxl import Workbook
import pytest

from import_batches import routes
from photo_catalog import PhotoCatalog, fingerprint
from photo_search import search, SearchPlan
from documents import DocumentSearch


def pdf(path,text='Bolletta ottobre 2026, energia elettrica',password=''):
    writer=PdfWriter()
    page=writer.add_blank_page(width=300,height=200)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject(); stream.set_data(('BT /F1 10 Tf 15 100 Td ('+text+') Tj ET').encode('ascii'))
    page[NameObject('/Contents')]=writer._add_object(stream)
    if password: writer.encrypt(password)
    with path.open('wb') as target: writer.write(target)


@pytest.fixture
def setup(tmp_path):
    phone=tmp_path/'synthetic-phone'
    normal=phone/'DCIM/Camera'; normal.mkdir(parents=True)
    wa=phone/'Android/media/com.whatsapp/WhatsApp/Media'; (wa/'WhatsApp Images/Sent').mkdir(parents=True)
    (wa/'WhatsApp Video').mkdir(); (wa/'WhatsApp Documents').mkdir()
    (wa/'.nomedia').write_bytes(b'')
    Image.new('RGB',(16,12),'red').save(normal/'normale.png')
    Image.new('RGB',(16,12),'blue').save(wa/'WhatsApp Images/Sent/ricevuta.png')
    from video_tools import run
    assert run(['-v','error','-f','lavfi','-i','color=c=red:s=160x120:d=1','-c:v','mpeg4',str(wa/'WhatsApp Video/ricevuto.mp4')]).returncode==0
    pdf(wa/'WhatsApp Documents/bolletta-ottobre.pdf')
    book=Workbook(); book.active.title='Spese'; book.active.append(['Voce','Importo']); book.active.append(['spese ottobre',120]); book.save(wa/'WhatsApp Documents/spese.xlsx'); book.close()
    catalog=PhotoCatalog(tmp_path/'index/catalog.sqlite')
    target=tmp_path/'PC'
    target.mkdir()
    catalog.add_root(target)
    jobs=SimpleNamespace(pause=lambda:None)
    phones=SimpleNamespace(devices=[{'id':'redmi','name':'Redmi di prova'}])
    def client():
        app=FastAPI()
        @app.middleware('http')
        async def gate(request,call_next):
            if request.url.path.startswith('/phone/'):
                request.state.device=request.headers.get('X-Test-Device','redmi')
            return await call_next(request)
        app.include_router(routes(catalog,jobs,target/'Importate dal telefono',phones=phones))
        return TestClient(app),catalog.batch_imports
    http,manager=client()
    yield SimpleNamespace(phone=phone,wa=wa,normal=normal,catalog=catalog,manager=manager,http=http,restart=client,target=target)
    manager.pool.shutdown(wait=True)
    catalog.batch_imports.pool.shutdown(wait=True)


def item(source,phone,media,kind):
    return {'media':media,'stamp':'stable:'+fingerprint(source),'sha256':fingerprint(source),'name':source.name,
            'folder':source.parent.relative_to(phone).as_posix(),'kind':kind,'size':source.stat().st_size,
            'mime':'application/octet-stream','day':'2026-10-15'}


def start(http,work,total,source='normal',scope='photos-videos',document_type=''):
    response=http.post('/phone/imports/start',json={'work_id':work,'total':total,'source':source,'scope':scope,'transport':'wifi','document_type':document_type})
    assert response.status_code==200,response.text
    return response.json()['id']


def manifest(http,batch,files):
    response=http.post('/phone/imports/manifest',json={'batch_id':batch,'files':files})
    assert response.status_code==200,response.text
    return response.json()


def upload(http,batch,file,source):
    response=http.put('/phone/imports/upload',params={'batch_id':batch,'media':file['media']},headers={'X-Regista-Sha256':file['sha256']},content=source.read_bytes())
    assert response.status_code==200,response.text
    return response.json()


def test_hidden_whatsapp_round_trip_resumes_without_touching_phone_and_uses_independent_zips(setup):
    env=setup; http=env.http
    before={path:path.read_bytes() for path in env.phone.rglob('*') if path.is_file()}
    normal=env.normal/'normale.png'; normal_info=item(normal,env.phone,'image:external:1','image')
    normal_batch=start(http,'first-normal',1)
    manifest(http,normal_batch,[normal_info]); upload(http,normal_batch,normal_info,normal)
    env.manager.finalize_sync(normal_batch)
    original_zip=env.manager.zip_path(normal_batch).read_bytes()

    photo=env.wa/'WhatsApp Images/Sent/ricevuta.png'; video=env.wa/'WhatsApp Video/ricevuto.mp4'
    photo_info=item(photo,env.phone,'tree:hidden-photo','image'); video_info=item(video,env.phone,'tree:hidden-video','video')
    batch=start(http,'first-whatsapp',2,'whatsapp')
    manifest(http,batch,[photo_info,video_info]); upload(http,batch,photo_info,photo)
    assert not env.manager.zip_path(batch).exists()
    assert http.post('/phone/imports/finalize',json={'batch_id':batch}).status_code==409
    # Recreate the service around the same persisted DB and working files.
    http,manager=env.restart()
    assert start(http,'first-whatsapp',2,'whatsapp')==batch
    wanted=manifest(http,batch,[photo_info,video_info])
    assert wanted['wanted']==[video_info['media']] and wanted['confirmed'][photo_info['media']]=='copied'
    truncated=http.put('/phone/imports/upload',params={'batch_id':batch,'media':video_info['media']},
        headers={'X-Regista-Sha256':video_info['sha256']},content=video.read_bytes()[:3])
    assert truncated.status_code==409
    upload(http,batch,video_info,video); manager.finalize_sync(batch)
    destination=env.target/'Importate dal telefono/WhatsApp/Media'
    assert (destination/'WhatsApp Images/Sent/ricevuta.png').read_bytes()==photo.read_bytes()
    assert (destination/'WhatsApp Video/ricevuto.mp4').read_bytes()==video.read_bytes()
    assert search(env.catalog,SearchPlan(tag='whatsapp'))['total']==2
    with zipfile.ZipFile(manager.zip_path(batch)) as archive:
        data=json.loads(archive.read('manifest.json'))
        assert len(data['originals'])==2 and len(data['sources'])==2
        for source in data['sources']:
            assert source['folder'].startswith('Android/media/com.whatsapp/')
            assert source['day']=='2026-10-15' and len(source['sha256'])==64
        for original in data['originals']:
            assert hashlib.sha256(archive.read(original['original'])).hexdigest()==original['sha256']
    assert manager.zip_path(normal_batch).read_bytes()==original_zip
    assert all(path.read_bytes()==data for path,data in before.items())
    assert (env.wa/'.nomedia').exists()


def test_identical_media_keeps_one_content_both_origins_and_automatic_source_tag(setup):
    env=setup; http=env.http; normal=env.normal/'normale.png'
    first=item(normal,env.phone,'image:external:1','image')
    batch=start(http,'ordinary',1); manifest(http,batch,[first]); upload(http,batch,first,normal); env.manager.finalize_sync(batch)
    duplicate=env.wa/'WhatsApp Images/Sent/doppione.png'; duplicate.write_bytes(normal.read_bytes())
    second=item(duplicate,env.phone,'tree:duplicate','image')
    other=start(http,'whatsapp-same-content',1,'whatsapp')
    answer=manifest(http,other,[second]); assert answer['wanted']==[] and answer['confirmed'][second['media']]=='duplicate'
    env.manager.finalize_sync(other)
    found=search(env.catalog,SearchPlan(tag='whatsapp'))
    assert found['total']==1
    with env.manager.connect() as db:
        folders={row[0] for row in db.execute('SELECT folder FROM origins WHERE sha256=?',(first['sha256'],))}
    assert folders=={first['folder'],second['folder']}
    with env.catalog.connect() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0]==1
        for row in db.execute('SELECT metadata FROM file_locations WHERE asset_id=?',(first['sha256'],)):
            assert set(json.loads(row[0])['source_folders'])==folders


def test_pdf_excel_index_download_and_chat_work_without_a_model(setup,monkeypatch):
    env=setup; http=env.http
    files=[env.wa/'WhatsApp Documents/bolletta-ottobre.pdf',env.wa/'WhatsApp Documents/spese.xlsx']
    entries=[item(path,env.phone,'tree:document-'+str(index),'document') for index,path in enumerate(files)]
    batches=[]
    for path,entry,category in zip(files,entries,['pdf','excel']):
        batch=start(http,'whatsapp-'+category,1,'whatsapp','documents',category)
        manifest(http,batch,[entry]); upload(http,batch,entry,path); env.manager.finalize_sync(batch)
        batches.append(batch)
        assert env.manager.status(batch)['documents']==1
        label='PDF' if category=='pdf' else 'Excel'
        assert (env.target/('Importate dal telefono/Documenti/WhatsApp/'+label+'/Media/WhatsApp Documents')/path.name).read_bytes()==path.read_bytes()
    found=http.post('/api/documents/search',json={'query':'ottobre','tag':'WhatsApp'}).json()
    assert found['total']==2 and all(file['text_state']=='ready' for file in found['files'])
    assert http.post('/api/documents/search',json={'kind':'excel','query':'spese'}).json()['total']==1
    import main
    monkeypatch.setattr(main,'CATALOG_ENABLED',True); monkeypatch.setattr(main,'photo_catalog',env.catalog)
    async def forbidden(): raise AssertionError('Document lookup must work with Ollama off')
    monkeypatch.setattr(main.llm,'installed',forbidden)
    http.app.add_api_route('/api/chat',main.chat,methods=['POST'])
    for asked,expected in [('Mandami il PDF della bolletta di ottobre',files[0]),("Apri l’Excel delle spese",files[1])]:
        response=http.post('/api/chat',json={'messages':[{'role':'user','content':asked}]})
        events=[json.loads(line) for line in response.text.splitlines()]
        attachment=next(event for event in events if event['type']=='documents')
        assert attachment['total']==1
        identifier=attachment['files'][0]['id']
        downloaded=http.get(f'/api/documents/{identifier}/file?download=true')
        assert downloaded.content==expected.read_bytes()
        assert downloaded.headers['x-regista-sha256']==fingerprint(expected)
        assert downloaded.headers['content-disposition'].startswith('attachment;')
    assert len(set(batches))==2
    for batch,category in zip(batches,['pdf','excel']):
        with zipfile.ZipFile(env.manager.zip_path(batch)) as archive:
            manifest_data=json.loads(archive.read('manifest.json'))
            assert manifest_data['document_type']==category
            assert len(manifest_data['originals'])==1
            assert {entry['kind'] for entry in manifest_data['sources']}=={'document'}


def test_protected_and_scanned_pdfs_remain_searchable_by_name(setup):
    env=setup
    protected=env.wa/'WhatsApp Documents/contratto-protetto.pdf'; pdf(protected,password='secret')
    scanned=env.wa/'WhatsApp Documents/ricevuta-scansione.pdf'; Image.new('RGB',(20,20),'white').save(scanned,'PDF')
    files=[protected,scanned]; entries=[item(path,env.phone,'doc:'+str(index),'document') for index,path in enumerate(files)]
    batch=start(env.http,'unreadable-text',2,'whatsapp','documents','pdf'); manifest(env.http,batch,entries)
    for path,entry in zip(files,entries): upload(env.http,batch,entry,path)
    env.manager.finalize_sync(batch)
    result=env.manager.documents.search(DocumentSearch(query='protetto'))
    assert result['total']==1 and result['files'][0]['text_state']=='protected'
    result=env.manager.documents.search(DocumentSearch(query='scansione'))
    assert result['total']==1 and result['files'][0]['text_state']=='no_text'


def test_telegram_and_next_month_have_new_archives_without_mutating_previous_blocks(setup):
    env=setup
    folder=env.phone/'Android/media/org.telegram.messenger/Telegram/Telegram Documents'; folder.mkdir(parents=True)
    first=folder/'spese-novembre.txt'; first.write_text('Spese Telegram di novembre, carburante 60 euro.',encoding='utf-8')
    entry=item(first,env.phone,'tree:telegram-1','document')
    batch=start(env.http,'november-telegram',1,'telegram','documents','txt'); manifest(env.http,batch,[entry]); upload(env.http,batch,entry,first); env.manager.finalize_sync(batch)
    archived=env.manager.zip_path(batch).read_bytes()
    assert (env.target/'Importate dal telefono/Documenti/Telegram/TXT/Telegram Documents/spese-novembre.txt').read_bytes()==first.read_bytes()
    assert env.manager.documents.search(DocumentSearch(tag='Telegram',query='carburante'))['total']==1
    later=start(env.http,'december-telegram',1,'telegram','documents','txt')
    assert manifest(env.http,later,[entry])['wanted']==[]
    env.manager.finalize_sync(later)
    assert later!=batch and env.manager.zip_path(later).is_file()
    assert env.manager.zip_path(batch).read_bytes()==archived


def test_document_import_request_targets_only_the_chosen_phone(setup):
    env=setup
    assert env.http.post('/api/documents/import-request',json={'device':'not-paired'}).status_code==409
    assert env.http.post('/api/documents/import-request',json={'device':'redmi'}).json()['devices']==1
    assert env.http.get('/phone/documents/import-request').json()['request_id']
    assert not env.http.get('/phone/documents/import-request',headers={'X-Test-Device':'other-phone'}).json()['request_id']


def test_pdf_block_cannot_silently_include_excel(setup):
    env=setup
    excel=env.wa/'WhatsApp Documents/spese.xlsx'
    entry=item(excel,env.phone,'doc:wrong-category','document')
    batch=start(env.http,'pdf-only',1,'whatsapp','documents','pdf')
    response=env.http.post('/phone/imports/manifest',json={'batch_id':batch,'files':[entry]})
    assert response.status_code==400
    assert env.manager.status(batch)['listed']==0
    assert not env.manager.zip_path(batch).exists()
