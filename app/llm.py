"""The local models, through Ollama: which ones are installed, and how to talk to one.

Ollama is the only thing that knows the models. Nothing here chooses one: that is catalog.py.
"""
import base64
import asyncio
import json
import math
import os
import re

import httpx2

from inference_scheduler import scheduler

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
# Shared context budget; actual GPU allocation depends on the model and available memory.
NUM_CTX = int(os.getenv("NUM_CTX", "6144"))
# How long a model stays in memory after it was last asked something. Ollama's own is five minutes:
# then a search after a pause waits 15 to 20 seconds for the model to be loaded again. Half an hour,
# and the memory goes back to the computer when Regista is not being used.
KEEP_ALIVE = os.getenv("KEEP_ALIVE", "30m")


def inference_seconds() -> float | None:
    seconds = float(os.getenv('REGISTA_INFERENCE_TIMEOUT', '300'))
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('REGISTA_INFERENCE_TIMEOUT deve essere un numero finito maggiore o uguale a zero.')
    return None if seconds == 0 else seconds


def inference_timeout() -> httpx2.Timeout:
    """Five minutes for a local response; zero disables the response timeout."""
    return httpx2.Timeout(inference_seconds(), connect=20, write=60, pool=20)


async def model_digest(name: str) -> str:
    """Read the exact tag without collapsing aliases or changing any model allocation."""
    async with httpx2.AsyncClient(timeout=20) as client:
        response = await client.get(f'{OLLAMA_URL}/api/tags')
        response.raise_for_status()
        return next((model['digest'] for model in response.json().get('models', []) if model['name'] == name), '')


async def installed() -> list[dict]:
    """Every model Ollama has, with what Ollama says it can do and whether it is in memory now."""
    async with httpx2.AsyncClient(timeout=20) as client:
        tags = await client.get(f"{OLLAMA_URL}/api/tags")
        tags.raise_for_status()
        running = await client.get(f"{OLLAMA_URL}/api/ps")
        running.raise_for_status()
        loaded = {model["digest"]: model for model in running.json().get("models", [])}

        # Preserve every exact installed tag, including aliases sharing a digest.
        unique: dict[str, dict] = {}
        for tag in tags.json()["models"]:
            known = unique.get(tag["name"])
            if known is None or known["name"].endswith(":latest"):
                unique[tag["name"]] = tag

        models = []
        for tag in unique.values():
            digest = tag["digest"]
            show = await client.post(f"{OLLAMA_URL}/api/show", json={"model": tag["name"]})
            show.raise_for_status()
            details = show.json()
            in_memory = loaded.get(digest)
            models.append({
                "name": tag["name"],
                "bytes": tag["size"],
                "digest": digest,
                "quantization": details.get("details", {}).get("quantization_level", ""),
                "parameters": details.get("details", {}).get("parameter_size", ""),
                "capabilities": details.get("capabilities", []),
                "loaded": in_memory is not None,
                # how much of a loaded model sits in video memory: 1 is all of it, 0 is none
                "gpu_share": round(in_memory["size_vram"] / in_memory["size"], 2) if in_memory and in_memory["size"] else None,
            })
    return models


async def ready(model: str, share: float | None = None) -> float | None:
    """Puts a model in memory before it is asked anything, so that the first request does not wait for it.

    Existing allocations are left alone, including models loaded by other clients. `share` is
    retained for legacy callers, but never authorizes unloading. Returns the current GPU share.
    """
    async with scheduler.slot(), httpx2.AsyncClient(timeout=inference_timeout()) as client:

        async def now() -> float | None:
            running = (await client.get(f"{OLLAMA_URL}/api/ps")).json().get("models", [])
            found = next((one for one in running if model in (one.get("name"), one.get("model"))), None)
            return round(found["size_vram"] / found["size"], 2) if found and found.get("size") else None

        loaded = await now()
        if loaded is None:
            # a request with nothing to answer only loads the model: with the context size of every other call,
            # or the first real request would load it again
            response = await client.post(f"{OLLAMA_URL}/api/generate", json={"model": model, "keep_alive": KEEP_ALIVE, "options": {"num_ctx": NUM_CTX}})
            if response.status_code != 200:
                raise RuntimeError(f"Ollama answered {response.status_code}: {response.text[:300]}")
            loaded = await now()
    return loaded


def question(what: str, english: bool = True) -> str:
    """The question about one picture: in English, which the models read best, or in the user's own words."""
    if english:
        return f"Does this photo show {what}? Answer only yes or no."
    return f"Questa foto mostra: {what}? Rispondi solo sì o no."


