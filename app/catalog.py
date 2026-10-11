"""Which model for which job, on this computer.

A model is described by what Ollama says it can do, by whether it fits in the video
memory of this machine, and, once it has been tried, by how it actually did here
(selftest.py). The choice prefers what was measured to what is declared: a model can
declare that it uses tools and get every call wrong.
"""
import os
from dataclasses import dataclass

# The jobs the app needs done. "tools" is the orchestrator: it decides what to do with a request.
JOBS = {
    "tools": "decides what to do and uses the tools",
    "chat": "answers in words",
    "vision": "looks at a picture",
}
# what Ollama calls each job
NEEDS = {"tools": "tools", "chat": "completion", "vision": "vision"}
# video memory a model needs on top of its file, for the conversation it holds
HEADROOM_GB = 0.8
# Models that declare tools and, when tried in this project, did not manage a single call.
# It is only a starting opinion: a test on this computer replaces it.
POOR_AT_TOOLS = ("llama3.2",)
# The models the app can suggest for the job of director, smallest first, with the size of the
# download. The first is the one this app was built and measured with; the others are the same
# model in larger sizes. Names and sizes as the Ollama library gave them on 2026-10-11.
SUGGESTED = [
    {"name": "granite4.1:3b", "gigabytes": 2.1},
    {"name": "granite4.1:8b", "gigabytes": 5.3},
    {"name": "granite4.1:30b", "gigabytes": 17.0},
]


@dataclass
class Hardware:
    gpu: str
    gpu_gb: float
    ram_gb: float
    cores: int

    @property
    def budget_gb(self) -> float:
        """The size of the largest model that runs well here.

        With a graphics card it is what fits in its memory. Without one the model runs on the
        processor, slowly, and may use up to half of the system memory.
        """
        return self.gpu_gb - HEADROOM_GB if self.gpu_gb else self.ram_gb / 2


def hardware() -> Hardware:
    """The computer the models run on. The app itself runs in a container and cannot see it,
    so whoever starts the app measures it and passes it in (run.ps1)."""
    return Hardware(
        gpu=os.getenv("HOST_GPU_NAME", ""),
        gpu_gb=round(int(os.getenv("HOST_GPU_MB") or 0) / 1024, 1),
        ram_gb=round(int(os.getenv("HOST_RAM_MB") or 0) / 1024, 1),
        cores=int(os.getenv("HOST_CORES") or 0),
    )


def _gigabytes(model: dict) -> float:
    return model["bytes"] / 1e9


def _billions(model: dict) -> float:
    """Size of the model as a number: "3.4B" is 3.4, "137M" is 0.137."""
    text = model["parameters"].upper()
    try:
        return float(text.rstrip("BM")) / (1000 if text.endswith("M") else 1)
    except ValueError:
        return 0


def can(model: dict) -> list[str]:
    """The jobs a model can be given, going by what it declares."""
    return [job for job, capability in NEEDS.items() if capability in model["capabilities"]]


def where(model: dict, machine: Hardware, tests: dict | None = None) -> str:
    """Where a model runs on this machine.

    "gpu": the whole model fits in video memory. "split": it is shared between video memory
    and processor, which is slow. "cpu": there is no graphics card and the model is small
    enough for the processor. "heavy": no graphics card, and too large for the memory.
    A model that was tried is judged by what was seen then, the others by their size.
    """
    share = (tests or {}).get(model["name"], {}).get("gpu_share")
    if machine.gpu_gb and share is not None:
        return "gpu" if share >= 1 else "split"
    fits = _gigabytes(model) <= machine.budget_gb
    if machine.gpu_gb:
        return "gpu" if fits else "split"
    return "cpu" if fits else "heavy"


def runs_well(model: dict, machine: Hardware, tests: dict | None = None) -> bool:
    return where(model, machine, tests) in ("gpu", "cpu")


def _tool_score(model: dict, tests: dict) -> float:
    """How well a model uses tools, from 0 to 1: measured if it was tried, guessed otherwise."""
    tried = tests.get(model["name"])
    if tried:
        return tried["right"] / tried["cases"]
    return 0.1 if model["name"].startswith(POOR_AT_TOOLS) else 0.6


def ranked(job: str, models: list[dict], machine: Hardware, tests: dict) -> list[dict]:
    """The models that can do a job, best first."""
    able = [model for model in models if job in can(model)]

    def key(model: dict):
        fits = runs_well(model, machine, tests)
        tools = _tool_score(model, tests) if job == "tools" else 0
        speed = tests.get(model["name"], {}).get("tokens_per_second", 0)
        # what fits comes first; for the orchestrator, then whoever gets the tools right;
        # then the larger model, which usually writes better; then the faster one
        return (fits, tools, _billions(model), speed)

    return sorted(able, key=key, reverse=True)


def suggest(models: list[dict], machine: Hardware) -> dict | None:
    """The model to have on this computer for the job of director, among the ones the app knows.

    With a graphics card it is the largest that fits in its memory: a larger model decides
    better, and there it is still fast. Without one it is the smallest: on the processor a
    larger model would make every request wait. None when the computer was not measured, or
    has too little memory for any of them.
    """
    smallest = SUGGESTED[0]
    if machine.gpu_gb:
        fitting = [model for model in SUGGESTED if model["gigabytes"] <= machine.budget_gb]
        # a card too small for all of them still helps the smallest, which then runs partly on the processor
        chosen, place = (fitting[-1], "gpu") if fitting else (smallest, "split")
    elif smallest["gigabytes"] <= machine.budget_gb:
        chosen, place = smallest, "cpu"
    else:
        return None
    return {
        **chosen,
        "where": place,
        "installed": any(model["name"] == chosen["name"] for model in models),
        # the app does not download models by itself: this is what the user runs, if they want to
        "command": f"ollama pull {chosen['name']}",
    }


def describe(models: list[dict], machine: Hardware, tests: dict) -> dict:
    """Everything the page shows about the models: each one with what it is for, and who gets each job."""
    order = {job: [model["name"] for model in ranked(job, models, machine, tests)] for job in JOBS}
    listed = []
    for model in sorted(models, key=lambda model: (not can(model), -_billions(model))):
        listed.append({
            "name": model["name"],
            "gigabytes": round(_gigabytes(model), 1),
            "parameters": model["parameters"],
            "can": can(model),
            "where": where(model, machine, tests),
            "loaded": model["loaded"],
            "tested": tests.get(model["name"]),
        })
    return {
        "hardware": {"gpu": machine.gpu, "gpu_gb": machine.gpu_gb, "ram_gb": machine.ram_gb, "cores": machine.cores},
        "models": listed,
        # for every job, the names in order of preference: the first is what "automatic" uses
        "order": order,
        # the model worth having on this computer, whether it is installed or not
        "suggested": suggest(models, machine),
    }


def pick(job: str, models: list[dict], machine: Hardware, tests: dict, wanted: str = "auto") -> str | None:
    """The model for a job: the one the user asked for if it can do it, else the best one."""
    names = [model["name"] for model in ranked(job, models, machine, tests)]
    if wanted != "auto" and wanted in names:
        return wanted
    return names[0] if names else None
