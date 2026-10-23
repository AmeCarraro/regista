"""A search whose pictures are looked at one by one by a model that sees, sent as they are confirmed, the newest first."""
import asyncio
import datetime

import numpy as np

import llm
import orchestrator
from catalog import director_and_eyes
from fakes import ColourEmbedder, picture
from photos import PhotoIndex, closest, day_in_name, day_of, to_look_at
from test_orchestrator import LAPTOP, script, said

EYES = {"name": "qwen3.5:4b", "bytes": 3.3e9, "parameters": "4.7B", "capabilities": ["completion", "tools", "vision"], "loaded": True, "gpu_share": 0.5}
TEXT_ONLY = {"name": "qwen3.5-testo:4b", "bytes": 2.6e9, "parameters": "4.7B", "capabilities": ["completion", "tools"], "loaded": False, "gpu_share": None}
TESTS = {"qwen3.5:4b": {"right": 17, "cases": 17, "tokens_per_second": 21.6}, "qwen3.5-testo:4b": {"right": 17, "cases": 17, "tokens_per_second": 30.1}}


def test_a_day_is_read_from_the_name_when_the_picture_does_not_say_it(tmp_path):
    assert day_in_name("IMG_20230812_142530.jpg") == "2023-08-12"
    assert day_in_name("IMG-20230812-WA0003.jpg") == "2023-08-12"
    assert day_in_name("WhatsApp Image 2023-08-12 at 14.25.30.jpeg") == "2023-08-12"
    assert day_in_name("Screenshot_20230702-104906.png") == "2023-07-02"
    # not a day: too many figures, a month that is not one, the future, or none at all
    for name in ("IMG_120230812.jpg", "IMG_20231312.jpg", "IMG_20991231.jpg", "vacanze.jpg"):
        assert day_in_name(name) == "", name
    # a picture received in a chat keeps its day in the name, not in its notes, and its file is from today
    picture(tmp_path, "IMG-20230812-WA0003.jpg", "red")
    assert day_of(tmp_path / "IMG-20230812-WA0003.jpg") == "2023-08-12"
    picture(tmp_path, "IMG-20230812-WA0004.jpg", "red", day="2024-01-02")
    assert day_of(tmp_path / "IMG-20230812-WA0004.jpg") == "2024-01-02"


