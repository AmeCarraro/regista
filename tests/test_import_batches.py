import hashlib
import json
from pathlib import Path
import zipfile

from fastapi import HTTPException
from PIL import Image
import pytest

from photo_catalog import PhotoCatalog
from import_batches import ImportBatches, ImportFile, ImportManifest, StartImport


@pytest.fixture
def batches(tmp_path):
    root=tmp_path/'foto'
    root.mkdir()
    catalog=PhotoCatalog(tmp_path/'index/catalog.sqlite')
    catalog.add_root(root)
    value=ImportBatches(catalog,root/'Importate dal telefono')
    yield value
    value.pool.shutdown(wait=True)


def sample(tmp_path,name='vacanza.png',kind='image',media='image:external:1',folder='DCIM/Camera'):
    path=tmp_path/name
    if kind=='image':
        Image.new('RGB',(12,9),'red').save(path)
    else:
        path.write_bytes(b'video-originale-di-prova')
    return path,ImportFile(media=media,stamp='versione:1',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        name=name,folder=folder,kind=kind,size=path.stat().st_size,mime=f'{kind}/test',day='2026-04-18')


def begin(batches,total=1,work='manual-1'):
    return batches.start('phone-1',StartImport(work_id=work,total=total))['id']


def send(batches,batch,path,item):
    batches.manifest('phone-1',ImportManifest(batch_id=batch,files=[item]))
    return batches.receive('phone-1',batch,item.media,path,item.sha256)


def test_no_zip_is_created_until_the_entire_selected_block_is_received(batches,tmp_path):
    path,item=sample(tmp_path)
    original=path.read_bytes()
    batch=begin(batches,total=2)
    send(batches,batch,path,item)
    assert batches.normal_path(item.sha256).read_bytes()==original
    assert not batches.zip_path(batch).exists()
    with pytest.raises(HTTPException,match='409'):
        batches.finalize(batch,'phone-1')
    assert batches.status(batch)['confirmed']==1


def test_retry_retains_work_and_does_not_request_confirmed_file_again(batches,tmp_path):
    path,item=sample(tmp_path)
    batch=begin(batches)
    send(batches,batch,path,item)
    assert begin(batches)==batch
    result=batches.manifest('phone-1',ImportManifest(batch_id=batch,files=[item]))
    assert result=={'wanted':[],'confirmed':{item.media:'copied'}}
    assert batches.status(batch)['copied']==1


def test_photos_and_videos_share_one_verified_immutable_zip_with_origins(batches,tmp_path):
    photo,p=sample(tmp_path)
    video,v=sample(tmp_path,'viaggio.mp4','video','video:external:1','Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video')
    originals={p.sha256:photo.read_bytes(),v.sha256:video.read_bytes()}
    batch=begin(batches,total=2)
    send(batches,batch,photo,p)
    send(batches,batch,video,v)
    result=batches.finalize_sync(batch)
    assert result['zip_ready'] and result['images']==1 and result['videos']==1
    archive=batches.zip_path(batch)
    immutable=archive.read_bytes()
    manifest=batches.verify_zip(archive)
    assert {row['folder'] for row in manifest['sources']}=={p.folder,v.folder}
    with zipfile.ZipFile(archive) as opened:
        for entry in manifest['originals']:
            assert opened.read(entry['original'])==originals[entry['sha256']]
    for sha,content in originals.items():
        assert batches.normal_path(sha).read_bytes()==content
        assert batches.catalog.archive.path(sha)==archive
        batches.catalog.archive.inspect(archive,sha)
    batches.catalog.override(p.sha256,'Skopje',True)
    batches.finalize_sync(batch)
    assert archive.read_bytes()==immutable
    assert batches.catalog.status()['backup']['archives']==1
    with batches.catalog.connect() as db:
        notes=[json.loads(row[0]) for row in db.execute('SELECT metadata FROM file_locations')]
    assert {row['media_kind'] for row in notes}=={'image','video'}
    assert {row['source_folder'] for row in notes}=={p.folder,v.folder}


def test_a_truncated_or_changed_source_is_not_confirmed(batches,tmp_path):
    path,item=sample(tmp_path)
    batch=begin(batches)
    batches.manifest('phone-1',ImportManifest(batch_id=batch,files=[item]))
    path.write_bytes(b'interrotto')
    with pytest.raises(HTTPException):
        batches.receive('phone-1',batch,item.media,path,item.sha256)
    assert batches.status(batch)['confirmed']==0
    assert not batches.zip_path(batch).exists()


def test_another_phone_cannot_take_over_or_finish_a_batch(batches,tmp_path):
    batch=begin(batches)
    with pytest.raises(HTTPException):
        batches.status(batch,'other-phone')
    with pytest.raises(HTTPException):
        batches.finalize(batch,'other-phone')


def test_corrupt_completed_zip_is_never_silently_replaced(batches,tmp_path):
    path,item=sample(tmp_path)
    batch=begin(batches)
    send(batches,batch,path,item)
    batches.finalize_sync(batch)
    archive=batches.zip_path(batch)
    archive.write_bytes(b'archivio-modificato-esternamente')
    with pytest.raises(zipfile.BadZipFile):
        batches.finalize_sync(batch)
    assert archive.read_bytes()==b'archivio-modificato-esternamente'
    with pytest.raises(ValueError,match='immutabile'):
        batches.catalog.archive.ensure(batches.normal_path(item.sha256),item.sha256,verify=True)


def test_duplicate_sources_keep_both_folders_and_one_original(batches,tmp_path):
    path,one=sample(tmp_path)
    two=one.model_copy(update={'media':'image:external:2','folder':'Pictures/Telegram'})
    batch=begin(batches,total=2)
    batches.manifest('phone-1',ImportManifest(batch_id=batch,files=[one,two]))
    answer=batches.receive('phone-1',batch,one.media,path,one.sha256)
    assert answer['confirmed']=={one.media:'copied',two.media:'duplicate'}
    batches.finalize_sync(batch)
    manifest=batches.verify_zip(batches.zip_path(batch))
    assert len(manifest['originals'])==1 and len(manifest['sources'])==2
    assert batches.status(batch)['copied']==1 and batches.status(batch)['duplicates']==1
