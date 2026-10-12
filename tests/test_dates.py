"""Pictures found by when they were taken: on the computer, on a phone, and from a request in words."""
import asyncio
import datetime
import os

import pytest

import orchestrator
import period
from fakes import ColourEmbedder, picture, shot
from phone import Phones
from photos import PhotoIndex, day_of
from test_orchestrator import Changes, form, proposed, said, script

MAY_TO_JULY = (datetime.date(2024, 5, 20), datetime.date(2024, 7, 20))


@pytest.fixture
def library(tmp_path):
    """Four pictures of the computer, taken on four days of 2024."""
    folder = tmp_path / "foto"
    picture(folder, "rose.jpg", "red", day="2024-05-19")
    picture(folder, "sea.jpg", "blue", day="2024-05-20")
    picture(folder, "sky.jpg", "blue", day="2024-07-20")
    picture(folder, "meadow.jpg", "green", day="2024-12-25")
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()
    return index, folder


def names(result):
    return [photo["name"] for photo in result["sure"]]


def test_the_day_of_a_picture_is_the_one_the_camera_wrote_or_else_the_one_of_the_file(tmp_path):
    picture(tmp_path, "dated.jpg", "red", day="2023-02-03")
    picture(tmp_path, "plain.jpg", "red")
    an_evening = datetime.datetime(2022, 6, 30, 18, 0).timestamp()
    os.utime(tmp_path / "plain.jpg", (an_evening, an_evening))

    assert day_of(tmp_path / "dated.jpg") == "2023-02-03"
    assert day_of(tmp_path / "plain.jpg") == "2022-06-30"


def test_a_period_keeps_only_the_pictures_taken_in_it_first_and_last_day_included(library):
    index, _ = library

    # no description: every picture of those days, the newest first
    assert names(index.search("", period=MAY_TO_JULY)) == ["sky.jpg", "sea.jpg"]
    assert index.search("", period=MAY_TO_JULY)["matching"] == 2 and index.search("", period=MAY_TO_JULY)["indexed"] == 4
    # with a description: what it shows, among the pictures of those days
    assert names(index.search("something blue", period=(datetime.date(2024, 7, 1), datetime.date(2024, 12, 31)))) == ["sky.jpg"]
    assert names(index.search("something red", period=MAY_TO_JULY)) == []
    assert names(index.search("", limit=1, period=(datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)))) == ["meadow.jpg"]


def test_pictures_read_before_days_were_kept_get_their_day_without_being_read_again(library, tmp_path):
    index, folder = library
    for photo in index.photos:
        del photo["day"]
    index._save()
    embedder = ColourEmbedder()
    again = PhotoIndex(str(folder), str(tmp_path / "index"), embedder)

    again.build()

    assert embedder.pictures_read == 0
    assert names(again.search("", period=MAY_TO_JULY)) == ["sky.jpg", "sea.jpg"]


@pytest.fixture
def phones(tmp_path):
    known = Phones(str(tmp_path / "phone"), ColourEmbedder(), ["192.168.1.23"], 8443)
    known.devices.append({"id": "d1", "name": "Pixel", "key": "", "paired": "", "seen": ""})
    known.add("d1", [shot("1", "blue", name="mare.jpg", day="2024-06-01"), shot("2", "blue", name="cielo.jpg", day="2024-08-15"), shot("3", "red", name="rosa.jpg", day="2024-06-02")])
    return known


def test_the_pictures_of_a_phone_are_found_by_their_day_too(phones):
    assert sorted(names(phones.search("", period=MAY_TO_JULY))) == ["mare.jpg", "rosa.jpg"]
    assert names(phones.search("something blue", period=MAY_TO_JULY)) == ["mare.jpg"]


def test_a_picture_whose_day_the_phone_did_not_say_is_asked_for_again(phones):
    listing = [{"id": "1", "stamp": "1"}, {"id": "2", "stamp": "1"}, {"id": "3", "stamp": "1"}]
    assert phones.wanted("d1", listing) == []
    # as an older app sent it: without the day, or with something that is not one
    phones.add("d1", [{**shot("2", "blue"), "day": ""}, {**shot("3", "red"), "day": "15/08/2024"}])

    assert phones.wanted("d1", listing) == ["2", "3"]
    assert [photo["name"] for photo in phones.search("", period=(datetime.date(2000, 1, 1), datetime.date(2100, 1, 1)))["sure"]] == ["mare.jpg"]


# ---- from a request in words. The fixed day is the one the period is worked out from.


