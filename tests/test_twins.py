"""Copies of the same picture: found by what they show and by how they look in pixels together, the best copy kept."""
import asyncio
import datetime
import random

import pytest
from PIL import Image, ImageDraw

import orchestrator
from fakes import ColourEmbedder, shot
from phone import Phones
from photos import TWIN_BITS, PhotoIndex, look_of
from test_orchestrator import GRANITE, LAPTOP, Changes, proposed, said


def drawn(seed, size=(320, 240)):
    """A picture of blocks in shades of red: all alike in colour, each different in its shapes."""
    rng = random.Random(seed)
    image = Image.new("RGB", size, (200, 60, 60))
    draw = ImageDraw.Draw(image)
    for _ in range(12):
        x, y = rng.randrange(size[0]), rng.randrange(size[1])
        shade = rng.randrange(80, 255)
        draw.rectangle((x, y, x + rng.randrange(20, 160), y + rng.randrange(20, 120)), fill=(shade, 50, 50))
    return image


def apart(one, other):
    return bin(int(one, 16) ^ int(other, 16)).count("1")


def test_a_copy_looks_the_same_in_pixels_and_another_picture_does_not():
    original = drawn(1)

    for copy in (original.resize((160, 120)), original.point(lambda value: min(255, int(value * 1.2))), original.convert("L").convert("RGB")):
        assert apart(look_of(original), look_of(copy)) <= TWIN_BITS
    for other in range(2, 8):
        assert apart(look_of(original), look_of(drawn(other))) > TWIN_BITS


@pytest.fixture
def folder(tmp_path):
    """A picture, a smaller copy of it saved again, the same file in another folder, and two other pictures of the same colours."""
    folder = tmp_path / "foto"
    (folder / "vecchie").mkdir(parents=True)
    drawn(1).save(folder / "IMG_1.jpg", quality=95)
    drawn(1).resize((160, 120)).save(folder / "IMG_1 copia.jpg", quality=60)
    drawn(1).save(folder / "vecchie" / "IMG_1.jpg", quality=95)
    drawn(2).save(folder / "IMG_2.jpg")
    drawn(3).save(folder / "IMG_3.jpg")
    return folder


def test_copies_are_grouped_the_largest_first_and_other_pictures_are_left_alone(folder, tmp_path):
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()

    groups = index.twins()

    assert [[index.relative_of(photo["id"]) for photo in group] for group in groups] == [["IMG_1.jpg", "vecchie/IMG_1.jpg", "IMG_1 copia.jpg"]]
    # only the groups with a picture of a period, when one is named
    today = datetime.date.today()
    assert index.twins((today - datetime.timedelta(days=400), today - datetime.timedelta(days=300))) == []
    assert len(index.twins((today, today))) == 1


def test_a_library_read_before_looks_were_kept_gets_them_when_it_is_read_again(folder, tmp_path):
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()
    for photo in index.photos:
        del photo["look"]
    index._save()

    again = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    again.build()

    assert all(photo["look"] for photo in again.photos) and len(again.twins()) == 1


def ask(text, photos, actions=None, phones=None):
    async def collect():
        return [event async for event in orchestrator.reply([{"role": "user", "content": text}], "auto", [GRANITE], LAPTOP, {}, photos, actions, [], phones)]

    return asyncio.run(collect())


def test_the_copies_are_shown_with_the_one_kept_and_proposed_for_the_trash_with_no_model(folder, tmp_path, monkeypatch):
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()
    # the model is not asked
    monkeypatch.setattr(orchestrator, "decide", None)

    events = ask("trovami le foto doppie", index, Changes())

    assert [event["type"] for event in events] == ["start", "step", "text", "photos", "text", "proposal", "done"]
    kept = events[3]["sure"]
    assert [index.relative_of(photo["id"]) for photo in kept] == ["IMG_1.jpg"]
    assert [index.relative_of(photo["id"]) for photo in proposed(events)["photos"]] == ["vecchie/IMG_1.jpg", "IMG_1 copia.jpg"]
    assert proposed(events)["action"] == "trash"
    assert said(events) == (
        "Ho trovato 1 foto con 2 copie. Tengo la versione più grande, questa:"
        "Sposto nel cestino queste 2 foto? Restano sul disco, e le riporto dov'erano quando vuoi."
    )
    assert events[-1]["memory"].startswith("Found 1 photos with copies, 2 copies in all")
    assert events[-1]["model"] == "granite4.1:3b"


def test_with_no_copies_the_app_says_so(tmp_path):
    folder = tmp_path / "foto"
    folder.mkdir()
    for seed in (1, 2, 3):
        drawn(seed).save(folder / f"IMG_{seed}.jpg")
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()

    events = ask("ci sono doppioni?", index, Changes())

    assert said(events) == "Non ho trovato foto doppie tra le 3 foto che conosco."
    assert proposed(events) is None


@pytest.fixture
def phones(tmp_path):
    """A phone that sent three pictures, two of them the same."""
    known = Phones(str(tmp_path / "phone"), ColourEmbedder(), ["192.168.1.23"], 8443)
    known.devices.append({"id": "d1", "name": "Pixel", "key": "", "paired": "", "seen": ""})
    known.add("d1", [shot("1", "blue", name="mare.jpg"), shot("2", "blue", name="cielo.jpg"), shot("3", "red", name="rosa.jpg")])
    return known


def test_copies_on_the_phone_go_to_the_computer_and_then_to_the_phones_trash(tmp_path, phones):
    index = PhotoIndex(str(tmp_path / "foto"), str(tmp_path / "index"), ColourEmbedder())

    events = ask("elimina le foto doppie dal telefono", index, Changes(), phones)

    assert [photo["name"] for photo in events[3]["sure"]] == ["mare.jpg"]
    assert proposed(events) == {"type": "proposal", "action": "clear", "folder": "Tolte dal telefono", "photos": [{"id": phones.photos[1]["id"], "name": "cielo.jpg"}]}
    # a phone with no trash an app can use is offered the copy only
    phones.running(phones.devices[0], "24")
    assert proposed(ask("elimina le foto doppie dal telefono", index, Changes(), phones))["action"] == "fetch"


def test_a_copy_on_another_phone_is_not_one_too_many(tmp_path, phones):
    phones.devices.append({"id": "d2", "name": "Tablet", "key": "", "paired": "", "seen": ""})
    phones.add("d2", [shot("1", "red", name="rosa.jpg")])

    assert [[photo["name"] for photo in group] for group in phones.twins()] == [["mare.jpg", "cielo.jpg"]]


def test_a_request_for_copies_is_told_from_others():
    for text in ("trovami le foto doppie", "elimina i doppioni", "ci sono foto duplicate?", "le foto uguali", "find duplicate photos"):
        assert orchestrator.TWINS.search(text), text
    for text in ("una foto con una doppia esposizione", "trovami le foto del mare", "le foto con due cani"):
        assert not orchestrator.TWINS.search(text), text