def test_the_pictures_found_are_shown_the_newest_first():
    vectors = np.array([[1, 0, 0], [0.99, 0.14, 0], [0.98, 0.2, 0], [0, 1, 0]], dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    entries = [{"id": "a", "name": "a.jpg", "day": "2024-01-01"}, {"id": "b", "name": "b.jpg", "day": "2026-05-03"},
               {"id": "c", "name": "c.jpg", "day": ""}, {"id": "d", "name": "d.jpg", "day": "2026-06-01"}]

    found = closest(vectors, np.array([1, 0, 0], dtype=np.float32), entries, 10)

    # the closest are chosen, and shown by day: the newest first, a picture with no day at the end
    assert [photo["id"] for photo in found["sure"]] == ["b", "a", "c"]
    assert found["sure"][0]["day"] == "2026-05-03"


def test_the_pictures_to_look_at_are_the_likeliest_first_within_the_period():
    vectors = np.array([[0.2, 1, 0], [1, 0, 0], [0.6, 0.8, 0], [0, 0, 1]], dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    entries = [{"id": str(n), "name": f"{n}.jpg", "day": f"2026-0{n + 1}-01"} for n in range(4)]
    red = np.array([1, 0, 0], dtype=np.float32)

    assert [one["id"] for one in to_look_at(vectors, red, entries)] == ["1", "2", "0", "3"]
    assert [one["id"] for one in to_look_at(vectors, red, entries, (datetime.date(2026, 1, 1), datetime.date(2026, 3, 31)))] == ["1", "2", "0"]
    assert to_look_at(vectors, red, entries, most=2)[1] == {"id": "2", "name": "2.jpg", "day": "2026-03-01", "score": 0.6}


def test_one_model_directs_and_looks_when_it_directs_as_well():
    assert director_and_eyes([EYES, TEXT_ONLY], LAPTOP, TESTS) == ("qwen3.5:4b", "qwen3.5:4b")
    worse = {**TESTS, "qwen3.5:4b": {"right": 12, "cases": 17, "tokens_per_second": 21.6}}
    assert director_and_eyes([EYES, TEXT_ONLY], LAPTOP, worse) == ("qwen3.5-testo:4b", "qwen3.5:4b")
    assert director_and_eyes([TEXT_ONLY], LAPTOP, TESTS) == ("qwen3.5-testo:4b", None)


def library(tmp_path):
    """Red pictures and blue ones, a day apart: the red ones are what is asked for."""
    folder = tmp_path / "foto"
    for number, colour in enumerate(["red", "blue", "red", "red", "blue", "red"]):
        picture(folder, f"{colour}_{number}.jpg", colour, day=f"2026-08-{10 + number:02d}")
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()
    return index


def eyes_that_see(monkeypatch, index, red_but_wrong=()):
    """In place of the model that sees: yes to the red pictures, except the ones named."""
    asked = []
    names = {photo["id"]: photo["path"] for photo in index.photos}
    by_bytes = {}

    real = index.thumbnail

    def thumbnail(identifier):
        data = real(identifier)
        by_bytes[data] = names[identifier]
        return data

    async def sees(model, data, question):
        asked.append((model, by_bytes[data], question))
        name = by_bytes[data]
        return name.startswith("red") and name not in red_but_wrong

    monkeypatch.setattr(index, "thumbnail", thumbnail)
    monkeypatch.setattr(llm, "sees", sees)
    return asked


def ask(text, index, actions=None):
    async def collect():
        return [event async for event in orchestrator.reply([{"role": "user", "content": text}], "auto", [EYES], LAPTOP, TESTS, index, actions, [], None)]

    return asyncio.run(collect())


def test_the_pictures_are_looked_at_one_by_one_and_sent_as_they_are_confirmed(tmp_path, monkeypatch):
    index = library(tmp_path)
    orchestrator._seen.clear()
    asked = eyes_that_see(monkeypatch, index, red_but_wrong=("red_3.jpg",))
    script(monkeypatch, ['{"action": "find_photos", "caption": "something red", "folder": ""}'])

    events = ask("trovami le foto rosse", index)

    kinds = [event["type"] for event in events]
    assert kinds[:3] == ["start", "step", "photos"] and kinds[-2:] == ["text", "done"]
    assert events[2]["sure"] == [] and events[2]["checking"] == 6
    confirmed = [event["photo"]["name"] for event in events if event["type"] == "photo"]
    # the red ones the eyes said yes to; the one they did not, left out
    assert sorted(confirmed) == ["red_0.jpg", "red_2.jpg", "red_5.jpg"]
    assert all(question == "Does this photo show something red? Answer only yes or no." and model == "qwen3.5:4b" for model, _, question in asked)
    # each picture sent as soon as it was confirmed, between the steps of the looking
    assert kinds.index("photo") < max(index for index, kind in enumerate(kinds) if kind == "looked")
    assert events[-3] == {"type": "looked", "looked": 6, "of": 6}
    assert said(events) == "Ho trovato 3 foto: le ho guardate una per una, dalla più recente."
    assert events[-1]["memory"] == 'Searched the photos for "something red": looked at 6 one by one, 3 show it.'
    assert events[-1]["model"] == "qwen3.5:4b"

    # asked again, nothing is looked at twice
    asked.clear()
    script(monkeypatch, ['{"action": "find_photos", "caption": "something red", "folder": ""}'])
    assert len([event for event in ask("trovami le foto rosse", index) if event["type"] == "photo"]) == 3
    assert asked == []


def test_the_looking_stops_after_many_wrong_in_a_row(tmp_path, monkeypatch):
    folder = tmp_path / "foto"
    for number in range(30):
        picture(folder, f"red_{number:02d}.jpg", "red", day="2026-08-01")
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()
    orchestrator._seen.clear()
    # the eyes say no to all of them
    eyes_that_see(monkeypatch, index, red_but_wrong=tuple(f"red_{number:02d}.jpg" for number in range(30)))
    script(monkeypatch, ['{"action": "find_photos", "caption": "something red", "folder": ""}'])

    events = ask("trovami le foto rosse", index)

    assert [event for event in events if event["type"] == "looked"][-1] == {"type": "looked", "looked": orchestrator.LOOK_STOP, "of": orchestrator.LOOK_STOP}
    assert said(events) == f"Ne ho guardate {orchestrator.LOOK_STOP} una per una: nessuna mostra quello che hai chiesto."


def test_without_a_model_that_sees_the_search_is_as_before_the_newest_first(tmp_path, monkeypatch):
    index = library(tmp_path)
    script(monkeypatch, ['{"action": "find_photos", "caption": "something red", "folder": ""}'])

    async def collect():
        return [event async for event in orchestrator.reply([{"role": "user", "content": "trovami le foto rosse"}], "auto", [TEXT_ONLY], LAPTOP, TESTS, index, None, [], None)]

    events = asyncio.run(collect())

    photos = next(event for event in events if event["type"] == "photos")
    assert [photo["name"] for photo in photos["sure"]] == ["red_5.jpg", "red_3.jpg", "red_2.jpg", "red_0.jpg"]
    assert "photo" not in [event["type"] for event in events]


def test_what_the_pictures_should_show_is_read_in_the_users_own_words():
    from understand import own_words

    assert own_words("trovami una motosega") == "motosega"
    assert own_words("le foto di un mangianastri") == "mangianastri"
    assert own_words("i camion della spazzatura") == "camion della spazzatura"
    # the period and the place are read apart, and come out
    assert own_words("le foto della pizza da gennaio a marzo 2025") == "pizza"
    assert own_words("le foto dell'estate scorsa al mare") == "mare"
    assert own_words("foto di cani che giocano sulla spiaggia a Parigi nel 2023", "Parigi") == "cani che giocano sulla spiaggia"
    assert own_words("mostrami le foto in cui c'è una torta") == "torta"
    assert own_words("trovami sul telefono le foto del lago") == "lago"
    # a request only about a period says nothing of what the pictures show
    assert own_words("le foto da gennaio a marzo") == ""


def test_a_request_that_plainly_asks_for_pictures_is_a_search_even_when_the_model_answers(tmp_path, monkeypatch):
    index = library(tmp_path)
    orchestrator._seen.clear()
    asked = eyes_that_see(monkeypatch, index)
    # the model took it for a question
    script(monkeypatch, ['{"action": "answer", "caption": "", "folder": ""}'])

    events = ask("trovami le foto rosse", index)

    assert sorted(event["photo"]["name"] for event in events if event["type"] == "photo") == ["red_0.jpg", "red_2.jpg", "red_3.jpg", "red_5.jpg"]
    # looked for in the user's own words, as nothing else was given, and asked in them
    assert events[1]["arguments"]["description"] == "rosse"
    assert asked and all(question == "Questa foto mostra: rosse? Rispondi solo sì o no." for _, _, question in asked)


def test_when_the_most_pictures_were_looked_at_the_answer_says_there_may_be_more(tmp_path, monkeypatch):
    index = library(tmp_path)
    orchestrator._seen.clear()
    eyes_that_see(monkeypatch, index)
    monkeypatch.setattr(orchestrator, "LOOK_MOST", 6)
    script(monkeypatch, ['{"action": "find_photos", "caption": "something red", "folder": ""}'])

    events = ask("trovami le foto rosse", index)

    assert said(events) == "Ho trovato 4 foto: le ho guardate una per una, dalla più recente. Mi sono fermato prima di guardarle tutte: potrebbero essercene altre."


def test_a_question_on_how_to_find_pictures_is_still_answered(monkeypatch):
    import test_orchestrator

    script(monkeypatch, ['{"action": "answer", "caption": "", "folder": ""}', "Scrivimi cosa cerchi."])

    events, photos = test_orchestrator.ask("mostrami come si cercano le foto")

    assert photos.asked == [] and said(events) == "Scrivimi cosa cerchi."


def test_all_the_pictures_of_a_period_are_shown_not_the_first_few(tmp_path, monkeypatch):
    folder = tmp_path / "foto"
    for number in range(80):
        picture(folder, f"p_{number:02d}.jpg", "red", day=f"2026-0{1 + number % 3}-{1 + number % 28:02d}")
    picture(folder, "late.jpg", "red", day="2026-05-01")
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()
    script(monkeypatch, ['{"action": "find_photos", "caption": "", "folder": ""}'])

    events = ask("le foto da gennaio a marzo 2026", index)

    photos = next(event for event in events if event["type"] == "photos")
    # all of them, the newest first; the one of May is not of the period
    assert len(photos["sure"]) == photos["matching"] == 80
    days = [photo["day"] for photo in photos["sure"]]
    assert days == sorted(days, reverse=True) and days[-1] == "2026-01-01" and "late.jpg" not in [photo["name"] for photo in photos["sure"]]
    assert said(events) == "Ho trovato 80 foto da gennaio a marzo 2026."


def test_a_request_is_read_as_one_for_pictures_only_when_it_names_them():
    for asked in ("trovami le foto con una motosega", "le foto di un mangianastri", "mostrami le immagini del mare", "fammi vedere le foto di ieri",
                  "foto di cani", "le mie foto del 2023", "cercami delle fotografie con la neve"):
        assert orchestrator.FIND.search(asked) and not orchestrator.HOW.search(asked), asked
    for asked in ("mostrami un esempio di codice Python", "trovami una ricetta per la torta", "le foto sono bellissime, grazie", "che belle foto"):
        assert not orchestrator.FIND.search(asked), asked
    assert orchestrator.HOW.search("mostrami come si cercano le foto")


def test_one_model_also_answers_in_words_when_it_is_as_large_so_that_nothing_is_loaded_again():
    from catalog import describe, writer

    # the copy without eyes writes faster, but the model that directs and looks is as large: it answers too
    assert writer([EYES, TEXT_ONLY], LAPTOP, TESTS, "auto", "qwen3.5:4b") == "qwen3.5:4b"
    # a model the user chose is the one that answers
    assert writer([EYES, TEXT_ONLY], LAPTOP, TESTS, "qwen3.5-testo:4b", "qwen3.5:4b") == "qwen3.5-testo:4b"
    # a larger model writes better: it answers, though it has to be loaded
    larger = {**TEXT_ONLY, "name": "larger:8b", "parameters": "8.0B", "bytes": 3.0e9}
    assert writer([EYES, TEXT_ONLY, larger], LAPTOP, TESTS, "auto", "qwen3.5:4b") == "larger:8b"
    # and the page is told what "automatic" really uses
    order = describe([EYES, TEXT_ONLY], LAPTOP, TESTS)["order"]
    assert order["tools"][0] == order["chat"][0] == order["vision"][0] == "qwen3.5:4b"


def test_pictures_to_throw_away_are_looked_at_one_by_one_and_only_the_confirmed_ones_are_proposed(tmp_path, monkeypatch):
    from test_orchestrator import Changes

    index = library(tmp_path)
    orchestrator._seen.clear()
    eyes_that_see(monkeypatch, index, red_but_wrong=("red_3.jpg",))
    script(monkeypatch, ['{"action": "trash_photos", "caption": "something red", "folder": ""}'])
    changes = Changes()

    events = ask("elimina le foto rosse", index, changes)

    kinds = [event["type"] for event in events]
    # how far the looking is, and then the proposal: the pictures are shown once, in it
    assert kinds[:3] == ["start", "step", "photos"] and "looked" in kinds and "photo" not in kinds
    proposal = next(event for event in events if event["type"] == "proposal")
    assert proposal["action"] == "trash" and sorted(photo["name"] for photo in proposal["photos"]) == ["red_0.jpg", "red_2.jpg", "red_5.jpg"]
    assert said(events) == "Sposto nel cestino queste 3 foto? Restano sul disco, e le riporto dov'erano quando vuoi."
    assert events[-1]["memory"] == 'Searched the photos for "something red": 3 found. Proposed to move them to the trash (3 photos). Nothing was done: the user must confirm.'
    assert changes.done == []

    # when the eyes confirm none, nothing is proposed
    orchestrator._seen.clear()
    eyes_that_see(monkeypatch, index, red_but_wrong=("red_0.jpg", "red_2.jpg", "red_3.jpg", "red_5.jpg"))
    script(monkeypatch, ['{"action": "trash_photos", "caption": "something red", "folder": ""}'])
    events = ask("elimina le foto rosse", index, Changes())
    assert said(events) == orchestrator.NONE_LIKE_THAT and "proposal" not in [event["type"] for event in events]


def test_a_request_typed_on_the_phone_is_looked_at_one_by_one_too(tmp_path, monkeypatch):
    import io

    from PIL import Image

    from fakes import shot
    from phone import Phones

    phones = Phones(str(tmp_path / "phone"), ColourEmbedder(), ["192.168.1.23"], 8443)
    phones.devices.append({"id": "d1", "name": "Pixel", "key": "", "paired": "", "seen": ""})
    phones.add("d1", [shot("1", "red", name="a.jpg", day="2026-08-01"), shot("2", "red", name="b.jpg", day="2026-08-20"), shot("3", "blue", name="c.jpg")])
    orchestrator._seen.clear()
    asked = []

    async def sees(model, data, question):
        asked.append(question)
        red, green, _ = Image.open(io.BytesIO(data)).convert("RGB").getpixel((0, 0))
        return red > 150 and green < 100

    monkeypatch.setattr(llm, "sees", sees)
    script(monkeypatch, ['{"action": "find_photos", "caption": "something red", "folder": ""}'])

    found = asyncio.run(orchestrator.on_the_phone("le foto rosse", "d1", phones, None, [EYES], LAPTOP, TESTS))

    # the red ones, the newest first, named as the phone names them; nothing left to doubt
    assert found["sure"] == ["2", "1"] and found["maybe"] == []
    assert found["words"] == "Ho trovato 2 foto: le ho guardate una per una, dalla più recente."
    assert found["model"] == "qwen3.5:4b" and asked
