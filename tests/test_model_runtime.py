import asyncio
import json
from types import SimpleNamespace

import pytest
import model_runtime
import llm


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def ollama(monkeypatch):
    state = SimpleNamespace(installed=True, loaded=False, posts=[], blocked=None)

    class Response:
        def __init__(self, value): self.value = value
        def json(self): return self.value
        def raise_for_status(self): pass

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            present = state.installed if url.endswith('/tags') else state.loaded
            return Response({'models': [{'name': 'qwen-test', 'digest': 'abc'}] if present else []})
        async def post(self, url, json):
            state.posts.append(json)
            if state.blocked: await state.blocked.wait()
            state.loaded = json['keep_alive'] != 0
            return Response({})

    monkeypatch.setattr(model_runtime.httpx2, 'AsyncClient', Client)
    yield state
    llm.pin('qwen-test', False)


@pytest.mark.anyio
async def test_load_is_confirmed_pinned_and_timed(tmp_path, ollama):
    runtime = model_runtime.ModelRuntime('qwen-test', tmp_path)
    await runtime.perform('load')
    status = await runtime.status()
    assert status['loaded'] and status['phase'] == 'idle'
    assert llm.keep_alive('qwen-test') == -1
    assert json.loads(runtime.history.read_text())['seconds']['load'] >= 0
    assert ollama.posts[0]['model'] == 'qwen-test'
    assert ollama.posts[0]['options']['num_ctx'] == llm.NUM_CTX


@pytest.mark.anyio
async def test_missing_exact_tag_never_pulls_or_loads_an_alias(tmp_path, ollama):
    ollama.installed = False
    runtime = model_runtime.ModelRuntime('qwen-test', tmp_path)
    await runtime.perform('load')
    assert runtime.snapshot()['phase'] == 'error'
    assert 'non installato' in runtime.snapshot()['problem']
    assert not ollama.posts


@pytest.mark.anyio
async def test_unload_waits_for_claimed_annotation_without_cancelling_it(tmp_path, ollama):
    ollama.loaded = True
    jobs = SimpleNamespace(current='photo', mode='paused')
    runtime = model_runtime.ModelRuntime('qwen-test', tmp_path, jobs)
    task = asyncio.create_task(runtime.perform('unload'))
    await asyncio.sleep(.02)
    assert not ollama.posts
    jobs.current = ''
    await task
    assert not runtime.snapshot()['loaded']
    assert ollama.posts[0]['keep_alive'] == 0


def test_repeat_taps_do_not_queue_duplicate_or_opposite_operations(tmp_path, monkeypatch):
    runtime = model_runtime.ModelRuntime('qwen-test', tmp_path)
    submitted = []
    monkeypatch.setattr(runtime.pool, 'submit', lambda fn: submitted.append(fn))
    jobs = SimpleNamespace(current='', mode='manual')
    jobs.pause = lambda: setattr(jobs, 'mode', 'paused')
    runtime.jobs = jobs
    first = runtime.start('unload')
    assert jobs.mode == 'paused'
    second = runtime.start('load')
    assert first['started'] == second['started'] and second['command'] == 'unload'
    assert len(submitted) == 1
