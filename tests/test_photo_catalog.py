import asyncio
import io
import json
from pathlib import Path
import shutil
import time

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from catalog_routes import routes
from index_jobs import IndexJobs
from inference_scheduler import InferenceScheduler
from photo_annotator import Annotation, PhotoAnnotator, VERSION
from photo_catalog import PhotoCatalog, fingerprint
from photo_search import SearchPlan, search


def photo(path, color='red'):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (32, 24), color).save(path)
    return path


class FakeAnnotator:
    def __init__(self):
        self.calls = []

    async def verify(self):
        return {'model': 'fake', 'digest': 'fake-digest'}

    async def annotate(self, path):
        self.calls.append(path)
        with Image.open(path) as image:
            image.verify()
        return {'model': 'fake', 'digest': 'fake-digest', 'quantization': 'test',
                'prompt_version': 'test', 'schema_version': '1', 'description': 'Un cane nero su un prato.',
                'tags': [{'tag': 'cane', 'category': 'animal'}, {'tag': 'nero', 'category': 'color'}],
                'raw': {}, 'seconds': 0.01}


@pytest.fixture
def library(tmp_path):
    root = tmp_path / 'photos'
    root.mkdir()
    catalog = PhotoCatalog(tmp_path / 'index' / 'catalog.sqlite')
    catalog.add_root(root)
    annotator = FakeAnnotator()
    jobs = IndexJobs(catalog, annotator)
    return root, catalog, jobs, annotator


def drain(jobs):
    async def run():
        while await jobs.one():
            pass
    asyncio.run(run())


def test_100_contents_are_annotated_once_and_a_rescan_and_rename_do_not_call_ai(library):
    root, catalog, jobs, annotator = library
    for number in range(100):
        photo(root / f'{number}.png', (number, 5, 10))
    shutil.copy2(root / '0.png', root / 'duplicate.png')
    catalog.scan(VERSION, stable_seconds=0)
    assert catalog.status()['discovered'] == 100
    assert catalog.status()['copies'] == 101
    assert annotator.calls == []
    drain(jobs)
    assert len(annotator.calls) == 100
    assert catalog.status()['coverage'] == 100
    (root / '0.png').rename(root / 'renamed.png')
    catalog.scan(VERSION, stable_seconds=0)
    drain(jobs)
    assert len(annotator.calls) == 100
    photo(root / 'renamed.png', 'blue')
    catalog.scan(VERSION, stable_seconds=0)
    drain(jobs)
    assert len(annotator.calls) == 101
    catalog.scan('new-prompt-not-authorized', stable_seconds=0)
    assert catalog.status()['pending'] == 0


def test_search_is_saved_data_only_with_pagination_boolean_terms_and_provenance(library):
    root, catalog, jobs, annotator = library
    photo(root / 'Giappone' / '2025-03' / 'dog.png')
    catalog.scan(VERSION, stable_seconds=0)
    drain(jobs)
    assert search(catalog, SearchPlan(terms=['cani', 'nero']))['total'] == 1
    assert search(catalog, SearchPlan(terms=['gatto', 'cani'], operator='or'))['total'] == 1
    assert search(catalog, SearchPlan(terms=['cane'], exclude=['nero']))['total'] == 0
    assert search(catalog, SearchPlan(place='Giappone'))['total'] == 0
    found = search(catalog, SearchPlan(folder='Giappone', since='2025-03-01', until='2025-03-31', limit=1))
    assert found['total'] == 1
    assert found['photos'][0]['metadata']['date'] == '2025-03'
    assert found['photos'][0]['metadata']['precision'] == 'month'
    assert found['photos'][0]['metadata']['date_source'] == 'path'
    assert search(catalog, SearchPlan(offset=1))['photos'] == []
    assert search(catalog, SearchPlan(tag='prato'))['total'] == 0  # description is not a tag
    assert search(catalog, SearchPlan(terms=['" OR *']))['total'] == 0
    assert len(annotator.calls) == 1


def test_overrides_survive_reanalysis_and_database_reopen(library):
    root, catalog, jobs, annotator = library
    path = photo(root / 'a.png')
    catalog.scan(VERSION, stable_seconds=0)
    drain(jobs)
    asset = fingerprint(path)
    catalog.override(asset, 'cane', False)
    catalog.override(asset, 'gatto', True)
    jobs.reanalyze([asset])
    drain(jobs)
    reopened = PhotoCatalog(catalog.database)
    tags = search(reopened, SearchPlan())['photos'][0]['tags']
    assert {tag['tag'] for tag in tags} == {'gatto', 'nero'}
    assert search(reopened, SearchPlan(tag='cane'))['total'] == 0
    assert search(reopened, SearchPlan(terms=['cane']))['total'] == 0
    with reopened.connect() as db:
        assert db.execute('SELECT count(*) FROM annotations').fetchone()[0] == 1


