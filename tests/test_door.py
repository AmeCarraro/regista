"""The door of the phones, with a phone played by the test: letting it in, learning its pictures, receiving the originals."""
import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import llm
import main
from actions import Actions
from fakes import ColourEmbedder, certificate_in, picture, shot
from phone import Phones
from photos import PhotoIndex

# someone at this computer, and the model the tests pretend is installed
client = TestClient(main.app, base_url="http://127.0.0.1:8090")
GRANITE = {"name": "granite4.1:3b", "bytes": 2.1e9, "parameters": "3.4B", "capabilities": ["completion", "tools"], "loaded": True, "gpu_share": 1.0}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A picture folder and a place for what is known of the phones, in place of the real ones."""
    folder = tmp_path / "foto"
    picture(folder, "rose.jpg", "red")
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()
    certificate_in(tmp_path / "phone")
    known = Phones(str(tmp_path / "phone"), ColourEmbedder(), ["192.168.1.23"], 8443, "PC di casa")
    monkeypatch.setattr(main, "photos", index)
    monkeypatch.setattr(main, "actions", Actions(str(folder)))
    monkeypatch.setattr(main, "phones", known)
    monkeypatch.setattr(main, "read_photos", index.build)
    return known, folder


def a_phone():
    """Someone who knocks at the door of the phones: this computer's address on the network, and the port of that door."""
    return TestClient(main.app, base_url="https://192.168.1.23:8443")


def let_in(name="Pixel 8"):
    """Pairs a phone as a real one does: the link is made at the computer, its secret is shown at the other door."""
    made = client.post("/api/phone/invite").json()
    secret = parse_qs(urlparse(made["link"]).query)["s"][0]
    phone = a_phone()
    paired = phone.post("/phone/pair", json={"secret": secret, "name": name}).json()
    return phone, {"Authorization": f"Bearer {paired['token']}"}, paired


def test_the_link_for_a_phone_comes_with_a_code_to_point_the_camera_at(home):
    made = client.post("/api/phone/invite").json()

    assert made["link"].startswith("regista://pair?") and made["seconds"] == 300
    assert made["qr"].startswith("data:image/svg+xml")
    assert client.get("/api/phone").json() == {"open": False, "addresses": ["192.168.1.23"], "devices": []}


def test_the_door_of_the_phones_opens_only_to_a_phone_that_was_let_in(home):
    stranger = a_phone()

    # nothing at all without a key: not the page, not the pictures, not the chat
    for path in ("/", "/api/photos", "/api/models", "/phone/hello", "/phone/work"):
        assert stranger.get(path).status_code == 401, path
    assert stranger.get("/api/photos", headers={"Authorization": "Bearer a-guess"}).status_code == 401
    assert stranger.post("/phone/pair", json={"secret": "a guess", "name": "x"}).status_code == 403

    phone, key, paired = let_in()

    assert paired["computer"] == "PC di casa"
    assert phone.get("/phone/hello", headers=key).json() == {"computer": "PC di casa", "photos": 0}
    # a phone uses the app as the computer does, but it cannot let other phones in or shut them out
    assert phone.get("/api/photos", headers=key).status_code == 200
    assert phone.post("/api/phone/invite", headers=key).status_code == 403
    assert phone.get("/api/phone", headers=key).status_code == 403


def test_the_page_inside_the_phone_app_is_let_in_by_the_key_once_and_then_by_a_cookie(home):
    phone, key, _ = let_in()

    first = phone.get("/api/photos", headers=key)

    cookie = first.headers["set-cookie"]
    assert "regista=" in cookie and "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Strict" in cookie
    # from here on the browser part of the app carries the cookie by itself
    assert phone.get("/api/photos").json()["door"] == "phone"
    assert "set-cookie" not in phone.get("/api/photos").headers


