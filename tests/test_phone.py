"""The phones: letting one in, learning its pictures, asking it for the originals. No real phone, and the colour model."""
import base64
import hashlib
import io
import json
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

import phone
from actions import Refused
from fakes import ColourEmbedder, certificate_in, shot
from phone import Phones, file_name, on_phone


@pytest.fixture
def phones(tmp_path):
    certificate_in(tmp_path / "phone")
    return Phones(str(tmp_path / "phone"), ColourEmbedder(), ["192.168.1.23", "100.64.0.7"], 8443, "PC di casa")


def let_in(phones, name="Pixel"):
    """Pairs a phone the way a real one does: with the secret of the link. Returns its key and its name here."""
    secret = parse_qs(urlparse(phones.invite()["link"]).query)["s"][0]
    paired = phones.pair(secret, name)
    return paired["token"], paired["device"]


def test_the_link_says_where_the_computer_is_and_how_to_recognise_it(phones):
    link = urlparse(phones.invite()["link"])
    said = parse_qs(link.query)

    assert (link.scheme, link.netloc) == ("regista", "pair")
    assert said["a"] == ["192.168.1.23,100.64.0.7"] and said["p"] == ["8443"] and said["n"] == ["PC di casa"]
    # the fingerprint of the certificate: the phone will talk to no other computer
    assert said["f"] == [hashlib.sha256(b"a certificate").hexdigest()]
    assert len(said["s"][0]) >= 20


def test_a_link_lets_one_phone_in_once(phones):
    secret = parse_qs(urlparse(phones.invite()["link"]).query)["s"][0]

    paired = phones.pair(secret, "  Pixel 8\n")

    assert paired["computer"] == "PC di casa" and phones.described()[0]["name"] == "Pixel 8"
    with pytest.raises(Refused):
        phones.pair(secret, "another phone")
    with pytest.raises(Refused):
        phones.pair("a guess", "a stranger")
    assert len(phones.devices) == 1


def test_a_link_stops_being_good_after_a_few_minutes(phones, monkeypatch):
    secret = parse_qs(urlparse(phones.invite()["link"]).query)["s"][0]
    later = phone.time.monotonic() + phone.INVITE_SECONDS + 1
    monkeypatch.setattr(phone.time, "monotonic", lambda: later)

    with pytest.raises(Refused):
        phones.pair(secret, "Pixel")


def test_a_new_link_replaces_the_one_before(phones):
    old = parse_qs(urlparse(phones.invite()["link"]).query)["s"][0]
    phones.invite()

    with pytest.raises(Refused):
        phones.pair(old, "Pixel")


def test_a_phone_is_known_by_its_key_and_the_key_is_not_kept(phones, tmp_path):
    token, device = let_in(phones)

    assert phones.device_of(token)["id"] == device
    assert phones.device_of("another key") is None and phones.device_of("") is None
    assert token not in (tmp_path / "phone" / "devices.json").read_text()
    # the page is told about the phone, never its key
    assert "key" not in phones.described()[0]


def test_a_phone_that_is_shut_out_is_forgotten_with_its_pictures(phones):
    token, device = let_in(phones)
    phones.add(device, [shot("1", "red")])
    asked = phones.ask([photo["id"] for photo in phones.photos], "Rose")

    assert phones.forget_device(device) is True

    assert phones.device_of(token) is None and phones.photos == [] and phones.search("red")["indexed"] == 0
    assert phones.transfer(asked["id"])["state"] == "done" and phones.work(device) == []
    assert phones.forget_device(device) is False


def test_the_computer_asks_only_for_the_small_copies_it_does_not_have(phones):
    _, device = let_in(phones)
    listing = [{"id": "1", "stamp": "a"}, {"id": "2", "stamp": "a"}, {"id": "3", "stamp": "a"}]

    assert phones.wanted(device, listing) == ["1", "2", "3"]
    assert phones.add(device, [shot("1", "red", stamp="a"), shot("2", "blue", stamp="a")]) == 2
    assert phones.wanted(device, listing) == ["3"]
    # a picture that changed on the phone is wanted again, and takes the place of the old one
    assert phones.wanted(device, [{"id": "1", "stamp": "b"}, {"id": "2", "stamp": "a"}]) == ["1"]
    phones.add(device, [shot("1", "green", stamp="b")])
    assert len(phones.photos) == 2 and phones.search("green")["sure"][0]["name"] == "IMG_1.jpg"


def test_pictures_the_phone_no_longer_has_are_forgotten(phones, tmp_path):
    _, device = let_in(phones)
    phones.add(device, [shot("1", "red"), shot("2", "blue")])
    red = phones.search("red")["sure"][0]["id"]

    phones.wanted(device, [{"id": "2", "stamp": "1"}])

    assert [photo["media"] for photo in phones.photos] == ["2"] and phones.thumbnail(red) is None
    assert not (tmp_path / "phone" / "thumbs" / f"{red}.jpg").exists()


def test_the_pictures_of_a_phone_are_searched_like_the_ones_of_the_computer(phones):
    _, device = let_in(phones)
    phones.add(device, [shot("10", "red", name="rosa.jpg"), shot("11", "blue", name="mare.jpg"), shot("12", "blue", name="cielo.jpg")])

    found = phones.search("something blue")

    assert sorted(photo["name"] for photo in found["sure"]) == ["cielo.jpg", "mare.jpg"]
    assert found["matching"] == 2 and found["indexed"] == 3 and found["maybe"] == []
    # their short names tell them apart from the pictures of the computer
    assert all(on_phone(photo["id"]) for photo in found["sure"]) and not on_phone("0123456789ab")
    # what is shown is a JPEG made here, not the bytes the phone sent
    assert phones.thumbnail(found["sure"][0]["id"])[:2] == b"\xff\xd8"
    assert phones.thumbnail("t000000000000") is None