def test_expired_lease_is_recovered_and_stale_worker_cannot_commit(library):
    root, catalog, jobs, annotator = library
    photo(root / 'a.png')
    catalog.scan(VERSION, stable_seconds=0)
    stale = jobs.claim()
    assert jobs.claim() is None
    with catalog.connect() as db:
        db.execute('UPDATE jobs SET lease_until=0')
    drain(jobs)
    jobs.finish(stale, {})  # stale lease rejected before reading the response
    with catalog.connect() as db:
        assert db.execute('SELECT count(*) FROM annotations').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM asset_tags').fetchone()[0] == 2


def test_corrupt_photo_has_bounded_retries_and_does_not_stop_other_jobs(library):
    root, catalog, jobs, annotator = library
    (root / 'broken.png').write_bytes(b'broken')
    photo(root / 'valid.png')
    catalog.scan(VERSION, stable_seconds=0)
    for _ in range(3):
        drain(jobs)
        with catalog.connect() as db:
            db.execute('UPDATE jobs SET next_run=0')
    assert catalog.status()['analyzed'] == 1
    assert catalog.status()['failed'] == 1
    jobs.retry()
    assert catalog.status()['failed'] == 0
    assert catalog.status()['pending'] == 1


def test_roots_block_escape_and_nested_roots_do_not_create_fake_duplicates(library):
    root, catalog, jobs, annotator = library
    root_id = catalog.roots()[0]['id']
    with pytest.raises(FileNotFoundError):
        catalog.safe_path(root_id, '../private.png')
    sub = root / 'sub'
    sub.mkdir()
    assert catalog.add_root(sub) == root_id
    assert len(catalog.roots()) == 1
    with pytest.raises(ValueError):
        catalog.add_root(root.parent)
    photo(root / '.regista' / 'trash.png')
    photo(root / 'Raccolte' / 'output.png')
    catalog.scan(VERSION, stable_seconds=0)
    assert catalog.status()['discovered'] == 0


def test_missing_files_are_marked_but_a_disconnected_root_is_not_erased(library):
    root, catalog, jobs, annotator = library
    path = photo(root / 'a.png')
    catalog.scan(VERSION, stable_seconds=0)
    root.rename(root.with_name('disconnected'))
    catalog.scan(VERSION, stable_seconds=0)
    assert catalog.status()['missing'] == 0
    root.with_name('disconnected').rename(root)
    path.unlink()
    catalog.scan(VERSION, stable_seconds=0)
    assert catalog.status()['missing'] == 1
    assert search(catalog, SearchPlan())['total'] == 0


def api(catalog, jobs, root, read_only=False):
    app = FastAPI()
    @app.middleware('http')
    async def authenticated(request: Request, call_next):
        if request.headers.get('test-device'):
            request.state.device = request.headers['test-device']
        return await call_next(request)
    app.include_router(routes(catalog, jobs, root / 'Importate', read_only=read_only))
    return TestClient(app)


def test_import_deduplicates_across_folders_keeps_annotations_paused_and_requires_hash(library):
    root, catalog, jobs, annotator = library
    data = io.BytesIO()
    Image.new('RGB', (32, 24), 'red').save(data, 'PNG')
    content = data.getvalue()
    import hashlib
    sha = hashlib.sha256(content).hexdigest()
    client = api(catalog, jobs, root)
    headers = {'test-device': 'd1', 'x-regista-sha256': sha}
    jobs.mode = 'manual'
    assert client.put('/phone/catalog/import?media=1&stamp=a', content=content, headers={'test-device': 'd1'}).status_code == 400
    uploaded = client.put('/phone/catalog/import?media=1&stamp=a', content=content, headers=headers)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()['duplicate'] is False
    assert jobs.mode == 'paused'
    assert annotator.calls == []
    duplicate = client.put('/phone/catalog/import?media=2&stamp=a', content=content, headers=headers)
    assert duplicate.json()['duplicate'] is True
    assert len(list(root.rglob('*.png'))) == 1
    catalog.scan(VERSION, stable_seconds=0)
    assert catalog.status()['copies'] == 1
    body = {'protocol': 2, 'photos': [{'media': '3', 'stamp': 'x', 'sha256': sha}]}
    assert client.post('/phone/catalog/missing', json=body, headers=headers).json()['wanted'] == []
    assert client.post('/phone/catalog/missing', json={**body, 'protocol': 1}, headers=headers).status_code == 426
    assert client.put('/phone/catalog/import?media=4&stamp=x', content=b'wrong', headers=headers).status_code == 400
    assert client.get('/api/catalog/status', headers=headers).json()['roots'][0].keys() == {'id', 'label'}
    assert client.post('/api/catalog/roots', json={'path': str(root)}, headers=headers).status_code == 403
    assert client.post('/api/catalog/control', json={'command': 'start'}, headers=headers).status_code == 403
    assert client.get(f'/api/catalog/photos/{sha}/thumb', headers=headers).status_code == 200
    assert client.get(f'/api/catalog/photos/{sha}/full', headers=headers).content == content
    assert client.get('/api/catalog/photos/not-known/full', headers=headers).status_code == 404