def test_another_page_cannot_ask_for_a_change_at_either_door(home):
    phones, folder = home
    elsewhere = {"Origin": "https://pictures.example.com"}

    # at the computer: a site the user has open cannot make a pairing link, shut a phone out or move a picture
    assert client.post("/api/phone/invite", headers=elsewhere).status_code == 403
    assert client.post("/api/photos/read", headers=elsewhere).status_code == 403
    assert client.post("/api/actions", json={"action": "trash", "ids": ["x"]}, headers=elsewhere).status_code == 403
    assert client.post("/api/phone/invite", headers={"Origin": "null"}).status_code == 403
    # the app's own page can, and so can what is not a browser and names no page
    assert client.post("/api/phone/invite", headers={"Origin": "http://127.0.0.1:8090"}).status_code == 200
    assert client.post("/api/phone/invite").status_code == 200
    # looking is not changing: a GET is not refused for where it comes from (and another site cannot read the answer anyway)
    assert client.get("/api/photos", headers=elsewhere).status_code == 200

    phone, key, _ = let_in()
    assert phone.post("/phone/library/done", headers={**key, **elsewhere}).status_code == 403
    assert phone.post("/phone/library/done", headers={**key, "Origin": "https://192.168.1.23:8443"}).status_code == 200


def test_what_a_phone_says_is_not_heard_at_the_door_of_the_computer(home):
    assert client.post("/phone/pair", json={"secret": "x", "name": "x"}).status_code == 404
    assert client.get("/phone/work").status_code == 404


def test_a_phone_that_is_shut_out_cannot_come_in_any_more(home):
    phone, key, paired = let_in()

    assert client.post(f"/api/phone/devices/{paired['device']}/forget").json() == {"forgotten": True}

    assert phone.get("/phone/hello", headers=key).status_code == 401
    assert client.post(f"/api/phone/devices/{paired['device']}/forget").status_code == 404


def test_pictures_asked_of_a_phone_arrive_in_a_folder_and_can_be_taken_back(home, monkeypatch):
    phones, folder = home
    phone, key, _ = let_in()

    # the phone says what it has, and sends the small copies the computer asks for
    listing = [{"id": "41", "stamp": "a"}, {"id": "42", "stamp": "a"}, {"id": "43", "stamp": "a"}]
    assert phone.post("/phone/library", json={"photos": listing}, headers=key).json() == {"wanted": ["41", "42", "43"]}
    sent = [shot("41", "blue", name="mare.jpg", stamp="a"), shot("42", "blue", name="mare.jpg", stamp="a"), shot("43", "red", name="rosa.jpg", stamp="a")]
    assert phone.post("/phone/photos", json={"photos": sent}, headers=key).json() == {"kept": 3}
    assert phone.post("/phone/library", json={"photos": listing}, headers=key).json() == {"wanted": []}
    assert phone.post("/phone/library/done", headers=key).json() == {"saved": True}
    assert client.get("/api/phone").json()["devices"][0]["photos"] == 3

    # at the computer: the pictures of the phone are found, and shown through their small copies
    async def installed():
        return [GRANITE]

    async def stream(model, messages, max_tokens=700, schema=None):
        yield "text", '{"action": "find_photos", "caption": "something blue", "folder": ""}'
        yield "stats", {"tokens": 2, "tokens_per_second": 50.0, "load_seconds": 0}

    monkeypatch.setattr(llm, "installed", installed)
    monkeypatch.setattr(llm, "stream", stream)
    said = client.post("/api/chat", json={"messages": [{"role": "user", "content": "trovami sul telefono le foto blu"}]})
    found = next(event for event in map(json.loads, said.text.splitlines()) if event["type"] == "photos")
    blue = [photo["id"] for photo in found["sure"]]
    assert found["place"] == "phone" and len(blue) == 2
    assert client.get(f"/api/photos/{blue[0]}/thumb").content[:2] == b"\xff\xd8"
    assert client.get(f"/api/photos/{blue[0]}/full").content[:2] == b"\xff\xd8"

    # the user says yes to copying them: the phone is asked, and nothing has arrived yet
    asked = client.post("/api/actions", json={"action": "fetch", "ids": blue, "folder": "Mare"}).json()
    assert asked["text"] == "Ho chiesto al telefono 2 foto. Arrivano quando Regista è aperto sul telefono."
    waiting = client.get(f"/api/transfers/{asked['transfer']}").json()
    assert (waiting["state"], waiting["arrived"], waiting["total"]) == ("waiting", 0, 2)
    assert client.get("/api/phone").json()["devices"][0]["waiting"] == 2
    assert not (folder / "Raccolte").exists()

    # the phone, when its app is open, finds the request and sends the originals
    job = phone.get("/phone/work", headers=key).json()["transfers"][0]
    assert job["id"] == asked["transfer"] and sorted(photo["media"] for photo in job["photos"]) == ["41", "42"]
    for number, photo in enumerate(job["photos"]):
        kept = phone.put(f"/phone/transfers/{job['id']}/photos/{photo['id']}", content=f"original {number}".encode(), headers=key)
        assert kept.json() == {"kept": True}
    # two pictures with the same name on the phone do not overwrite each other here
    landed = sorted((folder / "Raccolte" / "Mare").iterdir())
    assert [path.name for path in landed] == ["mare (2).jpg", "mare.jpg"]
    assert sorted(path.read_bytes() for path in landed) == [b"original 0", b"original 1"]
    assert phone.get("/phone/work", headers=key).json() == {"transfers": []}
    # not twice
    again = phone.put(f"/phone/transfers/{job['id']}/photos/{job['photos'][0]['id']}", content=b"again", headers=key)
    assert again.status_code == 409

    done = client.get(f"/api/transfers/{asked['transfer']}").json()
    assert done["state"] == "done" and done["text"] == "Fatto: 2 foto arrivate dal telefono, nella cartella «Mare»."
    assert client.get("/api/actions").json()["last"]["kind"] == "receive"

    # and it can be taken back like any copy: the copies go to the trash, the phone keeps its pictures
    back = client.post("/api/actions/undo", json={"of": done["entry"]}).json()
    assert back["text"] == "Annullato: ho tolto le 2 copie dalla cartella «Mare». Sul telefono le foto ci sono ancora."
    assert not (folder / "Raccolte").exists() and client.get("/api/actions").json()["trash"] == 2


