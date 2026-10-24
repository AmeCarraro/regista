"""The model put in memory before it is asked anything, and kept there for a while (llm.ready, llm.KEEP_ALIVE)."""
import asyncio

import llm


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

    async def post(self, url, json):
        self.asked.append(json)
        if url.endswith("/api/generate"):
            self.now = None if json.get("keep_alive") == 0 else self.again
            return Answer({})
        return Answer({"message": {"content": "Yes."}})


def test_a_model_not_in_memory_is_loaded_with_the_context_every_call_uses(monkeypatch):
    ollama = Ollama(now=None, again=0.48)
    monkeypatch.setattr(llm.httpx2, "AsyncClient", ollama)

    assert asyncio.run(llm.ready("qwen3.5:4b", 0.48)) == 0.48
    assert ollama.asked == [{"model": "qwen3.5:4b", "keep_alive": "30m", "options": {"num_ctx": llm.NUM_CTX}}]


def test_a_model_loaded_with_clearly_less_in_video_memory_than_it_can_have_is_loaded_again_once(monkeypatch):
    ollama = Ollama(now=0.37, again=0.48)
    monkeypatch.setattr(llm.httpx2, "AsyncClient", ollama)

    assert asyncio.run(llm.ready("qwen3.5:4b", 0.48)) == 0.48
    assert [request["keep_alive"] for request in ollama.asked] == [0, "30m"]


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
