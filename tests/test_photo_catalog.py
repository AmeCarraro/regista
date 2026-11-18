import asyncio
import io
import json
from pathlib import Path
import shutil
import time

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image
import httpx2
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
    {'done': True, 'message': {'content': '{"description":"Nessun soggetto riconoscibile.","tags":[]}'}},
    {'done': True, 'message': {'content': '{"description":"Una foto","tags":[{"term":"x","category":"unknown"}]}'}},
    {'done': True, 'message': {'content': '{"description":"Un prato.","tags":[{"term":"cane","category":"animal"}]}'}},
    {'done': True, 'message': {'content': json.dumps({'description': 'Due gatti.', 'tags': [{'term': 'gatti', 'category': 'animal'}] * 8})}},
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
    assert [(tag['tag'], tag['category']) for tag in result['tags']] == [('divano rosa', 'object'), ('due gatti', 'attribute'), ('gatti', 'animal')]
    assert search(catalog, SearchPlan(terms=['cani']))['total'] == 0
    assert search(catalog, SearchPlan(terms=['gatti']))['total'] == 1
    assert search(catalog, SearchPlan(terms=['2 gatti']))['total'] == 1
    assert search(catalog, SearchPlan(terms=['tre gatti']))['total'] == 0
    with catalog.connect() as db:
        raw = json.loads(db.execute('SELECT result FROM annotations').fetchone()[0])
    assert raw['_rejected_tags'] == [
        {'term': ' GATTI ', 'category': 'object', 'reason': 'duplicate'},
        {'term': 'cane', 'category': 'animal', 'reason': 'not_in_description'}]


def test_empty_tags_leave_photo_for_review_with_original_backup(library, monkeypatch):
    import llm
    root, catalog, jobs, _ = library
    path = photo(root / 'unclear.png')
    original = path.read_bytes()
    catalog.scan(VERSION, stable_seconds=0)
    async def structured(*args, **kwargs):
        return {'done': True, 'message': {'content': '{"description":"Foto non chiara.","tags":[]}'}}
    async def digest(model):
        return 'test'
    monkeypatch.setattr(llm, 'structured', structured)
    monkeypatch.setattr(llm, 'model_digest', digest)
    jobs.annotator = PhotoAnnotator()
    jobs.annotator.identity = {'digest': 'test'}
    drain(jobs)
    assert path.read_bytes() == original
    assert catalog.status()['analyzed'] == 0
    assert catalog.status()['failed'] == 1
    with catalog.connect() as db:
        job = db.execute('SELECT state,attempts,error FROM jobs').fetchone()
        assert job['state'] == 'error' and job['attempts'] == 1
        assert 'Nessun tag' in job['error']
        assert db.execute('SELECT count(*) FROM original_backups').fetchone()[0] == 1


def test_annotation_preserves_ollama_timings_and_ignores_missing_or_invalid_metrics(tmp_path, monkeypatch):
    import llm
    from photo_annotator import inference_metrics
    async def structured(*args, **kwargs):
        return {'done': True, 'message': {'content': '{"description":"Un cane.","tags":[{"term":"cane","category":"animal"}]}'},
                'total_duration': 3_000_000_000, 'load_duration': 1_000_000_000,
                'prompt_eval_duration': 500_000_000, 'eval_duration': 1_500_000_000,
                'prompt_eval_count': 100, 'prompt_eval_cached_count': 20, 'eval_count': 30}
    async def digest(model):
        return 'test'
    monkeypatch.setattr(llm, 'structured', structured)
    monkeypatch.setattr(llm, 'model_digest', digest)
    annotator = PhotoAnnotator()
    annotator.identity = {'digest': 'test'}
    result = asyncio.run(annotator.annotate(photo(tmp_path / 'dog.png')))
    assert result['raw']['_ollama'] == {'total_seconds': 3, 'load_seconds': 1, 'prompt_seconds': 0.5,
        'generation_seconds': 1.5, 'prompt_tokens': 100, 'prompt_cached_tokens': 20, 'generated_tokens': 30}
    assert inference_metrics({}) == {}
    assert inference_metrics({'load_duration': -1, 'eval_duration': float('nan'), 'total_duration': float('inf'),
                              'prompt_eval_duration': True, 'eval_count': '10', 'prompt_eval_count': -1,
                              'prompt_eval_cached_count': 1.5}) == {}
    assert inference_metrics({'load_duration': 0, 'eval_count': 0}) == {'load_seconds': 0, 'generated_tokens': 0}


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
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3