async def sees_many(model: str, pictures: list[bytes], what: str, english: bool = True) -> list[bool]:
    """For each of a few pictures, whether it shows `what`: asked about them together. Measured on the 200
    samples, 4 at a time took 0.67 seconds a picture against 1.06 one by one, and were as right about what
    is there (171 of 173 against 169 of 171); but about what is not there they said yes twice as often, 6
    times in 200 against 3, so Regista asks one at a time (orchestrator.GROUP). 8 at a time were no faster.
    One picture is asked about alone.
    """
    if len(pictures) == 1:
        return [await sees(model, pictures[0], question(what, english))]
    count = len(pictures)
    if english:
        text = (f"Here are {count} photos, numbered from 1 to {count} in the order given. For each one: does it show {what}? "
                "Answer with one line per photo, like '1: yes', and nothing else.")
    else:
        text = (f"Ecco {count} foto, numerate da 1 a {count} nell'ordine in cui sono date. Per ciascuna: mostra {what}? "
                "Rispondi con una riga per foto, come '1: sì', e nient'altro.")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": text, "images": [base64.b64encode(picture).decode() for picture in pictures]}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": 8 * count},
        "keep_alive": KEEP_ALIVE,
    }
    async with scheduler.slot(), httpx2.AsyncClient(timeout=inference_timeout()) as client:
        response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"Ollama answered {response.status_code}: {response.text[:300]}")
    answer = response.json().get("message", {}).get("content", "").lower()
    said = []
    for number in range(1, count + 1):
        line = re.search(rf"(?<!\d){number}\s*[:.)\-]\s*(yes|no|sì|si)\b", answer)
        # a picture the answer does not name counts as not showing it: better one missing than one wrong
        said.append(bool(line) and line.group(1) != "no")
    return said


async def sees(model: str, picture: bytes, question: str) -> bool:
    """Whether a model that looks at pictures answers yes to a question about one: what it sees, not what numbers guess.

    The same context size as every other call, so that a model that directs and looks too is not loaded again.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": question, "images": [base64.b64encode(picture).decode()]}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": 3},
        "keep_alive": KEEP_ALIVE,
    }
    async with scheduler.slot(), httpx2.AsyncClient(timeout=inference_timeout()) as client:
        response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"Ollama answered {response.status_code}: {response.text[:300]}")
    answer = response.json().get("message", {}).get("content", "").strip().lower()
    return answer.startswith(("yes", "sì", "si"))


async def stream(model: str, messages: list[dict], max_tokens: int = 700, schema: dict | None = None):
    """One reply of a model, as it is produced.

    Yields ("text", piece) while the model writes, and at the end ("stats", {...}) with how
    many tokens it wrote and how fast. With `schema`, the reply is JSON that is guaranteed
    to match it. Leaving the loop early closes the connection, and Ollama stops generating.
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        # A model that can think aloud before it answers (Qwen3.5) would take many times as long for
        # a decision of a few words: it answers straight away. Models that cannot think ignore this.
        "think": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": max_tokens},
        "keep_alive": KEEP_ALIVE,
    }
    if schema:
        payload["format"] = schema
    async with scheduler.slot(), httpx2.AsyncClient(timeout=inference_timeout()) as client:
        async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode(errors="replace")
                raise RuntimeError(f"Ollama answered {response.status_code}: {body[:300]}")
            async for line in response.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                message = chunk.get("message", {})
                if message.get("content"):
                    yield "text", message["content"]
                if chunk.get("done"):
                    seconds = chunk.get("eval_duration", 0) / 1e9
                    yield "stats", {
                        "tokens": chunk.get("eval_count", 0),
                        "tokens_per_second": round(chunk.get("eval_count", 0) / seconds, 1) if seconds else 0,
                        # a model that was not in memory had to be loaded first: this is how long that took
                        "load_seconds": round(chunk.get("load_duration", 0) / 1e9, 1),
                    }


async def structured(model: str, messages: list[dict], schema: dict, *, background=False, max_tokens=1000,
                     options: dict | None = None) -> dict:
    """A nonstreaming JSON response; all inference uses the same arbiter."""
    async with scheduler.slot(background=background), httpx2.AsyncClient(timeout=inference_timeout()) as client:
        # Bound the whole response even if Ollama keeps sending occasional bytes; queue wait is separate.
        async with asyncio.timeout(inference_seconds()):
            response = await client.post(f"{OLLAMA_URL}/api/chat", json={
                "model": model, "messages": messages, "format": schema, "stream": False, "think": False,
                "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": max_tokens, **(options or {})}, "keep_alive": KEEP_ALIVE,
            })
        response.raise_for_status()
        return response.json()
