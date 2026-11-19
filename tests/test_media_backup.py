from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlencode, parse_qs, urlparse
import zipfile

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from catalog_routes import routes
from media_backup import MediaBackup, MediaFile, Manifest
from photo_annotator import VERSION
from photo_catalog import PhotoCatalog, fingerprint
from test_catalog_service import service


class Jobs:
    mode = 'manual'
    def pause(self): self.mode = 'paused'


@pytest.fixture
def backup(tmp_path):
    catalog = PhotoCatalog(tmp_path / 'index' / 'catalog.sqlite')
    app = FastAPI()
    @app.middleware('http')
    async def authenticated(request: Request, call_next):
        if request.headers.get('device'):
            request.state.device = request.headers['device']
        return await call_next(request)
    jobs = Jobs()
    app.include_router(routes(catalog, jobs, tmp_path / 'imports'))
    return catalog, jobs, TestClient(app)


def entry(data, media='video:1', kind='video', name='clip.mp4', folder='Movies/Viaggio/'):
    return {'media': media, 'stamp': 'volume-generation-size', 'sha256': hashlib.sha256(data).hexdigest(),
            'name': name, 'folder': folder, 'kind': kind, 'size': len(data), 'mime': kind + '/example'}


def start(client, device='phone'):
    response = client.post('/phone/media-backup/start', json={}, headers={'device': device})
    assert response.status_code == 200
    return response.json()['run_id']


def manifest(client, run, files, device='phone'):
    return client.post('/phone/media-backup/manifest', json={'run_id': run, 'files': files}, headers={'device': device})


def upload(client, run, file, data, device='phone', sha=None):
    query = urlencode({'run_id': run, 'media': file['media'], 'stamp': file['stamp']})
    return client.put('/phone/media-backup/upload?' + query, content=data,
                      headers={'device': device, 'x-regista-sha256': sha or file['sha256']})


def test_all_media_are_preserved_byte_for_byte_in_verified_stored_zips_without_ai(backup):
    catalog, jobs, client = backup
    run = start(client)
    for index, kind in enumerate(('image', 'audio', 'video')):
        data = (kind + '-original-data').encode() * 100
        file = entry(data, media=f'{kind}:{index}', kind=kind, name='original.' + kind)
        assert manifest(client, run, [file]).json()['wanted'] == [file['media']]
        result = upload(client, run, file, data)
        assert result.status_code == 200 and result.json()['kept']
        archive = catalog.archive.path(file['sha256'])
        info = catalog.archive.inspect(archive, file['sha256'])
        with zipfile.ZipFile(archive) as stored:
            assert stored.read(info['original']) == data
            assert stored.getinfo(info['original']).compress_type == zipfile.ZIP_STORED
    with catalog.connect() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM original_backups').fetchone()[0] == 3
    assert jobs.mode == 'paused'
    done = client.post('/phone/media-backup/progress', json={'run_id': run, 'total': 3, 'scanned': 3, 'done': True}, headers={'device': 'phone'}).json()
    assert done['state'] == 'completed' and done['copied'] == 3 and done['duplicates'] == 0
    portable = list((catalog.archive.root / 'sessioni').rglob(run + '.json'))
    assert len(portable) == 1
    restored = json.loads(portable[0].read_text(encoding='utf-8'))
    assert restored['run']['state'] == 'completed'
    assert {item['kind'] for item in restored['files']} == {'image', 'audio', 'video'}
    assert all(item['state'] == 'received' for item in restored['files'])