def test_future_catalog_schema_is_not_downgraded(library):
    root, catalog, jobs, annotator = library
    with catalog.connect() as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError, match='recente'):
        PhotoCatalog(catalog.database)
    with catalog.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99


def test_quantities_colors_and_numeric_aliases_produce_distinct_supported_tags():
    from photo_annotator import supported_tags
    parsed = Annotation(description='Due gatti su un divano rosa accanto a 2 telecomandi.', tags=[
        {'term': 'gatti', 'category': 'animal'}, {'term': 'divano', 'category': 'object'},
        {'term': 'telecomandi', 'category': 'object'}, {'term': '2 gatti', 'category': 'attribute'},
        {'term': 'due gatti', 'category': 'attribute'}, {'term': 'cane', 'category': 'animal'}])
    tags, rejected, derived = supported_tags(parsed)
    labels = [tag['tag'] for tag in tags]
    assert {'gatti', 'due gatti', 'due telecomandi', 'divano rosa'} <= set(labels)
    assert len(labels) == len(set(labels))
    assert labels.count('due gatti') == 1 and '2 gatti' not in labels and 'cane' not in labels
    assert any(tag['source'] == 'description_quantity' and tag['evidence'] == '2 telecomandi' for tag in derived)
    assert {item['reason'] for item in rejected} == {'duplicate', 'not_in_description'}


def test_zip_backup_restores_exact_original_and_is_shared_by_identical_files(library):
    import zipfile
    root, catalog, jobs, annotator = library
    path = photo(root / 'a.png')
    content = path.read_bytes()
    shutil.copy2(path, root / 'copy.png')
    catalog.scan(VERSION, stable_seconds=0)
    sha = fingerprint(path)
    backup = catalog.archive.path(sha)
    manifest = catalog.archive.inspect(backup, sha)
    with zipfile.ZipFile(backup) as archive:
        assert archive.read(manifest['original']) == content
    assert path.read_bytes() == content
    assert len(list(catalog.archive.root.rglob('*.zip'))) == 1
    assert catalog.status()['backup']['count'] == 1
    assert annotator.calls == []


def test_imports_move_to_classified_with_a_separate_unchanged_original_zip(library):
    from photo_import import keep
    root, catalog, jobs, annotator = library
    source = photo(root.parent / 'phone.png')
    content = source.read_bytes()
    kept = keep(catalog, source, root / 'Importate', 'IMG_20250301.png')
    sha = kept['id']
    assert catalog.path_of(sha).parent.name == 'Da catalogare'
    original_zip = catalog.archive.path(sha).read_bytes()
    assert search(catalog, SearchPlan(stage='to_catalog'))['total'] == 1
    drain(jobs)
    assert catalog.path_of(sha).parent.name == 'Classificate'
    assert search(catalog, SearchPlan(stage='classified'))['total'] == 1
    assert search(catalog, SearchPlan(stage='to_catalog'))['total'] == 0
    assert catalog.archive.path(sha).read_bytes() == original_zip
    assert source.read_bytes() == content
    assert keep(catalog, source, root / 'Importate')['duplicate']
    assert len(list(root.rglob('*.png'))) == 1
    assert len(annotator.calls) == 1
    client = api(catalog, jobs, root)
    assert client.get(f'/api/catalog/photos/{sha}/backup').content == original_zip
    assert client.get(f'/api/catalog/photos/{sha}/backup', headers={'test-device': 'd1'}).status_code == 403


