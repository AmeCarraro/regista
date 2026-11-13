import importlib.util
import json
import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from PIL import Image
import pytest

import llm
from photo_annotator import MODEL, VERSION


@pytest.fixture
def service(tmp_path, monkeypatch):
    root = tmp_path / 'photos'
    root.mkdir()
    path = root / 'a.png'
    Image.new('RGB', (24, 32), 'blue').save(path)
    os.utime(path, (1_700_000_000, 1_700_000_000))
    monkeypatch.setenv('INDEX_DIR', str(tmp_path / 'index'))
    monkeypatch.setenv('PHOTOS_DIR', str(root))
    monkeypatch.setenv('REGISTA_PHOTO_CATALOG', '1')
    spec = importlib.util.spec_from_file_location('catalog_test_service', Path(__file__).parents[1] / 'app' / 'main.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    module.photos.build()
    return module, TestClient(module.app, base_url='http://127.0.0.1:8090')


def test_default_catalog_does_not_infer_until_start_and_models_never_fall_back(service, monkeypatch):
    module, client = service
    assert module.CATALOG_ENABLED
    state = client.get('/api/catalog/status').json()
    assert state['mode'] == 'paused' and state['pending'] == 1
    assert state['analyzed'] == 0
    async def installed():
        return [{'name': 'other:2b', 'bytes': 1e9, 'parameters': '2B', 'capabilities': ['vision', 'completion'], 'loaded': True, 'gpu_share': 1}]
    monkeypatch.setattr(llm, 'installed', installed)
    models = client.get('/api/models').json()
    assert models['configured_model'] == MODEL
    assert models['suggested'] is None
    assert models['order'] == {'tools': [], 'chat': [], 'vision': []}
    response = client.post('/api/catalog/control', json={'command': 'start'})
    assert response.status_code == 409
    assert module.index_jobs.mode == 'paused'
    assert client.get('/api/command-demo').status_code == 404


def test_new_phone_protocol_keeps_pairing_revocation_and_blocks_management(service):
    module, client = service
    invite = client.post('/api/phone/invite').json()
    # Use the existing pairing service contract directly; no credential bypass in Gate.
    from urllib.parse import urlparse, parse_qs
    secret = parse_qs(urlparse(invite['link']).query)['s'][0]
    phone = TestClient(module.app, base_url='https://192.168.1.23:8443')
    ticket = phone.post('/phone/pair', json={'secret': secret, 'name': 'Test Android'}).json()['ticket']
    pending = client.get('/api/phone').json()['pending'][0]['id']
    client.post(f'/api/phone/pending/{pending}', json={'yes': True})
    connected = phone.post('/phone/pair/wait', json={'ticket': ticket}).json()
    headers = {'Authorization': 'Bearer ' + connected['token']}
    assert phone.get('/phone/hello', headers=headers).json()['protocol'] == 2
    assert TestClient(module.app, base_url='https://192.168.1.23:8443').get('/api/catalog/status').status_code == 401
    assert phone.post('/api/catalog/scan', json={}, headers=headers).status_code == 403
    assert phone.get('/api/catalog/status', headers=headers).json()['computer'] is False
    for path in ('/phone/vectors', '/phone/library'):
        assert phone.post(path, json={'photos': []}, headers=headers).status_code == 426
    assert phone.get('/phone/models', headers=headers).status_code == 426
    assert client.post('/api/catalog/phone-import', json={}).json()['devices'] == 1
    requested = phone.get('/phone/catalog/import-request', headers=headers).json()['request_id']
    assert requested
    device = module.phones.devices[0]['id']
    client.post(f'/api/phone/devices/{device}/forget')
    assert phone.get('/api/catalog/status', headers=headers).status_code == 401


def test_saved_data_chat_search_has_no_image_calls(service, monkeypatch):
    module, client = service
    async def installed():
        return [{'name': MODEL, 'loaded': True}]
    async def stream(model, messages, max_tokens=700, schema=None):
        yield 'text', '{"action":"find_photos","caption":"a dog","folder":""}'
    async def structured(model, messages, schema, **options):
        assert all('images' not in message for message in messages)
        return {'done': True, 'message': {'content': '{"terms":["cane"]}'}}
    monkeypatch.setattr(llm, 'installed', installed)
    monkeypatch.setattr(llm, 'stream', stream)
    monkeypatch.setattr(llm, 'structured', structured)
    response = client.post('/api/chat', json={'messages': [{'role': 'user', 'content': 'Cerca cani'}]})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['type'] == 'done', events
    assert next(event for event in events if event['type'] == 'photos')['matching'] == 0
    assert module.photo_catalog.status()['analyzed'] == 0


def test_temporary_question_never_catalogs_without_explicit_save(service, monkeypatch):
    module, client = service
    import io
    image = io.BytesIO()
    Image.new('RGB', (48, 48), 'green').save(image, 'PNG')
    calls = []
    async def structured(model, messages, schema, **options):
        calls.append(messages)
        return {'done': True, 'message': {'content': '{"answer":"Un quadrato verde."}'}}
    monkeypatch.setattr(llm, 'structured', structured)
    response = client.post('/api/catalog/question?question=Che%20cosa%20vedi', content=image.getvalue())
    assert response.status_code == 200, response.text
    token = response.json()['attachment']
    assert not response.json()['cataloged']
    assert module.photo_catalog.status()['discovered'] == 1
    assert len(calls) == 1 and calls[0][1]['images']
    assert client.post(f'/api/catalog/attachments/{token}/save').json()['kept']
    assert module.photo_catalog.status()['discovered'] == 2
    assert module.index_jobs.mode == 'paused'
    assert module.photo_catalog.status()['analyzed'] == 0
    assert client.post('/api/catalog/attachments/not-a-token/save').status_code == 404


def test_catalog_content_ids_keep_copy_trash_journal_and_undo_working(service, monkeypatch):
    module, client = service
    monkeypatch.setattr(module, 'read_photos', module.photos.build)
    asset = module.photos.photos[0]['id']
    assert len(asset) == 64
    copied = client.post('/api/actions', json={'action': 'copy', 'ids': [asset], 'folder': 'Prova'})
    assert copied.status_code == 200, copied.text
    assert (module.photos.photos_dir / 'a.png').exists()
    assert (module.photos.photos_dir / 'Raccolte' / 'Prova' / 'a.png').exists()
    trashed = client.post('/api/actions', json={'action': 'trash', 'ids': [asset]})
    assert trashed.status_code == 200, trashed.text
    assert not (module.photos.photos_dir / 'a.png').exists()
    assert module.actions.last()['kind'] == 'trash'
    undone = client.post('/api/actions/undo', json={})
    assert undone.status_code == 200, undone.text
    assert (module.photos.photos_dir / 'a.png').exists()
    assert module.photo_catalog.status()['discovered'] == 1