def ask(text, index, monkeypatch, phones=None, actions=None, selection=()):
    monkeypatch.setattr(orchestrator, "read_period", lambda asked: period.read(asked, datetime.date(2026, 10, 12)))
    models = [{"name": "granite4.1:3b", "bytes": 2.1e9, "parameters": "3.4B", "capabilities": ["completion", "tools"], "loaded": True, "gpu_share": 1.0}]
    machine = orchestrator.catalog.Hardware(gpu="RTX 3050 Ti", gpu_gb=4.0, ram_gb=16.0, cores=14)

    async def collect():
        return [event async for event in orchestrator.reply([{"role": "user", "content": text}], "auto", models, machine, {}, index, actions, list(selection), phones)]

    return asyncio.run(collect())


def test_a_request_that_only_says_when_finds_every_picture_of_those_days(library, monkeypatch):
    index, _ = library
    # the model left the period in the caption: a picture does not show its date
    script(monkeypatch, [form("find_photos", "photos from May 20 to July 20, 2024")])

    events = ask("trovami le foto dal 20 maggio al 20 luglio 2024", index, monkeypatch)

    assert events[1] == {"type": "step", "tool": "find_photos", "arguments": {"description": "", "place": "computer", "period": "dal 20 maggio al 20 luglio 2024"}}
    assert names(events[2]) == ["sky.jpg", "sea.jpg"]
    assert said(events) == "Ho trovato 2 foto dal 20 maggio al 20 luglio 2024."
    assert events[-1]["memory"] == "Searched the photos taken from 2024-05-20 to 2024-07-20: 2 found, 0 uncertain."


def test_what_the_pictures_show_and_when_they_were_taken_work_together(library, monkeypatch):
    index, _ = library
    script(monkeypatch, [form("find_photos", "something blue in May 2024")])

    events = ask("le foto blu di maggio 2024", index, monkeypatch)

    assert events[1]["arguments"] == {"description": "something blue", "place": "computer", "period": "di maggio 2024"}
    assert names(events[2]) == ["sea.jpg"] and said(events) == "Ho trovato 1 foto di maggio 2024."
    assert events[-1]["memory"].startswith('Searched the photos for "something blue" taken from 2024-05-01 to 2024-05-31')


def test_a_period_with_no_pictures_says_so(library, monkeypatch):
    index, _ = library
    script(monkeypatch, [form("find_photos", "")])

    events = ask("le foto del 2019", index, monkeypatch)

    assert said(events) == "Non ho trovato foto del 2019 tra le 4 foto che conosco."


def test_a_month_with_no_year_is_the_last_one_that_has_been(library, monkeypatch):
    index, _ = library
    script(monkeypatch, [form("find_photos", "")])

    events = ask("le foto di dicembre", index, monkeypatch)

    # asked in October 2026: the last December was in 2025
    assert events[1]["arguments"]["period"] == "di dicembre 2025"


def test_how_many_pictures_of_a_period_is_counted(library, monkeypatch):
    index, _ = library
    script(monkeypatch, [form("count_photos")])

    events = ask("quante foto ho del 2024?", index, monkeypatch)

    assert said(events) == "Conosco 4 foto del 2024."
    assert events[-1]["memory"] == "Counted the photos taken from 2024-01-01 to 2024-12-31: 4."


def test_the_pictures_of_a_period_can_be_proposed_for_a_copy(library, monkeypatch):
    index, _ = library
    script(monkeypatch, [form("copy_photos", "", "Estate")])

    events = ask("copia le foto dal 20 maggio al 20 luglio 2024 in una cartella Estate", index, monkeypatch, actions=Changes(), selection=["not these"])

    assert sorted(photo["name"] for photo in proposed(events)["photos"]) == ["sea.jpg", "sky.jpg"]
    assert events[1]["arguments"] == {"description": "", "place": "computer", "period": "dal 20 maggio al 20 luglio 2024"}
    assert events[-1]["memory"].startswith("Searched the photos taken from 2024-05-20 to 2024-07-20: 2 found. Proposed to copy them")


def test_the_pictures_of_a_period_on_the_phone(library, phones, monkeypatch):
    index, _ = library
    script(monkeypatch, [form("copy_photos", "", "Giugno")])

    events = ask("prendi dal telefono le foto di giugno 2024 e salvale in una cartella Giugno", index, monkeypatch, phones=phones, actions=Changes())

    assert proposed(events)["action"] == "fetch" and sorted(photo["name"] for photo in proposed(events)["photos"]) == ["mare.jpg", "rosa.jpg"]
    assert said(events) == "Copio dal telefono al computer queste 2 foto, nella cartella «Giugno»? Sul telefono restano dove sono."