def test_what_cannot_be_a_small_copy_is_skipped(phones):
    _, device = let_in(phones)
    broken = {**shot("1", "red"), "jpeg": "bm90IGEgcGljdHVyZQ=="}
    huge = {**shot("2", "red"), "jpeg": "A" * (phone.SMALL_COPY + 1)}

    # a few bytes that claim to be an enormous picture: opening it would fill the memory
    blown = io.BytesIO()
    Image.new("RGB", (4000, 4000), (255, 0, 0)).save(blown, "PNG")
    enormous = {**shot("4", "red"), "jpeg": base64.b64encode(blown.getvalue()).decode()}
    assert len(enormous["jpeg"]) < phone.SMALL_COPY

    assert phones.add(device, [broken, huge, enormous, shot("3", "red")]) == 1
    assert [photo["media"] for photo in phones.photos] == ["3"]
    assert phones.add(device, [broken]) == 0


def test_what_is_known_of_a_phone_survives_a_restart(phones, tmp_path):
    token, device = let_in(phones)
    phones.add(device, [shot("1", "red")])
    phones.save()

    again = Phones(str(tmp_path / "phone"), ColourEmbedder(), [], 8443)

    assert again.device_of(token)["id"] == device
    assert [photo["name"] for photo in again.search("red")["sure"]] == ["IMG_1.jpg"]

    class OtherModel(ColourEmbedder):
        name = "another model"

    # fingerprints made by another model are of no use: the phone will send its pictures again
    assert Phones(str(tmp_path / "phone"), OtherModel(), [], 8443).photos == []


def test_a_phone_is_asked_for_originals_and_the_request_ends_when_all_are_accounted_for(phones):
    _, device = let_in(phones)
    phones.add(device, [shot("1", "blue", name="mare.jpg"), shot("2", "blue"), shot("3", "blue")])
    blue = [photo["id"] for photo in phones.search("blue")["sure"]]

    asked = phones.ask([*blue, blue[0], "t000000000000"], "Mare")

    assert asked["photos"] == blue and asked["state"] == "waiting"
    job = phones.work(device)[0]
    assert job["id"] == asked["id"] and sorted(photo["media"] for photo in job["photos"]) == ["1", "2", "3"]
    first = next(photo["id"] for photo in phones.photos if photo["media"] == "1")
    assert phones.expected(asked["id"], device, first) == {"folder": "Mare", "name": "mare.jpg"}

    # one arrives, the others cannot be sent: only then is the request over
    assert phones.settle(asked["id"], device, arrived={first: "Raccolte/Mare/mare.jpg"}) is None
    assert len(phones.work(device)[0]["photos"]) == 2
    with pytest.raises(Refused):
        phones.expected(asked["id"], device, first)
    finished = phones.settle(asked["id"], device, missing=[identifier for identifier in blue if identifier != first])
    assert finished["state"] == "done" and finished["arrived"] == {first: "Raccolte/Mare/mare.jpg"}
    assert phones.work(device) == [] and phones.settle(asked["id"], device, missing=blue) is None

    phones.close(asked["id"], "20261012-100000-abcd")
    assert phones.transfer(asked["id"])["entry"] == "20261012-100000-abcd"


def test_only_the_phone_that_was_asked_may_send(phones):
    _, mine = let_in(phones, "mine")
    _, other = let_in(phones, "other")
    phones.add(mine, [shot("1", "red")])
    asked = phones.ask([phones.photos[0]["id"]], "Rose")

    assert phones.work(other) == []
    with pytest.raises(Refused):
        phones.expected(asked["id"], other, phones.photos[0]["id"])
    with pytest.raises(Refused):
        phones.expected("no such request", mine, phones.photos[0]["id"])
    assert phones.settle(asked["id"], other, missing=[phones.photos[0]["id"]]) is None
    with pytest.raises(Refused):
        phones.ask(["t000000000000"], "Rose")


def test_a_picture_that_left_the_phone_is_not_waited_for(phones):
    _, device = let_in(phones)
    phones.add(device, [shot("1", "red"), shot("2", "red")])
    asked = phones.ask([photo["id"] for photo in phones.photos], "Rose")

    phones.wanted(device, [{"id": "2", "stamp": "1"}])

    assert [photo["media"] for photo in phones.work(device)[0]["photos"]] == ["2"]
    assert json.loads((phones.folder / "transfers.json").read_text())[0]["id"] == asked["id"]


@pytest.mark.parametrize("sent, kept", [
    ("IMG_20240812_101010.jpg", "IMG_20240812_101010.jpg"),
    ("../../Windows/system32/x.png", "Windows system32 x.png"),
    ("vacanza.HEIC", "vacanza.HEIC"),
    ("script.exe", "script.exe.jpg"),
    ("senza estensione", "senza estensione.jpg"),
    ("", "foto.jpg"),
    ("...", "foto.jpg"),
])
def test_a_file_from_a_phone_gets_a_name_that_is_only_a_name_and_ends_as_a_picture(sent, kept):
    assert file_name(sent) == kept
