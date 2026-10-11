"""Tries the installed models on this computer, so that the choice among them rests on what they did here.

A model can declare that it uses tools and still decide badly, and how fast it is
depends on the machine. So each model gets the same requests, and for each one the
question is whether it decided to do the right thing with it. Then it writes a few
lines, to see how many tokens per second it manages here. The results are kept on
disk and used by catalog.py.
"""
import datetime
import json
from pathlib import Path

import catalog
import llm
from orchestrator import TALK, decide

# a request, and the right thing to do with it
CASES = [
    ("trovami le foto con un cane", "find_photos"),
    ("show me the pictures of the beach at sunset", "find_photos"),
    ("mi fai vedere le foto delle chiese?", "find_photos"),
    ("cerca le immagini con una macchina rossa", "find_photos"),
    ("quante foto ho?", "count_photos"),
    ("ciao, come stai?", "answer"),
    ("quanto fa 12 per 12?", "answer"),
    ("spiegami in una frase cos'è una scheda video", "answer"),
    # the word "foto" is there, and still nothing is to be searched
    ("dammi tre consigli brevi per fare belle foto", "answer"),
    ("che differenza c'è tra jpg e png?", "answer"),
    # what changes the pictures: told to do it, the model must propose it; asked how it is done, it must answer
    ("elimina le foto dei gatti", "trash_photos"),
    ("copia le foto del mare in una cartella chiamata Estate", "copy_photos"),
    ("annulla l'ultima modifica", "undo"),
    ("come si svuota il cestino di Windows?", "answer"),
]
# what a model is asked to write when its speed is measured
SPEED_PROBE = "Describe in three sentences what a web browser does."


def load(index_dir: str) -> dict:
    """The results of the last test, model by model. Results of a test with other requests are left out: they do not say how a model does on these."""
    file = Path(index_dir) / "tests.json"
    saved = json.loads(file.read_text()) if file.exists() else {}
    return {name: result for name, result in saved.items() if result.get("cases") == len(CASES)}


def save(index_dir: str, tests: dict) -> None:
    Path(index_dir).mkdir(parents=True, exist_ok=True)
    (Path(index_dir) / "tests.json").write_text(json.dumps(tests, indent=1))


async def try_case(model: str, request: str, expected: str) -> bool:
    """One request to one model: did it decide to do the right thing with it."""
    decision = await decide(model, [{"role": "user", "content": request}])
    # a search with nothing to search for is not a search, and a copy needs the name of its folder
    needed = {"find_photos": "caption", "copy_photos": "folder"}.get(expected)
    return decision["action"] == expected and (needed is None or bool(decision[needed]))


async def speed(model: str) -> float:
    """Tokens per second of a model on this machine, on a short piece of writing."""
    measured = 0.0
    async for kind, value in llm.stream(model, [{"role": "system", "content": TALK}, {"role": "user", "content": SPEED_PROBE}], max_tokens=90):
        if kind == "stats":
            measured = value["tokens_per_second"]
    return measured


async def run(index_dir: str):
    """Tries every model that can direct. Yields progress, and saves the results at the end."""
    models = await llm.installed()
    candidates = [model["name"] for model in models if "tools" in catalog.can(model)]
    tests = load(index_dir)
    for name in candidates:
        right = 0
        for number, (request, expected) in enumerate(CASES, start=1):
            yield {"type": "progress", "model": name, "case": number, "cases": len(CASES)}
            try:
                right += await try_case(name, request, expected)
            except Exception as exc:
                yield {"type": "problem", "model": name, "message": f"{type(exc).__name__}: {exc}"}
        try:
            tokens_per_second = await speed(name)
        except Exception as exc:
            yield {"type": "problem", "model": name, "message": f"{type(exc).__name__}: {exc}"}
            tokens_per_second = 0.0
        # the model is still in memory: how much of it sits in the video memory
        share = next((model["gpu_share"] for model in await llm.installed() if model["name"] == name), None)
        tests[name] = {
            "cases": len(CASES),
            "right": right,
            "tokens_per_second": tokens_per_second,
            "gpu_share": share,
            "tested_on": str(datetime.date.today()),
        }
        yield {"type": "result", "model": name, **tests[name]}
    save(index_dir, tests)
    yield {"type": "done", "tests": tests}