def test_duplicates_across_folders_and_devices_only_transfer_one_unique_original(backup):
    catalog, _, client = backup
    data = b'one-original'
    first, second = entry(data), entry(data, media='video:2', name='other.mp4', folder='WhatsApp/Video/')
    run = start(client)
    assert manifest(client, run, [first, second]).json()['wanted'] == [first['media']]
    assert upload(client, run, first, data).json()['duplicate'] is False
    # Retrying an acknowledged body does not turn a durable copied receipt into a duplicate.
    assert upload(client, run, second, data).json()['duplicate'] is True
    assert upload(client, run, first, data).json()['duplicate'] is True
    status = client.get('/phone/media-backup/status', headers={'device': 'phone'}).json()
    assert (status['copied'], status['duplicates'], status['pending']) == (1, 1, 0)
    assert manifest(client, run, [first, second]).json()['wanted'] == []
    other = start(client, 'second-phone')
    assert manifest(client, other, [entry(data, media='audio:22', kind='audio')], 'second-phone').json()['wanted'] == []
    with closing(sqlite3.connect(catalog.database.parent / 'media-backup.sqlite')) as db:
        assert db.execute('SELECT folder FROM files WHERE run_id=? ORDER BY media', (run,)).fetchall() == [('Movies/Viaggio/',), ('WhatsApp/Video/',)]
    assert len(list(catalog.archive.root.rglob('*.zip'))) == 1
    journal = next((catalog.archive.root / 'sessioni').rglob(run + '.jsonl'))
    discoveries = [record for line in journal.read_text(encoding='utf-8').splitlines()
                   if (record := json.loads(line))['type'] == 'manifest']
    assert discoveries and {item['folder'] for item in discoveries[0]['files']} == {'Movies/Viaggio/', 'WhatsApp/Video/'}


def test_existing_photo_zip_is_reused_even_without_a_working_photo_file(backup, tmp_path):
    catalog, _, client = backup
    source = tmp_path / 'photo.jpg'
    Image.new('RGB', (32, 24), 'blue').save(source)
    data = source.read_bytes()
    file = entry(data, kind='image', name='photo.jpg')
    catalog.archive.ensure(source, file['sha256'], verify=True)
    source.unlink()
    run = start(client)
    assert manifest(client, run, [file]).json()['wanted'] == []
    assert client.get('/phone/media-backup/status', headers={'device': 'phone'}).json()['duplicates'] == 1


def test_corrupt_duplicate_is_requested_and_repaired_without_destroying_the_bad_zip(backup):
    catalog, _, client = backup
    data = b'original'
    file = entry(data)
    run = start(client)
    manifest(client, run, [file])
    assert upload(client, run, file, data).status_code == 200
    path = catalog.archive.path(file['sha256'])
    path.write_bytes(b'corrupt-zip')
    assert manifest(client, run, [file]).json()['wanted'] == [file['media']]
    assert upload(client, run, file, data).status_code == 200
    catalog.archive.inspect(path, file['sha256'])
    damaged = list(path.parent.glob('*.corrotto-*.zip'))
    assert len(damaged) == 1 and damaged[0].read_bytes() == b'corrupt-zip'


def test_truncated_and_wrong_hash_uploads_are_not_acknowledged_and_leave_no_partials(backup):
    catalog, _, client = backup
    data = b'original'
    file = entry(data)
    run = start(client)
    manifest(client, run, [file])
    assert upload(client, run, file, data[:-1]).status_code == 400
    assert upload(client, run, file, b'incorrec').status_code == 400
    assert not catalog.archive.path(file['sha256']).exists()
    assert not list(catalog.database.parent.glob('media-backup-*.part'))
    done = client.post('/phone/media-backup/progress', json={'run_id': run, 'total': 1, 'scanned': 1, 'done': True}, headers={'device': 'phone'}).json()
    assert done['state'] == 'incomplete' and done['failed'] == 1
    assert upload(client, run, file, data).status_code == 200


def test_header_and_manifest_sizes_hashes_and_identity_are_checked(backup):
    _, _, client = backup
    data = b'original'
    file = entry(data)
    run = start(client)
    manifest(client, run, [file])
    assert upload(client, run, file, data, sha='0' * 64).status_code == 400
    changed = {**file, 'stamp': 'changed'}
    assert upload(client, run, changed, data).status_code == 409
    assert manifest(client, run, [file, {**file, 'media': 'different', 'size': len(data) + 1}]).status_code == 400
    assert manifest(client, run, [file, file]).status_code == 400


def test_racing_uploads_publish_one_archive_and_one_copied_receipt(backup, tmp_path):
    catalog, _, _ = backup
    worker = MediaBackup(catalog)
    data = b'original-race' * 1000
    files = [MediaFile.model_validate(entry(data, media=f'video:{n}')) for n in range(2)]
    run = worker.start('phone')['run_id']
    worker.manifest('phone', Manifest(run_id=run, files=files))
    source = tmp_path / 'source'
    source.write_bytes(data)
    entries = [worker.named('phone', run, file.media, file.stamp) for file in files]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda file: worker.keep('phone', run, file, source, file['sha256']), entries))
    assert sorted(item['duplicate'] for item in responses) == [False, True]
    assert worker.status('phone', run)['copied'] == 1
    assert worker.status('phone', run)['duplicates'] == 1
    assert len(list(catalog.archive.root.rglob('*.zip'))) == 1