def test_a_picture_the_phone_cannot_send_ends_the_wait(home):
    phones, _ = home
    phone, key, _ = let_in()
    phone.post("/phone/photos", json={"photos": [shot("7", "red")]}, headers=key)
    identifier = phones.photos[0]["id"]
    asked = client.post("/api/actions", json={"action": "fetch", "ids": [identifier], "folder": "Rose"}).json()

    assert phone.post(f"/phone/transfers/{asked['transfer']}/missing", json={"ids": [identifier]}, headers=key).json() == {"noted": True}

    done = client.get(f"/api/transfers/{asked['transfer']}").json()
    assert done["state"] == "done" and done["text"] == "Dal telefono non è arrivata nessuna foto. 1 foto il telefono non è riuscito a mandarla."
    assert done["entry"] == "" and client.get("/api/actions").json()["last"] is None


def test_a_picture_that_arrives_empty_is_not_kept_and_is_still_waited_for(home):
    phones, folder = home
    phone, key, _ = let_in()
    phone.post("/phone/photos", json={"photos": [shot("7", "red")]}, headers=key)
    identifier = phones.photos[0]["id"]
    asked = client.post("/api/actions", json={"action": "fetch", "ids": [identifier], "folder": "Rose"}).json()

    assert phone.put(f"/phone/transfers/{asked['transfer']}/photos/{identifier}", content=b"", headers=key).status_code == 400

    assert list((folder / "Raccolte" / "Rose").iterdir()) == []
    assert len(phone.get("/phone/work", headers=key).json()["transfers"][0]["photos"]) == 1


def test_asking_a_phone_needs_pictures_it_has_and_a_folder_name(home):
    phones, _ = home
    phone, key, _ = let_in()
    phone.post("/phone/photos", json={"photos": [shot("7", "red")]}, headers=key)

    assert client.post("/api/actions", json={"action": "fetch", "ids": ["t000000000000"], "folder": "Rose"}).status_code == 409
    assert client.post("/api/actions", json={"action": "fetch", "ids": [phones.photos[0]["id"]], "folder": " "}).status_code == 409
    assert phones.transfers == [] and client.get("/api/transfers/nothing").status_code == 404