@pytest.mark.parametrize('error', [TimeoutError(), ValueError('Risposta Qwen troncata.'),
                                 httpx2.ConnectTimeout('connection'), httpx2.WriteTimeout('write')])
def test_failed_imports_are_set_aside_with_the_reason_and_only_retry_explicitly(library, monkeypatch, error):
    from photo_import import keep
    root, catalog, jobs, annotator = library
    source = photo(root.parent / 'phone.png')
    sha = keep(catalog, source, root / 'Importate')['id']
    original = annotator.annotate
    async def fail(path):
        raise error
    monkeypatch.setattr(annotator, 'annotate', fail)
    drain(jobs)
    found = search(catalog, SearchPlan(stage='needs_review'))
    assert found['total'] == 1
    assert found['photos'][0]['processing']['attempts'] == 1
    reason = found['photos'][0]['processing']['error']
    if isinstance(error, httpx2.ConnectTimeout):
        assert '20 secondi' in reason
    elif isinstance(error, httpx2.WriteTimeout):
        assert '60 secondi' in reason
    elif isinstance(error, TimeoutError):
        assert '300 secondi' in reason
    else:
        assert 'troncata' in reason
    assert catalog.path_of(sha).parent.name == 'Da catalogare'
    catalog.archive.inspect(catalog.archive.path(sha), sha)
    assert not asyncio.run(jobs.one())
    jobs.retry()
    monkeypatch.setattr(annotator, 'annotate', original)
    drain(jobs)
    assert catalog.path_of(sha).parent.name == 'Classificate'
    assert search(catalog, SearchPlan(stage='needs_review'))['total'] == 0


def test_unverified_backup_prevents_acknowledging_or_saving_an_import(library, monkeypatch):
    from photo_import import keep
    root, catalog, jobs, annotator = library
    source = photo(root.parent / 'phone.png')
    content = source.read_bytes()
    def invalid(*args):
        raise ValueError('Backup non verificato')
    monkeypatch.setattr(catalog.archive, 'inspect', invalid)
    with pytest.raises(ValueError, match='non verificato'):
        keep(catalog, source, root / 'Importate')
    assert source.read_bytes() == content
    assert not list(root.rglob('*.png'))
    assert not list(catalog.archive.root.rglob('*.part'))
    assert catalog.status()['backup']['count'] == 0
    assert annotator.calls == []


def test_corrupt_zip_is_retained_and_rebuilt_from_the_unchanged_original(library):
    root, catalog, jobs, annotator = library
    source = photo(root / 'a.png')
    catalog.scan(VERSION, stable_seconds=0)
    sha = fingerprint(source)
    backup = catalog.archive.path(sha)
    backup.write_bytes(b'broken archive')
    catalog.archive.ensure(source, sha, verify=True)
    catalog.archive.inspect(backup, sha)
    damaged = list(backup.parent.glob('*.corrotto-*.zip'))
    assert len(damaged) == 1 and damaged[0].read_bytes() == b'broken archive'
    assert catalog.status()['backup']['errors'] == 0


def test_classification_never_overwrites_a_different_destination_file(library):
    from photo_import import keep
    root, catalog, jobs, annotator = library
    source = photo(root.parent / 'phone.png')
    sha = keep(catalog, source, root / 'Importate')['id']
    occupied = photo(root / 'Importate' / 'Classificate' / (sha + '.png'), 'blue')
    different = occupied.read_bytes()
    drain(jobs)
    assert occupied.read_bytes() == different
    assert catalog.path_of(sha).parent.name == 'Da catalogare'
    assert search(catalog, SearchPlan(stage='needs_review'))['total'] == 1
    catalog.archive.inspect(catalog.archive.path(sha), sha)


