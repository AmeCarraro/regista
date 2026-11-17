"""The model put in memory before it is asked anything, and kept there for a while (llm.ready, llm.KEEP_ALIVE)."""
import asyncio
import json

import llm
import pytest


@pytest.mark.parametrize(('value', 'seconds'), [(None, 300), ('0', None), ('7200', 7200)])
def test_local_inference_allows_long_responses_or_an_unlimited_wait(monkeypatch, value, seconds):
    if value is None:
        monkeypatch.delenv('REGISTA_INFERENCE_TIMEOUT', raising=False)
    else:
        monkeypatch.setenv('REGISTA_INFERENCE_TIMEOUT', value)
    timeout = llm.inference_timeout()
    assert timeout.read == seconds
    assert timeout.connect == 20


@pytest.mark.parametrize('value', ['-1', 'nan', 'inf', 'invalid'])
def test_invalid_inference_timeouts_are_rejected(monkeypatch, value):
    monkeypatch.setenv('REGISTA_INFERENCE_TIMEOUT', value)
    with pytest.raises(ValueError):
        llm.inference_timeout()


def test_structured_request_uses_the_response_timeout_and_visual_sampling(monkeypatch):
    monkeypatch.setenv('REGISTA_INFERENCE_TIMEOUT', '0')
    captured = {}
    def handle(request):
        captured['timeout'] = request.extensions['timeout']
        captured['payload'] = json.loads(request.content)
        return llm.httpx2.Response(200, json={'done': True, 'message': {'content': '{}'}})
    real_client = llm.httpx2.AsyncClient
    monkeypatch.setattr(llm.httpx2, 'AsyncClient', lambda **kwargs: real_client(transport=llm.httpx2.MockTransport(handle), **kwargs))
    result = asyncio.run(llm.structured('test', [], {'type': 'object'}, max_tokens=4096,
                                       options={'temperature': 0.7, 'presence_penalty': 1.5}))
    assert result['done']
    assert captured['timeout']['read'] is None
    assert captured['payload']['options'] == {'temperature': 0.7, 'presence_penalty': 1.5,
                                               'num_ctx': llm.NUM_CTX, 'num_predict': 4096}


def test_structured_response_deadline_cancels_slow_inference(monkeypatch):
    monkeypatch.setenv('REGISTA_INFERENCE_TIMEOUT', '0.01')
    stopped = []
    async def handle(request):
        try:
            await asyncio.sleep(1)
        finally:
            stopped.append(True)
        return llm.httpx2.Response(200, json={'done': True})
    real_client = llm.httpx2.AsyncClient
    monkeypatch.setattr(llm.httpx2, 'AsyncClient', lambda **kwargs: real_client(transport=llm.httpx2.MockTransport(handle), **kwargs))
    with pytest.raises(TimeoutError):
        asyncio.run(llm.structured('test', [], {'type': 'object'}))
    assert stopped == [True]


def test_waiting_for_the_gpu_does_not_consume_the_model_response_deadline(monkeypatch):
    monkeypatch.setenv('REGISTA_INFERENCE_TIMEOUT', '0.05')
    real_client = llm.httpx2.AsyncClient
    transport = llm.httpx2.MockTransport(lambda request: llm.httpx2.Response(200, json={'done': True}))
    monkeypatch.setattr(llm.httpx2, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    async def run():
        async with llm.scheduler.slot():
            request = asyncio.create_task(llm.structured('test', [], {'type': 'object'}, background=True))
            await asyncio.sleep(0.1)
        assert (await request)['done']
    asyncio.run(run())


class Answer:
    def __init__(self, body):
        self.status_code, self.body, self.text = 200, body, ""

    def json(self):
        return self.body


class Ollama:
    """Ollama as llm sees it: how much of the model is in video memory now, None when it is not loaded,
    and how much will be there when it is loaded again."""

    def __init__(self, now, again):
        self.now, self.again, self.asked = now, again, []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *problem):
        return False

    async def get(self, url):
        running = [] if self.now is None else [{"name": "qwen3.5:4b", "model": "qwen3.5:4b", "size": 100, "size_vram": round(self.now * 100)}]
        return Answer({"models": running})

    said = "Yes."

    async def post(self, url, json):
        self.asked.append(json)
        if url.endswith("/api/generate"):
            self.now = None if json.get("keep_alive") == 0 else self.again
            return Answer({})
        return Answer({"message": {"content": self.said}})


