"""A request that names neither the computer nor the phone: the pictures of both, each still where it is."""
import asyncio

import orchestrator
from fakes import ColourEmbedder, shot
from phone import Phones
from test_looking import EYES, TESTS, eyes_that_see, library
from test_orchestrator import GRANITE, LAPTOP, Changes, said, script


def phone_with_pictures(tmp_path):
    phones = Phones(str(tmp_path / "phone"), ColourEmbedder(), ["192.168.1.23"], 8443)
    phones.devices.append({"id": "d1", "name": "Pixel", "key": "", "paired": "", "seen": "", "android": 33})
    phones.add("d1", [shot("1", "red", name="IMG_1.jpg", day="2026-09-01"), shot("2", "blue", name="IMG_2.jpg", day="2026-09-02")])
    return phones


def ask(text, index, phones, models=(GRANITE,), tests=None, selection=(), actions=None):
    async def collect():
        history = [{"role": "user", "content": text}]
        return [event async for event in orchestrator.reply(history, "auto", list(models), LAPTOP, tests or {}, index, actions, list(selection), phones)]

    return asyncio.run(collect())


def test_a_search_that_names_no_place_finds_the_pictures_of_the_computer_and_of_the_phone(tmp_path, monkeypatch):
    index, phones = library(tmp_path), phone_with_pictures(tmp_path)
    script(monkeypatch, ['{"action": "find_photos", "caption": "something red", "folder": ""}'])

    events = ask("le foto rosse", index, phones)

    found = next(event for event in events if event["type"] == "photos")
    assert found["place"] == "both"
    names = [photo["name"] for photo in found["sure"]]
    # the newest first: the phone's of September, then the computer's of August
    assert names[0] == "IMG_1.jpg" and sorted(names[1:]) == ["red_0.jpg", "red_2.jpg", "red_3.jpg", "red_5.jpg"]
    assert found["sure"][0]["place"] == "phone" and "place" not in found["sure"][1]
    assert said(events) == "Ho trovato 5 foto. Una è sul telefono."
    assert events[-1]["memory"].startswith('Searched the photos on the computer and the phone for "something red"')


def test_looked_at_one_by_one_the_pictures_of_both_say_where_they_are(tmp_path, monkeypatch):
    index, phones = library(tmp_path), phone_with_pictures(tmp_path)
    orchestrator._seen.clear()
    eyes_that_see(monkeypatch, index)
    # the phone's small copies end with their names too, as the computer's do (eyes_that_see): the eyes read them there
    names = {photo["id"]: photo["name"] for photo in phones.photos}
    real = phones.thumbnail
    monkeypatch.setattr(phones, "thumbnail", lambda identifier: real(identifier) + names[identifier].encode())

    async def sees_many(model, pictures, what, english=True):
        ends = [data.decode("latin-1")[-12:] for data in pictures]
        return [end.endswith("IMG_1.jpg") or "red_" in end for end in ends]

    monkeypatch.setattr(orchestrator.llm, "sees_many", sees_many)
    script(monkeypatch, ['{"action": "find_photos", "caption": "something red", "folder": ""}'])

    events = ask("le foto rosse", index, phones, models=(EYES,), tests=TESTS)

    confirmed = [event["photo"] for event in events if event["type"] == "photo"]
    assert {photo["name"]: photo.get("place", "computer") for photo in confirmed} == {
        "IMG_1.jpg": "phone", "red_0.jpg": "computer", "red_2.jpg": "computer", "red_3.jpg": "computer", "red_5.jpg": "computer"}
    assert said(events) == "Ho trovato 5 foto: le ho guardate una per una, dalla più recente. Una è sul telefono."


def test_how_many_pictures_counts_both(tmp_path, monkeypatch):
    index, phones = library(tmp_path), phone_with_pictures(tmp_path)
    script(monkeypatch, ['{"action": "count_photos", "caption": "", "folder": ""}'])

    assert said(ask("quante foto ho?", index, phones)) == "Conosco 6 foto sul computer e 2 foto sul telefono."


def test_the_pictures_of_the_phone_on_screen_are_not_touched_by_a_change_meant_for_the_computer(tmp_path, monkeypatch):
    index, phones = library(tmp_path), phone_with_pictures(tmp_path)
    script(monkeypatch, ['{"action": "trash_photos", "caption": "", "folder": ""}'])
    on_screen = [index.photos[0]["id"], phones.photos[0]["id"]]

    events = ask("eliminale", index, phones, selection=on_screen, actions=Changes())

    proposal = next(event for event in events if event["type"] == "proposal")
    assert [photo["id"] for photo in proposal["photos"]] == [index.photos[0]["id"]]
    assert said(events).startswith("1 foto del telefono non la tocco da qui: per quella dimmelo con «dal telefono». Sposto nel cestino questa foto?")