def test_interrupted_relocation_is_recovered_by_scan_without_repeating_ai(library):
    from photo_import import keep
    root, catalog, jobs, annotator = library
    source = photo(root.parent / 'phone.png')
    sha = keep(catalog, source, root / 'Importate')['id']
    pending = catalog.path_of(sha)
    landed = pending.parent.parent / 'Classificate' / pending.name
    landed.parent.mkdir()
    pending.rename(landed)  # Crash after the rename, before the location transaction.
    catalog.scan(VERSION, stable_seconds=0)
    assert catalog.path_of(sha).parent.name == 'Da catalogare'
    drain(jobs)
    assert catalog.path_of(sha).parent.name == 'Classificate'
    assert len(annotator.calls) == 1
    assert len(list(root.rglob('*.png'))) == 1


def test_phone_manifest_persists_missing_contents_and_one_import_settles_all_identical_offers(library):
    root, catalog, jobs, annotator = library
    source = photo(root.parent / 'phone.png')
    sha = fingerprint(source)
    client = api(catalog, jobs, root)
    headers = {'test-device': 'd1', 'x-regista-sha256': sha}
    body = {'protocol': 2, 'photos': [{'media': str(i), 'stamp': 'x', 'sha256': sha, 'name': f'{i}.png'} for i in (1, 2)]}
    assert client.post('/phone/catalog/missing', json=body, headers=headers).json()['wanted'] == ['1', '2']
    state = client.get('/api/catalog/status').json()
    assert state['awaiting_transfer'] == 1 and state['incoming'][0]['copies'] == 2
    assert client.get('/api/catalog/status', headers=headers).json()['incoming'] == []
    copied = client.put('/phone/catalog/import?media=1&stamp=x&name=1.png', content=source.read_bytes(), headers=headers)
    assert copied.status_code == 200, copied.text
    assert client.get('/api/catalog/status').json()['awaiting_transfer'] == 0
    assert client.post('/phone/catalog/missing', json=body, headers=headers).json()['wanted'] == []
    with catalog.connect() as db:
        assert db.execute('SELECT count(*) FROM import_receipts').fetchone()[0] == 2
    assert len(list(root.rglob('*.png'))) == 1 and catalog.status()['backup']['count'] == 1


def test_changed_working_file_cannot_acknowledge_an_old_hash_as_a_duplicate(library):
    from photo_import import keep
    root, catalog, jobs, annotator = library
    path = photo(root / 'old.png')
    original = path.read_bytes()
    sha = fingerprint(path)
    catalog.scan(VERSION, stable_seconds=0)
    photo(path, 'blue')
    source = root.parent / 'phone.png'
    source.write_bytes(original)
    result = keep(catalog, source, root / 'Importate')
    assert not result['duplicate']
    assert fingerprint(catalog.path_of(sha)) == sha
    assert path.read_bytes() != original


def test_v2_migration_keeps_saved_results_and_an_independent_database_backup(library):
    import sqlite3
    root, catalog, jobs, annotator = library
    photo(root / 'a.png')
    catalog.scan(VERSION, stable_seconds=0)
    drain(jobs)
    with catalog.connect() as db:
        for table in ('original_backups', 'archive_errors', 'managed_imports', 'phone_import_items'):
            db.execute('DROP TABLE ' + table)
        db.execute('PRAGMA user_version=2')
    reopened = PhotoCatalog(catalog.database)
    assert reopened.status()['analyzed'] == 1
    with sqlite3.connect(catalog.database.with_name('catalog.before-v3.sqlite')) as backup:
        assert backup.execute('PRAGMA user_version').fetchone()[0] == 2
        assert backup.execute('SELECT count(*) FROM annotations').fetchone()[0] == 1
    reopened.scan(VERSION, stable_seconds=0)
    assert reopened.status()['backup']['count'] == 1
    assert len(annotator.calls) == 1


def test_historical_errors_do_not_keep_a_successfully_cataloged_photo_in_the_error_count(library):
    root, catalog, jobs, annotator = library
    photo(root / 'a.png')
    catalog.scan('old-prompt', stable_seconds=0)
    with catalog.connect() as db:
        db.execute("UPDATE jobs SET state='error',error='Errore di una vecchia versione'")
    catalog.scan(VERSION, stable_seconds=0)
    drain(jobs)
    assert catalog.status()['failed'] == 0
    assert catalog.status()['classified'] == 1
    assert catalog.status()['coverage'] == 100


