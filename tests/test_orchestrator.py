"""The orchestrator without Ollama: the models are scripted, the picture index is a fake."""
import asyncio
import json

import pytest

import llm
import orchestrator
import selftest
from catalog import Hardware
from fakes import ColourEmbedder, shot
from phone import Phones

LAPTOP = Hardware(gpu="RTX 3050 Ti", gpu_gb=4.0, ram_gb=16.0, cores=14)
GRANITE = {"name": "granite4.1:3b", "bytes": 2.1e9, "parameters": "3.4B", "capabilities": ["completion", "tools"], "loaded": True, "gpu_share": 1.0}
POET = {"name": "poet:4b", "bytes": 2.5e9, "parameters": "4.0B", "capabilities": ["completion"], "loaded": False, "gpu_share": None}


class Photos:
    """A fake index that remembers what it was asked."""

    def __init__(self, sure=2, maybe=1, indexed=200, running=False, matching=None):
        self.asked, self.limits, self.periods = [], [], []
        self.state = {"running": running, "total": indexed}
        self.photos = [{"id": f"p{n}", "path": f"trip/p{n}.jpg"} for n in range(indexed)]
        self.result = {
            "sure": [{"id": f"p{n}", "name": f"p{n}.jpg", "score": 0.3} for n in range(sure)],
            "maybe": [{"id": f"p{sure + n}", "name": f"p{sure + n}.jpg", "score": 0.23} for n in range(maybe)],
            "matching": sure if matching is None else matching,
            "indexed": indexed,
        }

    def search(self, description, limit=60, period=None):
        self.asked.append(description)
        self.limits.append(limit)
        self.periods.append(period)
        return dict(self.result)


class Changes:
    """Fake actions. The orchestrator may ask them what could be done, and must never do it."""

    def __init__(self, writable=True, last=None):
        self.can, self.previous, self.done = writable, last, []

    def writable(self):
        return self.can

    def last(self):
        return self.previous

    def trash(self, *_):
        self.done.append("trash")

    def copy(self, *_):
        self.done.append("copy")

    def undo(self, *_):
        self.done.append("undo")


def find(caption):
    return json.dumps({"action": "find_photos", "caption": caption})


def form(action, caption="", folder=""):
    return json.dumps({"action": action, "caption": caption, "folder": folder})


ANSWER = json.dumps({"action": "answer", "caption": ""})
COUNT = json.dumps({"action": "count_photos", "caption": ""})
TRASHED = {"id": "20261011-150000-ab12", "kind": "trash", "when": "2026-10-11T15:00:00+02:00", "files": [{"from": "a.jpg", "to": "x"}] * 3}