def test_readonly_denies_backup_mutations_and_phone_cannot_read_pc_paths(backup, tmp_path):
    catalog, _, client = backup
    assert client.post('/phone/media-backup/start', json={}).status_code == 403
    assert client.get('/api/media-backup/status', headers={'device': 'phone'}).status_code == 403
    run = start(client)
    assert manifest(client, run, [], device='other-phone').status_code == 404
    readonly = FastAPI()
    @readonly.middleware('http')
    async def authenticated(request, call_next):
        request.state.device = 'phone'
        return await call_next(request)
    readonly.include_router(routes(catalog, Jobs(), tmp_path / 'readonly', read_only=True))
    reader = TestClient(readonly)
    assert reader.post('/phone/media-backup/start', json={}).status_code == 409
    assert reader.post('/phone/media-backup/manifest', json={'run_id': run, 'files': []}).status_code == 409
    assert reader.get('/phone/media-backup/status').status_code == 200
    assert 'archive_root' not in reader.get('/phone/media-backup/status').json()


def test_pc_can_download_verified_backup_and_inspect_source_metadata(backup):
    catalog, _, client = backup
    data = b'original'
    file = entry(data, name='../../clip.mp4')
    run = start(client)
    manifest(client, run, [file])
    upload(client, run, file, data)
    status = client.get('/api/media-backup/status').json()
    assert status['archive_root'] == str(catalog.archive.root)
    assert status['runs'][0]['copied'] == 1
    restored = client.get('/api/media-backup/' + file['sha256'] + '/archive')
    assert restored.status_code == 200
    with zipfile.ZipFile(io.BytesIO(restored.content)) as archive:
        info = json.loads(archive.read('manifest.json'))
        assert info['original'] == 'original/clip.mp4'
        assert archive.read(info['original']) == data


def test_media_limit_is_separate_from_photo_limit_and_configurable(backup, monkeypatch):
    _, _, client = backup
    monkeypatch.setenv('REGISTA_MEDIA_BACKUP_MAX_BYTES', '5')
    run = start(client)
    assert manifest(client, run, [entry(b'123456')]).status_code == 413


def test_media_upload_bypasses_generic_body_cap_but_still_requires_pairing(service, monkeypatch):
    module, client = service
    secret = parse_qs(urlparse(client.post('/api/phone/invite').json()['link']).query)['s'][0]
    phone = TestClient(module.app, base_url='https://192.168.1.23:8443')
    ticket = phone.post('/phone/pair', json={'secret': secret, 'name': 'Backup Android'}).json()['ticket']
    pending = client.get('/api/phone').json()['pending'][0]['id']
    client.post(f'/api/phone/pending/{pending}', json={'yes': True})
    token = phone.post('/phone/pair/wait', json={'ticket': ticket}).json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    run = phone.post('/phone/media-backup/start', json={}, headers=headers).json()['run_id']
    data = b'large-media' * 1024
    file = entry(data)
    assert phone.post('/phone/media-backup/manifest', json={'run_id': run, 'files': [file]}, headers=headers).status_code == 200
    monkeypatch.setattr(module, 'BODY', 16)
    query = urlencode({'run_id': run, 'media': file['media'], 'stamp': file['stamp']})
    url = '/phone/media-backup/upload?' + query
    assert phone.put(url, content=data, headers={**headers, 'X-Regista-Sha256': file['sha256']}).status_code == 200
    stranger = TestClient(module.app, base_url='https://192.168.1.23:8443')
    assert stranger.put(url, content=data, headers={'X-Regista-Sha256': file['sha256']}).status_code == 401