def test_a_model_not_in_memory_is_loaded_with_the_context_every_call_uses(monkeypatch):
    ollama = Ollama(now=None, again=0.48)
    monkeypatch.setattr(llm.httpx2, "AsyncClient", ollama)

    assert asyncio.run(llm.ready("qwen3.5:4b", 0.48)) == 0.48
    assert ollama.asked == [{"model": "qwen3.5:4b", "keep_alive": "30m", "options": {"num_ctx": llm.NUM_CTX}}]


def test_an_existing_allocation_is_never_unloaded_even_when_gpu_share_is_lower(monkeypatch):
    ollama = Ollama(now=0.37, again=0.48)
    monkeypatch.setattr(llm.httpx2, "AsyncClient", ollama)

    assert asyncio.run(llm.ready("qwen3.5:4b", 0.48)) == 0.37
    assert ollama.asked == []


def test_a_model_already_in_memory_as_it_should_be_is_left_alone(monkeypatch):
    for share, measured in ((0.46, 0.48), (0.37, None)):
        ollama = Ollama(now=share, again=0.48)
        monkeypatch.setattr(llm.httpx2, "AsyncClient", ollama)

        assert asyncio.run(llm.ready("qwen3.5:4b", measured)) == share
        assert ollama.asked == []


def test_every_question_keeps_the_model_in_memory_for_a_while(monkeypatch):
    ollama = Ollama(now=0.48, again=0.48)
    monkeypatch.setattr(llm.httpx2, "AsyncClient", ollama)

    assert asyncio.run(llm.sees("qwen3.5:4b", b"a picture", "Does this photo show a dog? Answer only yes or no.")) is True
    assert ollama.asked[0]["keep_alive"] == "30m" and ollama.asked[0]["options"]["num_ctx"] == llm.NUM_CTX


def test_a_few_pictures_are_asked_about_together_and_each_answer_is_read_by_its_number(monkeypatch):
    ollama = Ollama(now=0.48, again=0.48)
    ollama.said = "1: Yes\n2: no\n3: sì"
    monkeypatch.setattr(llm.httpx2, "AsyncClient", ollama)

    # the fourth is not in the answer: it does not count as showing it
    assert asyncio.run(llm.sees_many("qwen3.5:4b", [b"a", b"b", b"c", b"d"], "a dog")) == [True, False, True, False]
    asked = ollama.asked[0]
    assert len(asked["messages"][0]["images"]) == 4 and "does it show a dog?" in asked["messages"][0]["content"]
    assert asked["keep_alive"] == "30m" and asked["options"]["num_ctx"] == llm.NUM_CTX
    # one picture alone is asked the question of one
    ollama.asked.clear()
    ollama.said = "yes"
    assert asyncio.run(llm.sees_many("qwen3.5:4b", [b"a"], "un cane", english=False)) == [True]
    assert ollama.asked[0]["messages"][0]["content"] == "Questa foto mostra: un cane? Rispondi solo sì o no."


def test_the_model_that_looks_is_shown_smaller_pictures():
    import io

    from PIL import Image

    from photos import EYES, for_the_eyes

    big = io.BytesIO()
    Image.new("RGB", (1280, 960), (200, 30, 30)).save(big, "JPEG")
    assert max(Image.open(io.BytesIO(for_the_eyes(big.getvalue()))).size) == EYES
    small = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(small, "JPEG")
    assert for_the_eyes(small.getvalue()) == small.getvalue()
    assert for_the_eyes(b"not a picture") == b"not a picture"


def test_before_a_request_the_model_is_checked_at_most_every_ten_minutes(monkeypatch):
    import orchestrator

    checked = []

    async def ready(model, share):
        checked.append((model, share))
        return share

    monkeypatch.setattr(llm, "ready", ready)
    monkeypatch.setattr(orchestrator, "_checked", 0.0)
    tests = {"qwen3.5:4b": {"gpu_share": 0.48}}

    asyncio.run(orchestrator._ready_to_look("qwen3.5:4b", tests))
    asyncio.run(orchestrator._ready_to_look("qwen3.5:4b", tests))
    # a model never measured has nothing to be compared with: it is left as Ollama loaded it
    monkeypatch.setattr(orchestrator, "_checked", 0.0)
    asyncio.run(orchestrator._ready_to_look("granite4.1:3b", tests))

    assert checked == [("qwen3.5:4b", 0.48)]