def script(monkeypatch, replies):
    """Makes llm.stream give the scripted replies, one per call, in two pieces, and records what each call was given."""
    seen = []

    async def fake_stream(model, messages, max_tokens=700, schema=None):
        seen.append({"model": model, "messages": messages, "max_tokens": max_tokens, "schema": schema})
        reply = replies[len(seen) - 1]
        for piece in (reply[: len(reply) // 2], reply[len(reply) // 2:]):
            if piece:
                yield "text", piece
        yield "stats", {"tokens": 10, "tokens_per_second": 60.0, "load_seconds": 0}

    monkeypatch.setattr(llm, "stream", fake_stream)
    return seen


def ask(text, photos=None, models=(GRANITE,), wanted="auto", history=(), actions=None, selection=(), phones=None):
    photos = photos or Photos()

    async def collect():
        messages = [*history, {"role": "user", "content": text}]
        return [event async for event in orchestrator.reply(messages, wanted, list(models), LAPTOP, {}, photos, actions, list(selection), phones)]

    return asyncio.run(collect()), photos


def proposed(events):
    return next((event for event in events if event["type"] == "proposal"), None)


def said(events):
    return "".join(event["text"] for event in events if event["type"] == "text")


def test_a_request_for_pictures_becomes_a_search_and_the_app_says_what_it_found(monkeypatch):
    seen = script(monkeypatch, [find("a black dog")])

    events, photos = ask("trovami le foto con un cane nero")

    assert photos.asked == ["a black dog"]
    assert [event["type"] for event in events] == ["start", "step", "photos", "text", "done"]
    assert events[1] == {"type": "step", "tool": "find_photos", "arguments": {"description": "a black dog", "place": "computer", "period": "", "spot": ""}}
    assert events[2]["place"] == "computer"
    assert [photo["id"] for photo in events[2]["sure"]] == ["p0", "p1"]
    # counted by the app, not written by the model
    assert said(events) == "Ho trovato 2 foto. Ce n'è un'altra che potrebbe andare bene."
    assert events[-1]["memory"] == 'Searched the photos for "a black dog": 2 found, 1 uncertain.'
    # the model was asked once, for a decision in the shape of the form
    assert len(seen) == 1 and seen[0]["schema"] == orchestrator.DECISION


def test_anything_else_is_answered_in_words_as_they_are_written(monkeypatch):
    seen = script(monkeypatch, [ANSWER, "Sto bene, grazie."])

    events, photos = ask("ciao, come stai?")

    assert photos.asked == []
    assert [event["type"] for event in events] == ["start", "text", "text", "done"]
    assert said(events) == events[-1]["memory"] == "Sto bene, grazie."
    assert events[-1]["model"] == "granite4.1:3b" and events[-1]["tokens_per_second"] == 60.0
    # first the decision, then the answer: free text, with the instructions for talking
    assert [call["schema"] for call in seen] == [orchestrator.DECISION, None]
    assert seen[1]["messages"][0]["content"] == orchestrator.TALK


def test_the_model_reads_the_conversation_so_a_request_can_build_on_the_last_one(monkeypatch):
    seen = script(monkeypatch, [find("a black dog")])
    history = [
        {"role": "user", "content": "trovami le foto con un cane"},
        {"role": "assistant", "content": 'Searched the photos for "a dog": 20 found, 3 uncertain.'},
    ]

    ask("solo quelli neri", history=history)

    roles = [message["role"] for message in seen[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert seen[0]["messages"][2]["content"].startswith('Searched the photos for "a dog"')


def test_when_another_model_is_chosen_to_talk_the_director_only_decides(monkeypatch):
    seen = script(monkeypatch, [ANSWER, "Nel mezzo del cammin..."])

    events, _ = ask("scrivimi una poesia", models=(GRANITE, POET), wanted="poet:4b")

    assert [call["model"] for call in seen] == ["granite4.1:3b", "poet:4b"]
    assert said(events) == "Nel mezzo del cammin..."
    assert events[0] == {"type": "start", "director": "granite4.1:3b", "writer": "poet:4b", "loading": False}
    assert events[-1]["model"] == "poet:4b"


def test_the_director_still_searches_when_another_model_was_chosen_to_talk(monkeypatch):
    seen = script(monkeypatch, [find("a church")])

    events, photos = ask("le foto delle chiese", models=(GRANITE, POET), wanted="poet:4b")

    assert photos.asked == ["a church"] and len(seen) == 1
    assert events[-1]["model"] == "granite4.1:3b"


def test_a_model_that_is_not_in_memory_is_announced_as_loading(monkeypatch):
    script(monkeypatch, [ANSWER, "Ciao."])

    events, _ = ask("ciao", models=({**GRANITE, "loaded": False},))

    assert events[0]["loading"] is True


def test_without_a_model_that_can_direct_the_app_can_still_talk(monkeypatch):
    seen = script(monkeypatch, ["Ciao."])

    events, _ = ask("ciao", models=(POET,))

    assert events[0]["director"] is None and said(events) == "Ciao."
    # no decision was asked for: the only call is the answer
    assert len(seen) == 1 and seen[0]["schema"] is None


def test_with_no_model_at_all_the_app_says_what_to_check(monkeypatch):
    script(monkeypatch, [])

    events, _ = ask("ciao", models=())

    assert said(events) == orchestrator.NO_MODEL


def test_how_many_pictures_is_counted_by_the_app(monkeypatch):
    script(monkeypatch, [COUNT])

    events, photos = ask("quante foto ho?", photos=Photos(indexed=200))

    assert photos.asked == []
    assert said(events) == "Conosco 200 foto."
    assert events[-1]["memory"] == "Counted the photos: 200."


def test_while_the_pictures_are_being_read_the_count_says_so():
    assert orchestrator.counted_in_words({"running": True, "total": 500}, 120) == "Sto ancora leggendo le foto: ne conosco 120 su 500."
    assert orchestrator.counted_in_words({"running": False, "total": 0}, 0) == orchestrator.NO_PHOTOS


def test_a_search_with_nothing_to_search_for_is_not_run(monkeypatch):
    script(monkeypatch, [find("  ")])

    events, photos = ask("le foto")

    assert photos.asked == [] and said(events) == orchestrator.UNCLEAR


@pytest.mark.parametrize("written", ["I think the user wants photos", '{"action": "delete_everything", "caption": ""}', '["find_photos"]'])
def test_a_decision_that_is_not_a_valid_form_means_just_answer(monkeypatch, written):
    script(monkeypatch, [written, "Non posso farlo."])

    events, photos = ask("cancella tutto")

    assert photos.asked == [] and said(events) == "Non posso farlo."


@pytest.mark.parametrize("sure, maybe, indexed, running, expected", [
    (1, 0, 50, False, "Ho trovato 1 foto."),
    (12, 8, 50, False, "Ho trovato 12 foto. Altre 8 potrebbero andare bene, ma ne sono meno sicuro."),
    (0, 3, 50, False, "Non sono sicuro di averne trovate. Queste 3 sono le più vicine."),
    (0, 0, 50, False, "Non ho trovato niente del genere tra le 50 foto che conosco."),
    (0, 0, 0, False, orchestrator.NO_PHOTOS),
    (2, 0, 50, True, "Ho trovato 2 foto. Sto ancora leggendo le foto, quindi il risultato è parziale."),
])
def test_what_was_found_in_words(sure, maybe, indexed, running, expected):
    result = {"sure": [{}] * sure, "maybe": [{}] * maybe, "matching": sure, "indexed": indexed, "partial": running}

    assert orchestrator.found_in_words(result) == expected


def test_when_more_match_than_are_shown_the_app_says_how_many_there_are(monkeypatch):
    script(monkeypatch, [find("a dog")])

    events, _ = ask("le foto dei cani", photos=Photos(sure=60, maybe=0, indexed=5000, matching=412))

    assert said(events) == "Ho trovato 412 foto: ti mostro le 60 più vicine a quello che hai chiesto."
    assert events[-1]["memory"] == 'Searched the photos for "a dog": 412 found, 0 uncertain.'


# ---- what would change the pictures is proposed, and never done here


def test_throwing_away_the_pictures_on_screen_is_only_proposed(monkeypatch):
    script(monkeypatch, [form("trash_photos")])
    actions = Changes()

    events, photos = ask("eliminale", actions=actions, selection=["p3", "p7", "p3", "not a picture"])

    assert [event["type"] for event in events] == ["start", "text", "proposal", "done"]
    # the pictures the user was looking at, once each, and only the ones that exist
    assert proposed(events) == {"type": "proposal", "action": "trash", "folder": "", "photos": [{"id": "p3", "name": "p3.jpg"}, {"id": "p7", "name": "p7.jpg"}]}
    assert said(events) == "Sposto nel cestino queste 2 foto? Restano sul disco, e le riporto dov'erano quando vuoi."
    assert "Nothing was done" in events[-1]["memory"]
    assert photos.asked == [] and actions.done == []


def test_a_request_that_says_which_pictures_searches_them_and_proposes_the_sure_ones(monkeypatch):
    script(monkeypatch, [form("trash_photos", "a sunset")])
    actions = Changes()

    events, photos = ask("butta via le foto dei tramonti", photos=Photos(sure=3, maybe=4), actions=actions)

    assert [event["type"] for event in events] == ["start", "step", "text", "proposal", "done"]
    assert photos.asked == ["a sunset"] and photos.limits == [orchestrator.MOST]
    assert [photo["id"] for photo in proposed(events)["photos"]] == ["p0", "p1", "p2"]
    # the search is remembered with the proposal, so that the next request can build on it
    assert events[-1]["memory"] == 'Searched the photos for "a sunset": 3 found. Proposed to move them to the trash (3 photos). Nothing was done: the user must confirm.'
    assert actions.done == []


def test_a_copy_is_proposed_with_a_folder_name_that_cannot_lead_elsewhere(monkeypatch):
    script(monkeypatch, [form("copy_photos", "", "../../Windows")])

    events, _ = ask("copiale in ../../Windows", actions=Changes(), selection=["p1"])

    assert proposed(events)["action"] == "copy" and proposed(events)["folder"] == "Windows"
    assert said(events) == "Copio questa foto nella cartella «Windows»? Gli originali restano dove sono."
    assert 'copy them into the folder "Windows"' in events[-1]["memory"]


@pytest.mark.parametrize("folder", ["", "...", "  "])
def test_a_copy_without_a_usable_folder_name_is_proposed_and_the_name_is_asked_for(monkeypatch, folder):
    script(monkeypatch, [form("copy_photos", "", folder)])

    events, _ = ask("copiale in una cartella", actions=Changes(), selection=["p1", "p2"])

    assert proposed(events)["folder"] == "" and len(proposed(events)["photos"]) == 2
    assert said(events) == "Copio queste 2 foto in una cartella nuova? Scrivi qui sotto come chiamarla. Gli originali restano dove sono."
    assert "a folder that has no name yet" in events[-1]["memory"]


@pytest.mark.parametrize("written, selection, expected", [
    (form("copy_photos", "", "Cani"), [], orchestrator.WHICH_ONES),
    (form("trash_photos"), [], orchestrator.WHICH_ONES),
    (form("trash_photos"), ["gone"], orchestrator.WHICH_ONES),
    (form("undo"), [], orchestrator.NOTHING_TO_UNDO),
])
def test_when_something_is_missing_the_app_asks_and_proposes_nothing(monkeypatch, written, selection, expected):
    script(monkeypatch, [written])
    actions = Changes()

    events, _ = ask("fallo", actions=actions, selection=selection)

    assert said(events) == expected and proposed(events) is None and actions.done == []


def test_when_no_picture_matches_nothing_is_proposed(monkeypatch):
    script(monkeypatch, [form("trash_photos", "a unicorn")])

    events, _ = ask("elimina le foto degli unicorni", photos=Photos(sure=0, maybe=5), actions=Changes())

    assert said(events) == orchestrator.NONE_LIKE_THAT and proposed(events) is None


def test_taking_back_the_last_change_is_proposed_too(monkeypatch):
    script(monkeypatch, [form("undo")])
    actions = Changes(last=TRASHED)

    events, _ = ask("annulla", actions=actions)

    assert proposed(events) == {"type": "proposal", "action": "undo", "of": TRASHED["id"], "undoes": "trash", "folder": "", "count": 3, "when": TRASHED["when"]}
    assert said(events) == "L'ultima modifica è stata spostare 3 foto nel cestino. Le rimetto al loro posto?"
    assert actions.done == []


def test_a_folder_given_to_read_only_is_said_and_nothing_is_proposed(monkeypatch):
    script(monkeypatch, [form("trash_photos")])

    events, _ = ask("eliminale", actions=Changes(writable=False), selection=["p1"])

    assert said(events) == orchestrator.READ_ONLY and proposed(events) is None


def test_more_pictures_than_one_request_may_change_are_proposed_a_part_at_a_time():
    photos = Photos(sure=orchestrator.MOST, matching=950)

    plan = orchestrator.propose({"action": "trash_photos", "caption": "a dog", "folder": ""}, photos, Changes(), [])

    assert len(plan["proposal"]["photos"]) == orchestrator.MOST
    assert plan["text"].endswith(f"In tutto sono 950: te ne propongo {orchestrator.MOST} per volta.")


@pytest.mark.parametrize("result, text, memory", [
    ({"kind": "trash", "count": 14, "missing": 0, "failed": 0},
     "Fatto: 14 foto nel cestino. Per riaverle basta dirmi «annulla».", "The user confirmed: 14 photos were moved to the trash."),
    ({"kind": "trash", "count": 2, "missing": 1, "failed": 3},
     "Fatto: 2 foto nel cestino. Per riaverle basta dirmi «annulla». 1 foto non c'era più. 3 foto non sono riuscito a toccarle: forse sono aperte in un altro programma.",
     "The user confirmed: 2 photos were moved to the trash."),
    ({"kind": "trash", "count": 1, "missing": 0, "failed": 0},
     "Fatto: 1 foto nel cestino. Per riaverla basta dirmi «annulla».", "The user confirmed: 1 photos were moved to the trash."),
    ({"kind": "trash", "count": 0, "missing": 2, "failed": 0}, "Non ho spostato niente. 2 foto non c'erano più.", "The user confirmed: 0 photos were moved to the trash."),
    ({"kind": "copy", "count": 1, "missing": 0, "failed": 0, "folder": "Fiori"},
     "Fatto: 1 foto copiata nella cartella «Fiori».", 'The user confirmed: 1 photos were copied into the folder "Fiori".'),
    ({"kind": "copy", "count": 5, "missing": 0, "failed": 1, "folder": "Fiori"},
     "Fatto: 5 foto copiate nella cartella «Fiori». 1 foto non sono riuscito a toccarla: forse è aperta in un altro programma.",
     'The user confirmed: 5 photos were copied into the folder "Fiori".'),
])
def test_what_a_change_did_in_words(result, text, memory):
    assert orchestrator.done_in_words(result) == (text, memory)


@pytest.mark.parametrize("result, text", [
    ({"undid": "trash", "count": 14, "failed": 0, "folder": ""}, "Annullato: 14 foto di nuovo al loro posto."),
    ({"undid": "trash", "count": 1, "failed": 0, "folder": ""}, "Annullato: 1 foto di nuovo al suo posto."),
    ({"undid": "trash", "count": 0, "failed": 0, "folder": ""}, "Nel cestino quelle foto non ci sono più: non ho potuto rimetterle a posto."),
    ({"undid": "copy", "count": 3, "failed": 0, "folder": "Fiori"}, "Annullato: ho tolto le 3 copie dalla cartella «Fiori». Gli originali sono al loro posto."),
    ({"undid": "trash", "count": 2, "failed": 1, "folder": ""},
     "Annullato: 2 foto di nuovo al loro posto. 1 foto non sono riuscito a spostarla: chiedimelo di nuovo tra poco."),
])
def test_what_taking_a_change_back_did_in_words(result, text):
    assert orchestrator.undone_in_words(result)[0] == text


def test_a_model_that_wants_to_change_pictures_can_only_talk_when_there_is_nothing_to_act_with(monkeypatch):
    seen = script(monkeypatch, [form("trash_photos"), "Non posso cancellare niente."])

    events, _ = ask("eliminale", selection=["p1"])

    assert proposed(events) is None and said(events) == "Non posso cancellare niente."
    assert len(seen) == 2


def test_a_model_is_tried_on_whether_it_decides_the_right_thing(monkeypatch):
    script(monkeypatch, [find("a dog"), ANSWER, ANSWER, find("twelve"), find("")])

    async def tries():
        return [
            await selftest.try_case("m", "trovami le foto con un cane", "find_photos"),   # searched: right
            await selftest.try_case("m", "trovami le foto con un cane", "find_photos"),   # answered instead: wrong
            await selftest.try_case("m", "quanto fa 12 per 12?", "answer"),               # answered: right
            await selftest.try_case("m", "quanto fa 12 per 12?", "answer"),               # searched the photos: wrong
            await selftest.try_case("m", "le foto del mare", "find_photos"),              # a search for nothing: wrong
        ]

    assert asyncio.run(tries()) == [True, False, True, False, False]


def test_a_copy_without_the_name_of_its_folder_is_not_a_right_decision(monkeypatch):
    script(monkeypatch, [form("copy_photos", "the sea", "Estate"), form("copy_photos", "the sea"), form("trash_photos")])

    async def tries():
        return [
            await selftest.try_case("m", "copia le foto del mare in Estate", "copy_photos"),
            await selftest.try_case("m", "copia le foto del mare in Estate", "copy_photos"),
            await selftest.try_case("m", "elimina le foto dei gatti", "trash_photos"),
        ]

    assert asyncio.run(tries()) == [True, False, True]


def test_results_of_a_test_with_other_requests_are_not_used(tmp_path):
    selftest.save(str(tmp_path), {
        "old": {"cases": len(selftest.CASES) - 4, "right": 10, "tokens_per_second": 60.0},
        "new": {"cases": len(selftest.CASES), "right": 13, "tokens_per_second": 60.0},
    })

    assert list(selftest.load(str(tmp_path))) == ["new"]


# ---- the pictures of a phone


@pytest.fixture
def phones(tmp_path):
    """A phone that was let in and has sent the small copies of three pictures."""
    known = Phones(str(tmp_path / "phone"), ColourEmbedder(), ["192.168.1.23"], 8443)
    known.devices.append({"id": "d1", "name": "Pixel", "key": "", "paired": "", "seen": ""})
    known.add("d1", [shot("1", "blue", name="mare.jpg"), shot("2", "blue", name="cielo.jpg"), shot("3", "red", name="rosa.jpg")])
    return known


@pytest.mark.parametrize("request_text, there", [
    ("trovami sul telefono le foto del mare", True),
    ("prendi dal mio cellulare le foto del Giappone", True),
    ("quante foto ho nel telefono?", True),
    ("show me the pictures on my phone", True),
    ("le foto del telefono con un cane", True),
    # a picture that shows a phone is not a picture on the phone
    ("trovami le foto con un telefono", False),
    ("una foto di un telefono rotto", False),
    ("trovami le foto del mare", False),
])
def test_a_request_names_the_phone_as_a_place_or_does_not(request_text, there):
    assert bool(orchestrator.ON_PHONE.search(request_text)) is there


def test_a_search_on_the_phone_looks_at_its_pictures_and_says_so(monkeypatch, phones):
    # the model left the place in the caption: a picture does not show where it is kept
    script(monkeypatch, [find("something green on the phone")])

    events, photos = ask("trovami sul telefono le foto verdi", phones=phones)

    assert photos.asked == []
    assert events[1] == {"type": "step", "tool": "find_photos", "arguments": {"description": "something green", "place": "phone", "period": "", "spot": ""}}
    assert events[2]["place"] == "phone" and events[2]["indexed"] == 3
    assert said(events) == "Non ho trovato niente del genere tra le 3 foto del telefono che conosco."
    assert events[-1]["memory"].startswith('Searched the photos on the phone for "something green"')


def test_what_is_found_on_the_phone_is_said_to_be_there(monkeypatch, phones):
    script(monkeypatch, [find("something blue")])

    events, _ = ask("le foto blu sul telefono", phones=phones)

    assert said(events) == "Ho trovato 2 foto sul telefono."
    assert all(photo["id"].startswith("t") for photo in events[2]["sure"])


def test_the_next_request_stays_on_the_phone_until_the_computer_is_named(monkeypatch, phones):
    on_screen = [photo["id"] for photo in phones.photos if photo["name"] != "rosa.jpg"]

    script(monkeypatch, [find("something red")])
    events, photos = ask("e quelle rosse?", phones=phones, selection=on_screen)
    assert events[2]["place"] == "phone" and photos.asked == []

    script(monkeypatch, [find("something red")])
    events, photos = ask("e quelle rosse sul computer?", phones=phones, selection=on_screen)
    assert events[2]["place"] == "computer" and photos.asked == ["something red"]


def test_without_a_phone_let_in_a_request_about_the_phone_says_how_to_connect_one(monkeypatch, tmp_path):
    script(monkeypatch, [find("the sea")])
    nobody = Phones(str(tmp_path / "phone"), ColourEmbedder(), [], 8443)

    events, photos = ask("trovami sul telefono le foto del mare", phones=nobody)

    assert said(events) == orchestrator.NO_PHONE and photos.asked == []


def test_how_many_pictures_are_on_the_phone_is_counted_there(monkeypatch, phones):
    script(monkeypatch, [COUNT])

    events, _ = ask("quante foto ho sul telefono?", phones=phones)

    assert said(events) == "Conosco 3 foto del telefono."
    assert events[-1]["memory"] == "Counted the photos on the phone: 3."


def test_copying_from_the_phone_is_proposed_as_a_request_to_the_phone(monkeypatch, phones):
    script(monkeypatch, [form("copy_photos", "something blue", "Mare")])
    actions = Changes()

    events, _ = ask("prendi dal telefono le foto blu e salvale nella cartella Mare", phones=phones, actions=actions)

    assert [event["type"] for event in events] == ["start", "step", "text", "proposal", "done"]
    assert proposed(events)["action"] == "fetch" and proposed(events)["folder"] == "Mare"
    assert sorted(photo["name"] for photo in proposed(events)["photos"]) == ["cielo.jpg", "mare.jpg"]
    assert said(events) == "Copio dal telefono al computer queste 2 foto, nella cartella «Mare»? Sul telefono restano dove sono."
    assert 'copy them from the phone to the computer, into the folder "Mare"' in events[-1]["memory"]
    assert actions.done == [] and phones.transfers == []


def test_these_are_pictures_of_the_phone_when_the_ones_on_screen_are(monkeypatch, phones):
    script(monkeypatch, [form("copy_photos", "", "Vacanze")])
    on_screen = [phones.photos[0]["id"]]

    events, _ = ask("copiale nella cartella Vacanze", phones=phones, actions=Changes(), selection=on_screen)

    assert proposed(events) == {"type": "proposal", "action": "fetch", "folder": "Vacanze", "photos": [{"id": on_screen[0], "name": "mare.jpg"}]}


def test_saving_them_on_the_computer_says_where_they_go_not_where_they_are(monkeypatch, phones):
    # the pictures on screen are on the phone; the model repeats what they show, as it often does
    script(monkeypatch, [form("copy_photos", "something blue", "Mare")])
    on_screen = [photo["id"] for photo in phones.photos if photo["name"] != "rosa.jpg"]

    events, photos = ask("salvale sul computer in una cartella Mare", phones=phones, actions=Changes(), selection=on_screen)

    assert photos.asked == []
    assert proposed(events)["action"] == "fetch" and sorted(photo["id"] for photo in proposed(events)["photos"]) == sorted(on_screen)


def test_throwing_away_pictures_of_the_phone_is_proposed_as_a_copy_here_and_then_its_trash(monkeypatch, phones):
    script(monkeypatch, [form("trash_photos", "something blue")])

    events, _ = ask("elimina dal telefono le foto blu", phones=phones, actions=Changes())

    plan = proposed(events)
    assert (plan["action"], plan["folder"]) == ("clear", "Tolte dal telefono")
    assert sorted(photo["name"] for photo in plan["photos"]) == ["cielo.jpg", "mare.jpg"]
    assert said(events) == (
        "Tolgo dal telefono queste 2 foto? Prima le copio sul computer, nella cartella «Tolte dal telefono», e controllo che siano arrivate intere. "
        "Poi il telefono le sposta nel suo cestino, dove restano 30 giorni: te lo chiederà Android."
    )
    assert events[-1]["memory"].endswith("and then move them to the trash of the phone (2 photos). Nothing was done: the user must confirm.")


def test_the_ones_on_screen_are_taken_off_the_phone_when_they_are_its_pictures(monkeypatch, phones):
    script(monkeypatch, [form("trash_photos", "")])
    on_screen = [phones.photos[0]["id"]]

    events, _ = ask("eliminale", phones=phones, actions=Changes(), selection=on_screen)

    assert proposed(events) == {"type": "proposal", "action": "clear", "folder": "Tolte dal telefono", "photos": [{"id": on_screen[0], "name": "mare.jpg"}]}


def test_what_taking_pictures_off_a_phone_becomes_in_words():
    assert orchestrator.asked_in_words(2, "Tolte dal telefono", clear=True)[0] == (
        "Ho chiesto al telefono 2 foto. Quando sono al sicuro sul computer, il telefono ti chiede di spostarle nel suo cestino. Tieni Regista aperto sul telefono."
    )
    assert orchestrator.confirming_in_words(2, "Tolte dal telefono") == (
        "Le 2 foto sono al sicuro sul computer, nella cartella «Tolte dal telefono». Ora rispondi sul telefono alla domanda di Android, che le sposta nel suo cestino."
    )
    said = lambda *numbers: orchestrator.cleared_in_words(*numbers, "Tolte dal telefono")[0]  # noqa: E731
    assert said(2, 2, 0, "") == "Fatto: 2 foto tolte dal telefono. Restano 30 giorni nel suo cestino, e una copia è sul computer nella cartella «Tolte dal telefono»."
    assert said(1, 1, 1, "") == (
        "Fatto: 1 foto tolta dal telefono. Resta 30 giorni nel suo cestino, e una copia è sul computer nella cartella «Tolte dal telefono». "
        "1 foto il telefono non è riuscito a mandarla: non la ho toccata."
    )
    assert said(2, 0, 0, "declined") == "Sul telefono hai detto di no: le foto sono rimaste dov'erano. La copia è sul computer, nella cartella «Tolte dal telefono»."
    assert said(2, 0, 0, "old").startswith("Questo telefono non ha un cestino che io possa usare (serve Android 11 o più recente): le foto sono rimaste dov'erano.")
    assert said(0, 0, 2, "") == "Dal telefono non è arrivata nessuna foto, quindi non ne ho tolta nessuna. 2 foto il telefono non è riuscito a mandarle: non le ho toccate."
    # taking back the arrival of pictures that then left their phone is said for what it is
    entry = {"kind": "receive", "files": [1, 2], "folder": "Tolte dal telefono", "cleared": 2}
    assert orchestrator.undo_proposed_in_words(entry) == (
        "L'ultima modifica è stata togliere 2 foto dal telefono, dopo averle copiate nella cartella «Tolte dal telefono». "
        "Sul telefono le riprendi dal cestino della galleria, finché ci restano. Da qui posso solo togliere dal computer quelle copie: lo faccio?"
    )
    undone = {"undid": "receive", "count": 2, "folder": "Tolte dal telefono", "cleared": 2}
    assert orchestrator.undone_in_words(undone)[0] == (
        "Annullato: ho tolto le 2 copie dalla cartella «Tolte dal telefono». Sul telefono le trovi nel cestino della galleria, finché ci restano."
    )


def test_what_a_request_to_the_phone_becomes_in_words():
    assert orchestrator.asked_in_words(12, "Mare")[0] == "Ho chiesto al telefono 12 foto. Arrivano quando Regista è aperto sul telefono."
    assert orchestrator.received_in_words(12, 0, "Mare")[0] == "Fatto: 12 foto arrivate dal telefono, nella cartella «Mare»."
    assert orchestrator.received_in_words(1, 2, "Mare")[0] == "Fatto: 1 foto arrivata dal telefono, nella cartella «Mare». 2 foto il telefono non è riuscito a mandarle."
    assert orchestrator.received_in_words(0, 1, "Mare")[0] == "Dal telefono non è arrivata nessuna foto. 1 foto il telefono non è riuscito a mandarla."
    arrived = {"id": "x", "kind": "receive", "folder": "Mare", "files": [{}] * 3}
    assert orchestrator.undo_proposed_in_words(arrived) == "L'ultima modifica è stata copiare 3 foto dal telefono nella cartella «Mare». Tolgo quelle copie? Sul telefono le foto restano."
    taken_back = {"undid": "receive", "count": 3, "failed": 0, "folder": "Mare"}
    assert orchestrator.undone_in_words(taken_back)[0] == "Annullato: ho tolto le 3 copie dalla cartella «Mare». Sul telefono le foto ci sono ancora."