def test_photo_import_restores_existing_backup_without_another_phone_transfer(backup):
    catalog, jobs, client = backup
    buffer = io.BytesIO()
    Image.new('RGB', (32, 24), 'green').save(buffer, 'JPEG')
    data = buffer.getvalue()
    file = entry(data, kind='image', name='2025-03-15-photo.jpg')
    run = start(client)
    manifest(client, run, [file])
    assert upload(client, run, file, data).status_code == 200
    assert catalog.status()['discovered'] == 0
    request = {'protocol': 2, 'photos': [{'media': '42', 'stamp': 'current-photo', 'sha256': file['sha256'], 'name': file['name']}]}
    response = client.post('/phone/catalog/missing', json=request, headers={'device': 'phone'})
    assert response.status_code == 200 and response.json()['wanted'] == []
    restored = catalog.verified_path_of(file['sha256'])
    assert restored is not None and restored.read_bytes() == data
    assert restored.parent.name == 'Da catalogare'
    assert catalog.status()['discovered'] == 1 and catalog.status()['analyzed'] == 0
    assert jobs.mode == 'paused'
    with catalog.connect() as db:
        assert db.execute('SELECT state FROM jobs').fetchone()[0] == 'pending'
        assert db.execute('SELECT state FROM phone_import_items WHERE media=?', ('42',)).fetchone()[0] == 'received'


def test_photo_import_requests_a_new_copy_when_the_only_backup_is_corrupt(backup):
    catalog, _, client = backup
    sha = 'a' * 64
    path = catalog.archive.path(sha)
    path.parent.mkdir(parents=True)
    path.write_bytes(b'damaged')
    request = {'protocol': 2, 'photos': [{'media': '42', 'stamp': 'photo', 'sha256': sha, 'name': 'photo.jpg'}]}
    response = client.post('/phone/catalog/missing', json=request, headers={'device': 'phone'})
    assert response.status_code == 200 and response.json()['wanted'] == ['42']
    assert catalog.status()['discovered'] == 0


def test_local_restore_failure_is_explicit_and_never_requests_duplicate_network_transfer(backup, monkeypatch):
    catalog, _, client = backup
    import photo_import
    buffer = io.BytesIO()
    Image.new('RGB', (32, 24), 'green').save(buffer, 'PNG')
    data = buffer.getvalue()
    file = entry(data, kind='image', name='photo.png')
    run = start(client)
    manifest(client, run, [file])
    upload(client, run, file, data)
    def disk_full(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(photo_import, 'keep', disk_full)
    request = {'protocol': 2, 'photos': [{'media': '42', 'stamp': 'photo', 'sha256': file['sha256'], 'name': file['name']}]}
    response = client.post('/phone/catalog/missing', json=request, headers={'device': 'phone'})
    assert response.status_code == 409 and 'Nessun nuovo trasferimento' in response.json()['detail']
    assert not list((catalog.database.parent / 'catalog-staging').glob('restore-*.part'))
    catalog.archive.inspect(catalog.archive.path(file['sha256']), file['sha256'])
    with catalog.connect() as db:
        assert db.execute('SELECT state FROM phone_import_items WHERE media=?', ('42',)).fetchone()[0] == 'error'


def test_unsupported_backed_up_bytes_are_not_silently_imported_as_a_photo(backup):
    catalog, _, client = backup
    data = b'not-a-photo'
    file = entry(data, kind='image', name='unsupported.raw')
    run = start(client)
    manifest(client, run, [file])
    upload(client, run, file, data)
    request = {'protocol': 2, 'photos': [{'media': '42', 'stamp': 'photo', 'sha256': file['sha256'], 'name': file['name']}]}
    response = client.post('/phone/catalog/missing', json=request, headers={'device': 'phone'})
    assert response.status_code == 409
    assert catalog.status()['discovered'] == 0


def test_heic_backup_is_restored_without_network_and_remains_explicitly_excluded_without_decoder(backup):
    catalog, _, client = backup
    data = b'\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic' + b'opaque image data'
    file = entry(data, kind='image', name='original.heic')
    run = start(client)
    manifest(client, run, [file])
    upload(client, run, file, data)
    request = {'protocol': 2, 'photos': [{'media': '42', 'stamp': 'photo', 'sha256': file['sha256'], 'name': file['name']}]}
    response = client.post('/phone/catalog/missing', json=request, headers={'device': 'phone'})
    assert response.status_code == 200 and response.json()['wanted'] == []
    assert catalog.verified_path_of(file['sha256']).read_bytes() == data
    assert catalog.status()['excluded'] == 1
    with catalog.connect() as db:
        assert db.execute('SELECT excluded_reason FROM assets').fetchone()[0]
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