def test_count_search_keeps_the_quantity_attached_to_the_correct_animal(library, monkeypatch):
    root, catalog, jobs, annotator = library
    expected = photo(root / 'two-cats.png')
    photo(root / 'one-cat-two-dogs.png', 'blue')
    original = annotator.annotate
    async def counts(path):
        answer = await original(path)
        answer['description'] = 'Due gatti sul divano.' if path.name == 'two-cats.png' else 'Un gatto accanto a due cani.'
        answer['tags'] = []
        return answer
    monkeypatch.setattr(annotator, 'annotate', counts)
    catalog.scan(VERSION, stable_seconds=0)
    drain(jobs)
    for terms in (['due', 'gatti'], ['2', 'gatti'], ['2 gatti']):
        found = search(catalog, SearchPlan(terms=terms))
        assert [item['id'] for item in found['photos']] == [fingerprint(expected)]


def test_landing_a_file_never_replaces_a_destination_created_concurrently(tmp_path, monkeypatch):
    import photo_files
    source = tmp_path / 'source'
    destination = tmp_path / 'destination'
    source.write_bytes(b'original')
    real_link = photo_files.os.link
    def raced(from_path, to_path):
        destination.write_bytes(b'another original')
        return real_link(from_path, to_path)
    monkeypatch.setattr(photo_files.os, 'link', raced)
    with pytest.raises(FileExistsError):
        photo_files.move_new(source, destination)
    assert source.read_bytes() == b'original'
    assert destination.read_bytes() == b'another original'


def test_copy_fallback_keeps_its_source_if_destination_verification_fails(tmp_path, monkeypatch):
    import errno
    import hashlib
    import photo_files
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    source.write_bytes(b'original')
    def unsupported(*args):
        raise OSError(errno.ENOTSUP, 'No links on this volume')
    monkeypatch.setattr(photo_files.os, 'link', unsupported)
    monkeypatch.setattr(photo_files, 'RENAME_REFUSES_REPLACEMENT', False)
    monkeypatch.setattr(photo_files.shutil, 'copyfileobj', lambda original, target: target.write(b'damaged'))
    with pytest.raises(ValueError, match='modificata'):
        photo_files.move_new(source, destination, hashlib.sha256(b'original').hexdigest())
    assert source.read_bytes() == b'original'


def test_relocated_content_replaces_a_stale_location_identity_without_losing_other_photos(library):
    from photo_import import keep
    root, catalog, jobs, annotator = library
    source = photo(root.parent / 'phone.png')
    asset = keep(catalog, source, root / 'Importate')['id']
    other = photo(root / 'other.png', 'blue')
    catalog.scan(VERSION, stable_seconds=0)
    with catalog.connect() as db:
        imported = db.execute('SELECT * FROM file_locations WHERE asset_id=?', (asset,)).fetchone()
        db.execute('''INSERT INTO file_locations(id,asset_id,root_id,relative,size,mtime_ns,present,metadata)
            VALUES (?,?,?,?,?,?,0,?)''', ('stale', fingerprint(other), imported['root_id'],
                                        'Importate/Classificate/' + asset + '.png', imported['size'], imported['mtime_ns'], imported['metadata']))
    drain(jobs)
    assert fingerprint(catalog.path_of(asset)) == asset
    assert catalog.path_of(asset).parent.name == 'Classificate'
    assert other.exists()


