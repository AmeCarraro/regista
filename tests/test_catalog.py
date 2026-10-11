"""Which model gets which job."""
import pytest

import catalog
from catalog import Hardware

LAPTOP = Hardware(gpu="RTX 3050 Ti", gpu_gb=4.0, ram_gb=16.0, cores=14)
NO_GPU = Hardware(gpu="", gpu_gb=0, ram_gb=8.0, cores=4)


def model(name, gigabytes, parameters, capabilities, loaded=False):
    return {"name": name, "bytes": gigabytes * 1e9, "parameters": parameters, "capabilities": capabilities, "loaded": loaded, "gpu_share": None}


GRANITE = model("granite4.1:3b", 2.1, "3.4B", ["completion", "tools"])
LLAMA = model("llama3.2:3b", 2.0, "3.2B", ["completion", "tools"])
BIG = model("big:8b", 5.2, "8.0B", ["completion", "tools"])
EYES = model("eyes:4b", 3.0, "4.3B", ["completion", "vision"])
NOMIC = model("nomic-embed-text:latest", 0.3, "137M", ["embedding"])
ALL = [LLAMA, NOMIC, BIG, GRANITE, EYES]


def test_what_a_model_is_for_comes_from_what_it_declares():
    assert catalog.can(GRANITE) == ["tools", "chat"]
    assert catalog.can(EYES) == ["chat", "vision"]
    assert catalog.can(NOMIC) == []


def test_a_model_larger_than_the_video_memory_is_not_the_first_choice():
    # the 8B model would write better, but it does not fit in 4 GB and would crawl
    assert catalog.where(BIG, LAPTOP) == "split"
    assert catalog.pick("tools", ALL, LAPTOP, {}) == "granite4.1:3b"
    assert catalog.pick("chat", ALL, LAPTOP, {}) == "eyes:4b"


def test_without_a_graphics_card_everything_runs_on_the_processor():
    # half of 8 GB of memory can go to a model: the small ones are fine, the 8B one is too much
    assert NO_GPU.budget_gb == 4.0
    assert catalog.where(GRANITE, NO_GPU) == "cpu"
    assert catalog.where(BIG, NO_GPU) == "heavy"
    assert catalog.pick("tools", ALL, NO_GPU, {}) == "granite4.1:3b"


def test_a_model_known_to_get_tools_wrong_is_not_the_orchestrator_until_it_proves_itself():
    assert catalog.ranked("tools", [LLAMA, GRANITE], LAPTOP, {})[0]["name"] == "granite4.1:3b"

    proven = {"llama3.2:3b": {"cases": 8, "right": 8, "tokens_per_second": 70}, "granite4.1:3b": {"cases": 8, "right": 5, "tokens_per_second": 60}}
    assert catalog.ranked("tools", [LLAMA, GRANITE], LAPTOP, proven)[0]["name"] == "llama3.2:3b"


def test_a_model_seen_to_spill_out_of_the_video_memory_is_judged_by_that_and_not_by_its_size():
    # by its size llama would fit; when it was tried, a tenth of it ended up on the processor
    tried = {"llama3.2:3b": {"cases": 10, "right": 10, "tokens_per_second": 47, "gpu_share": 0.9},
             "granite4.1:3b": {"cases": 10, "right": 10, "tokens_per_second": 62, "gpu_share": 1.0}}

    assert catalog.where(LLAMA, LAPTOP) == "gpu"
    assert catalog.where(LLAMA, LAPTOP, tried) == "split"
    assert catalog.pick("tools", [LLAMA, GRANITE], LAPTOP, tried) == "granite4.1:3b"


def test_the_user_can_choose_who_talks_but_only_among_those_who_can():
    assert catalog.pick("chat", ALL, LAPTOP, {}, wanted="llama3.2:3b") == "llama3.2:3b"
    # an embedding model cannot talk: the choice falls back to the best one
    assert catalog.pick("chat", ALL, LAPTOP, {}, wanted="nomic-embed-text:latest") == "eyes:4b"
    assert catalog.pick("vision", [GRANITE, LLAMA], LAPTOP, {}) is None


def test_the_page_gets_every_model_with_what_it_is_for_and_the_order_for_each_job():
    described = catalog.describe(ALL, LAPTOP, {"granite4.1:3b": {"cases": 8, "right": 8, "tokens_per_second": 61.5}})

    assert described["hardware"] == {"gpu": "RTX 3050 Ti", "gpu_gb": 4.0, "ram_gb": 16.0, "cores": 14}
    assert described["order"]["tools"][0] == "granite4.1:3b"
    assert described["order"]["vision"] == ["eyes:4b"]
    granite = next(entry for entry in described["models"] if entry["name"] == "granite4.1:3b")
    assert granite == {
        "name": "granite4.1:3b", "gigabytes": 2.1, "parameters": "3.4B", "can": ["tools", "chat"],
        "where": "gpu", "loaded": False, "tested": {"cases": 8, "right": 8, "tokens_per_second": 61.5},
    }
    # models that cannot talk are listed last
    assert described["models"][-1]["name"] == "nomic-embed-text:latest"


@pytest.mark.parametrize("machine, installed, name, place, there", [
    # a 4 GB card: the small one, which is already there
    (LAPTOP, [GRANITE, LLAMA], "granite4.1:3b", "gpu", True),
    # 12 and 16 GB: the 8B one fits whole, the 30B one does not
    (Hardware("RTX 4070", 12.0, 32.0, 16), [GRANITE], "granite4.1:8b", "gpu", False),
    (Hardware("RTX 5080", 16.0, 32.0, 16), [], "granite4.1:8b", "gpu", False),
    (Hardware("RTX 4090", 24.0, 64.0, 24), [], "granite4.1:30b", "gpu", False),
    # no card: the small one, however much memory there is, because the processor is slow
    (NO_GPU, [], "granite4.1:3b", "cpu", False),
    (Hardware("", 0, 64.0, 16), [], "granite4.1:3b", "cpu", False),
    # a card too small even for the small one still takes a part of it
    (Hardware("GT 1030", 2.0, 8.0, 4), [], "granite4.1:3b", "split", False),
])
def test_the_model_suggested_for_a_computer_is_the_largest_that_runs_well_on_it(machine, installed, name, place, there):
    suggested = catalog.suggest(installed, machine)

    assert (suggested["name"], suggested["where"], suggested["installed"]) == (name, place, there)
    assert suggested["command"] == f"ollama pull {name}" and suggested["gigabytes"] > 0


def test_nothing_is_suggested_for_a_computer_that_was_not_measured_or_has_too_little_memory():
    assert catalog.suggest([], Hardware("", 0, 0, 0)) is None
    assert catalog.suggest([], Hardware("", 0, 3.0, 2)) is None
    assert catalog.describe([], Hardware("", 0, 0, 0), {})["suggested"] is None


def test_the_computer_is_described_by_whoever_starts_the_app(monkeypatch):
    monkeypatch.setenv("HOST_GPU_NAME", "RTX 3050 Ti")
    monkeypatch.setenv("HOST_GPU_MB", "4096")
    monkeypatch.setenv("HOST_RAM_MB", "16384")
    monkeypatch.setenv("HOST_CORES", "14")

    machine = catalog.hardware()

    assert (machine.gpu_gb, machine.ram_gb, machine.cores) == (4.0, 16.0, 14)
    assert machine.budget_gb == pytest.approx(3.2)