def test_read_only_import_is_refused_and_start_requires_exact_model(library, monkeypatch):
    root, catalog, jobs, annotator = library
    client = api(catalog, jobs, root, read_only=True)
    assert client.post('/phone/catalog/missing', json={'protocol': 2, 'photos': []}, headers={'test-device': 'd1'}).status_code == 409
    import llm
    async def installed():
        return [{'name': 'qwen3-vl:2b', 'digest': 'different', 'capabilities': ['vision']}]
    monkeypatch.setattr(llm, 'installed', installed)
    with pytest.raises(ValueError, match='Modello esatto'):
        asyncio.run(PhotoAnnotator().verify())
    assert jobs.mode == 'paused'


def test_phone_heic_original_is_preserved_even_without_decoder_and_is_not_sent_to_ai(library):
    root, catalog, jobs, annotator = library
    import hashlib
    content = b'\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic' + b'opaque image data'
    sha = hashlib.sha256(content).hexdigest()
    client = api(catalog, jobs, root)
    response = client.put('/phone/catalog/import?media=1&stamp=x&name=IMG_20250301.heic', content=content,
                          headers={'test-device': 'd1', 'x-regista-sha256': sha})
    assert response.status_code == 200, response.text
    assert catalog.path_of(sha).read_bytes() == content
    assert catalog.status()['excluded'] == 1
    assert catalog.status()['pending'] == 0
    assert annotator.calls == []
    found = search(catalog, SearchPlan())['photos'][0]
    assert found['excluded_reason']
    assert found['metadata']['date'] == '2025-03-01'
    assert found['metadata']['date_source'] == 'phone_filename'


def test_interactive_inference_precedes_waiting_background_and_cancel_releases_slot():
    async def run():
        arbiter = InferenceScheduler()
        order = []
        gate = asyncio.Event()
        async def current():
            async with arbiter.slot(background=True):
                await gate.wait()
        async def work(name, background):
            async with arbiter.slot(background):
                order.append(name)
        active = asyncio.create_task(current())
        await asyncio.sleep(0.01)
        background = asyncio.create_task(work('background', True))
        interactive = asyncio.create_task(work('interactive', False))
        await asyncio.sleep(0.01)
        gate.set()
        await asyncio.gather(active, background, interactive)
        assert order == ['interactive', 'background']
        async with arbiter.slot():
            waiting = asyncio.create_task(work('cancelled', False))
            await asyncio.sleep(0)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
        assert arbiter.interactive == 0 and not arbiter.lock.locked()
    asyncio.run(run())


@pytest.mark.parametrize('response', [
    {'done': False, 'message': {'content': '{}'}},
    {'done': True, 'done_reason': 'length', 'message': {'content': '{}'}},
    {'done': True, 'message': {'content': 'not JSON'}},
    {'done': True, 'message': {'content': '{"description":"","tags":[]}'}},
    {'done': True, 'message': {'content': '{"description":"Una foto","tags":[{"term":"x","category":"unknown"}]}'}},
    {'done': True, 'message': {'content': '{"description":"Un prato.","tags":[{"term":"cane","category":"animal"}]}'}},
])
def test_invalid_or_truncated_annotations_are_not_successes(tmp_path, monkeypatch, response):
    import llm
    async def structured(*args, **kwargs):
        return response
    monkeypatch.setattr(llm, 'structured', structured)
    async def digest(model):
        return 'test'
    monkeypatch.setattr(llm, 'model_digest', digest)
    annotator = PhotoAnnotator()
    annotator.identity = {'digest': 'test', 'quantization': 'test'}
    with pytest.raises(ValueError):
        asyncio.run(annotator.annotate(photo(tmp_path / 'test.png')))