def test_relative_catalog_path_keeps_its_backup_in_the_selected_directory(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    work.mkdir()
    source = photo(tmp_path / 'original.png')
    monkeypatch.chdir(work)
    catalog = PhotoCatalog('../index/catalog.sqlite')
    sha = fingerprint(source)
    backup = catalog.archive.ensure(source, sha)
    assert backup.is_relative_to(tmp_path / 'index' / 'backup-originali')
    catalog.archive.inspect(backup, sha)


def test_read_only_catalog_can_annotate_without_relocating_previously_imported_files(library):
    from photo_import import keep
    root, catalog, jobs, annotator = library
    source = photo(root.parent / 'phone.png')
    sha = keep(catalog, source, root / 'Importate')['id']
    pending = catalog.path_of(sha)
    api(catalog, jobs, root, read_only=True)
    drain(jobs)
    catalog.scan(VERSION, stable_seconds=0)
    assert catalog.path_of(sha) == pending and pending.is_file()
    assert search(catalog, SearchPlan(stage='classified'))['total'] == 1


@pytest.mark.parametrize(('description', 'term', 'quantity'), [
    ('Un uomo tiene due pesci.', 'pesce', 'due pesci'),
    ('Due palline da golf bianche.', 'pallina da golf', 'due palline da golf'),
    ('Due cani neri nel prato.', 'cane nero', 'due cani neri'),
    ('Tre libri sul tavolo.', 'libro', 'tre libri'),
    ('Due uomini in una stanza.', 'uomo', 'due uomini'),
])
def test_inflected_subject_tags_keep_counts_from_the_actual_description(description, term, quantity):
    from photo_annotator import supported_tags
    annotation = Annotation(description=description, tags=[{'term': term, 'category': 'object'}])
    tags, rejected, evidence = supported_tags(annotation)
    assert {term, quantity} <= {tag['tag'] for tag in tags}
    assert not rejected
    assert any(item['source'] == 'description_inflection' for item in evidence)
    assert any(item['tag'] == quantity and item['source'] == 'description_quantity' for item in evidence)


@pytest.mark.parametrize('terms', [('gatto', 'gatti'), ('gatti', 'gatto')])
def test_singular_and_plural_labels_do_not_duplicate_the_same_subject(terms):
    from photo_annotator import supported_tags
    tags, rejected, _ = supported_tags(Annotation(description='Due gatti.', tags=[
        {'term': term, 'category': 'animal'} for term in terms]))
    assert len(tags) == 2  # One subject label plus its explicit quantity.
    assert sum(tag['tag'] == 'due gatti' for tag in tags) == 1
    assert len(rejected) == 1 and rejected[0]['reason'] == 'duplicate'


@pytest.mark.parametrize(('description', 'term'), [
    ('Due gatti sul prato.', 'cane'), ('Un pescatore sulla riva.', 'pesce'), ('Un pianoforte.', 'corno'),
])
def test_inflection_matching_does_not_add_different_objects_or_word_substrings(description, term):
    from photo_annotator import supported_tags
    with pytest.raises(ValueError, match='Nessun tag coerente'):
        supported_tags(Annotation(description=description, tags=[{'term': term, 'category': 'object'}]))


def test_inflected_count_tags_are_saved_and_searchable_without_another_vision_call(library, monkeypatch):
    import llm
    from photo_annotator import FILTER_VERSION
    root, catalog, jobs, _ = library
    photo(root / 'test.png')
    catalog.scan(VERSION, stable_seconds=0)
    calls = []
    async def structured(*args, **kwargs):
        calls.append(1)
        return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
            'description': 'Due palline da golf bianche.', 'tags': [{'term': 'pallina da golf', 'category': 'object'}]})}}
    async def digest(model):
        return 'test'
    monkeypatch.setattr(llm, 'structured', structured)
    monkeypatch.setattr(llm, 'model_digest', digest)
    jobs.annotator = PhotoAnnotator()
    jobs.annotator.identity = {'digest': 'test'}
    drain(jobs)
    assert search(catalog, SearchPlan(terms=['due palline da golf']))['total'] == 1
    assert search(catalog, SearchPlan(terms=['pallina da golf']))['total'] == 1
    with catalog.connect() as db:
        raw = json.loads(db.execute('SELECT result FROM annotations').fetchone()[0])
    assert raw['_tag_filter_version'] == FILTER_VERSION
    assert calls == [1]