def test_only_unique_caption_supported_tags_are_saved_and_searchable(library, monkeypatch):
    import llm
    root, catalog, jobs, _ = library
    photo(root / 'test.png')
    catalog.scan(VERSION, stable_seconds=0)
    response = {'description': 'Due gatti su un divano rosa accanto a un canestro.', 'tags': [
        {'term': 'gatti', 'category': 'animal'}, {'term': ' GATTI ', 'category': 'object'},
        {'term': 'divano rosa', 'category': 'object'}, {'term': 'cane', 'category': 'animal'}]}
    async def structured(*args, **kwargs):
        return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(response)}}
    async def digest(model):
        return 'test'
    monkeypatch.setattr(llm, 'structured', structured)
    monkeypatch.setattr(llm, 'model_digest', digest)
    jobs.annotator = PhotoAnnotator()
    jobs.annotator.identity = {'digest': 'test'}
    drain(jobs)
    result = search(catalog, SearchPlan())['photos'][0]
    assert [(tag['tag'], tag['category']) for tag in result['tags']] == [('divano rosa', 'object'), ('gatti', 'animal')]
    assert search(catalog, SearchPlan(terms=['cani']))['total'] == 0
    assert search(catalog, SearchPlan(terms=['gatti']))['total'] == 1
    with catalog.connect() as db:
        raw = json.loads(db.execute('SELECT result FROM annotations').fetchone()[0])
    assert raw['_rejected_tags'] == [
        {'term': ' GATTI ', 'category': 'object', 'reason': 'duplicate'},
        {'term': 'cane', 'category': 'animal', 'reason': 'not_in_description'}]


def test_long_annotation_renews_ownership_until_it_finishes(library, monkeypatch):
    import index_jobs
    root, catalog, jobs, annotator = library
    photo(root / 'test.png')
    catalog.scan(VERSION, stable_seconds=0)
    monkeypatch.setattr(index_jobs, 'LEASE_REFRESH_SECONDS', 0.001)

    async def run():
        started, renewed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_annotate, original_renew = annotator.annotate, jobs.renew
        async def slow(path):
            started.set()
            await release.wait()
            return await original_annotate(path)
        def renew(job):
            owned = original_renew(job)
            renewed.set()
            return owned
        monkeypatch.setattr(annotator, 'annotate', slow)
        monkeypatch.setattr(jobs, 'renew', renew)
        worker = asyncio.create_task(jobs.one())
        try:
            await asyncio.wait_for(started.wait(), 2)
            with catalog.connect() as db:
                db.execute('UPDATE jobs SET lease_until=0')
            renewed.clear()
            await asyncio.wait_for(renewed.wait(), 2)
            assert IndexJobs(catalog, annotator).claim() is None
            release.set()
            await asyncio.wait_for(worker, 2)
        finally:
            release.set()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    asyncio.run(run())
    assert catalog.status()['analyzed'] == 1
    assert len(annotator.calls) == 1


def test_cancelling_slow_annotation_stops_inference_and_releases_the_job(library, monkeypatch):
    root, catalog, jobs, annotator = library
    photo(root / 'test.png')
    catalog.scan(VERSION, stable_seconds=0)
    async def run():
        started, stopped = asyncio.Event(), asyncio.Event()
        async def slow(path):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        monkeypatch.setattr(annotator, 'annotate', slow)
        worker = asyncio.create_task(jobs.one())
        await asyncio.wait_for(started.wait(), 2)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        assert stopped.is_set()
    asyncio.run(run())
    assert catalog.status()['pending'] == 1
    assert catalog.status()['running'] == 0


def test_version_one_migration_preserves_results_and_keeps_a_sqlite_backup(library):
    root, catalog, jobs, annotator = library
    photo(root / 'a.png')
    catalog.scan(VERSION, stable_seconds=0)
    drain(jobs)
    with catalog.connect() as db:
        db.execute('ALTER TABLE assets DROP COLUMN excluded_reason')
        db.execute('PRAGMA user_version=1')
    reopened = PhotoCatalog(catalog.database)
    assert reopened.status()['analyzed'] == 1
    assert reopened.status()['pending'] == 0
    assert catalog.database.with_name('catalog.before-v2.sqlite').is_file()
    with reopened.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2


def test_future_catalog_schema_is_not_downgraded(library):
    root, catalog, jobs, annotator = library
    with catalog.connect() as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError, match='recente'):
        PhotoCatalog(catalog.database)
    with catalog.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
