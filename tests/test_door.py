"""The door of the phones, with a phone played by the test: letting it in, learning its pictures, receiving the originals."""
import asyncio
import base64
import hashlib
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest
from fastapi.testclient import TestClient

import llm
import main
import phone as phone_module
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
    """Pairs a phone as a real one does: the code is made at the computer, its secret shown at the other door,
    the yes given at the computer to the request with the same number, and the key taken with the ticket."""
    made = client.post("/api/phone/invite").json()
    secret = parse_qs(urlparse(made["link"]).query)["s"][0]
    phone = a_phone()
    asked = phone.post("/phone/pair", json={"secret": secret, "name": name}).json()
    request = next(one for one in client.get("/api/phone").json()["pending"] if one["code"] == asked["code"])
    assert client.post(f"/api/phone/pending/{request['id']}", json={"yes": True}).json() == {"answered": True}
    paired = phone.post("/phone/pair/wait", json={"ticket": asked["ticket"]}).json()
    return phone, {"Authorization": f"Bearer {paired['token']}"}, paired


def test_the_link_for_a_phone_comes_with_a_code_to_point_the_camera_at(home):
    made = client.post("/api/phone/invite").json()

    assert made["link"].startswith("regista://pair?") and made["seconds"] == 60
    assert made["qr"].startswith("data:image/svg+xml")
    assert client.get("/api/phone").json() == {"open": False, "addresses": ["192.168.1.23"], "devices": [], "pending": [], "refused": {"count": 0, "last": "", "what": ""}}


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
    # a phone uses the app as the computer does, but it cannot let other phones in, say yes for them, or shut them out
    assert phone.get("/api/photos", headers=key).status_code == 200
    assert phone.post("/api/phone/invite", headers=key).status_code == 403
    assert phone.get("/api/phone", headers=key).status_code == 403
    assert phone.post("/api/phone/pending/abc", json={"yes": True}, headers=key).status_code == 403
    # what was refused is told at the computer, with what was wrong
    assert client.get("/api/phone").json()["refused"]["count"] == 7


def test_a_phone_is_let_in_only_with_a_yes_at_the_computer(home):
    made = client.post("/api/phone/invite").json()
    secret = parse_qs(urlparse(made["link"]).query)["s"][0]
    phone = a_phone()

    asked = phone.post("/phone/pair", json={"secret": secret, "name": "Telefono di qualcuno"}).json()

    # it waits, with no key, until the answer at the computer
    assert set(asked) == {"ticket", "code", "computer", "seconds"} and "token" not in asked
    assert phone.post("/phone/pair/wait", json={"ticket": asked["ticket"]}).json()["state"] == "waiting"
    request = client.get("/api/phone").json()["pending"][0]
    assert (request["name"], request["code"]) == ("Telefono di qualcuno", asked["code"])
    # a no, and it is out; the code it showed is good no more
    client.post(f"/api/phone/pending/{request['id']}", json={"yes": False})
    refused = phone.post("/phone/pair/wait", json={"ticket": asked["ticket"]})
    assert refused.status_code == 403 and "detto di no" in refused.json()["detail"]
    assert phone.post("/phone/pair", json={"secret": secret, "name": "x"}).status_code == 403
    assert client.get("/api/phone").json()["devices"] == []
    assert client.post("/api/phone/pending/gone", json={"yes": True}).status_code == 404


def test_too_many_refused_knocks_calm_the_door_down_but_not_for_the_phones_it_knows(home, monkeypatch):
    phone, key, _ = let_in()
    stranger = a_phone()
    monkeypatch.setattr(phone_module, "KNOCKS", 3)

    for _ in range(4):
        stranger.get("/phone/hello", headers={"Authorization": "Bearer a-guess"})

    assert stranger.get("/phone/hello").status_code == 429
    assert stranger.post("/phone/pair", json={"secret": "x", "name": "x"}).status_code == 429
    assert phone.get("/phone/hello", headers=key).status_code == 200


def test_the_page_inside_the_phone_app_is_let_in_by_the_key_once_and_then_by_a_cookie(home):
    phone, key, _ = let_in()

    first = phone.get("/api/photos", headers=key)

    cookie = first.headers["set-cookie"]
    assert "regista=" in cookie and "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Strict" in cookie
    # kept only while the app is open: on the phone the key is written nowhere but in its locked place
    assert "Max-Age" not in cookie and "Expires" not in cookie
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


def test_a_request_cannot_carry_more_than_it_has_reason_to(home):
    stranger = a_phone()
    json_body = {"Content-Type": "application/json"}

    # the request that lets a phone in is heard before any key is shown: it is a secret and a name, not a way to fill the memory
    assert stranger.post("/phone/pair", content=b'{"secret": "' + b"x" * 5000 + b'"}', headers=json_body).status_code == 413
    # nor when its size is left unsaid: what is too much is not read
    unsaid = stranger.post("/phone/pair", content=iter([b'{"secret": "', b"x" * 5000, b'"}']), headers=json_body)
    assert unsaid.status_code == 400
    # at the computer's door too
    assert client.post("/api/chat", content=b"x" * (main.BODY + 1), headers=json_body).status_code == 413
    # what has a reason to be large still passes: a real secret is refused for being wrong, not for its size
    assert stranger.post("/phone/pair", json={"secret": "a guess", "name": "x"}).status_code == 403


def test_every_answer_tells_the_browser_to_keep_the_page_to_itself(home):
    refused = client.post("/api/phone/invite", headers={"Origin": "https://pictures.example.com"})

    for answer in (client.get("/api/photos"), refused, a_phone().get("/")):
        # no other page can show this one inside itself, and the page loads nothing from elsewhere
        assert "frame-ancestors 'none'" in answer.headers["content-security-policy"]
        assert "default-src 'self'" in answer.headers["content-security-policy"]
        assert answer.headers["x-frame-options"] == "DENY" and answer.headers["x-content-type-options"] == "nosniff"
    # and the service does not list what it can do
    assert client.get("/api/docs").status_code == 404 and client.get("/api/openapi.json").status_code == 404


def test_what_a_phone_says_is_not_heard_at_the_door_of_the_computer(home):
    assert client.post("/phone/pair", json={"secret": "x", "name": "x"}).status_code == 404
    assert client.get("/phone/work").status_code == 404


def test_a_phone_says_which_android_it_runs_and_only_a_plain_number_is_kept(home):
    known, _ = home
    phone, key, paired = let_in()

    assert phone.get("/phone/hello", headers={**key, "X-Regista-Android": "24"}).status_code == 200
    assert known.devices[0]["android"] == 24
    # what is not a version is not one, and does not trouble the door
    for odd in ("²".encode("latin-1"), b"9" * 5000, b"-1", b"34 "):
        assert phone.get("/phone/hello", headers={**key, "X-Regista-Android": odd}).status_code == 200
    assert known.devices[0]["android"] == 24


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
    assert phone.get("/phone/work", headers=key).json() == {"transfers": [], "incoming": []}
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


def sha(data: bytes) -> dict:
    """What a phone says of a picture it sends: the fingerprint of its bytes."""
    return {"X-Regista-Sha256": hashlib.sha256(data).hexdigest()}


def with_two_pictures():
    """A phone that was let in and has told the computer of two pictures. Returns it, its key and the short names of the pictures."""
    phone, key, _ = let_in()
    phone.post("/phone/photos", json={"photos": [shot("41", "blue", name="mare.jpg"), shot("42", "blue", name="lago.jpg")]}, headers=key)
    return phone, key, [photo["id"] for photo in main.phones.photos]


def test_pictures_leave_a_phone_only_after_a_checked_copy_here_and_a_yes_on_the_phone(home):
    phones, folder = home
    phone, key, ids = with_two_pictures()
    kept = folder / "Raccolte" / "Tolte dal telefono"

    # the yes in the page: the phone is asked for the pictures, and nothing has left it
    asked = client.post("/api/actions", json={"action": "clear", "ids": ids}).json()
    assert asked["kind"] == "clear" and asked["folder"] == "Tolte dal telefono" and asked["text"].startswith("Ho chiesto al telefono 2 foto. Quando sono al sicuro")
    job = phone.get("/phone/work", headers=key).json()["transfers"][0]
    assert job["then"] == "trash" and len(job["photos"]) == 2 and job["trash"] == []
    first, second = (f"/phone/transfers/{job['id']}/photos/{photo['id']}" for photo in job["photos"])

    # a picture that is to leave the phone must say what it is, and arrive as that
    assert phone.put(first, content=b"original 1", headers=key).status_code == 400
    assert phone.put(first, content=b"original", headers={**key, **sha(b"original 1")}).status_code == 400
    assert not list(kept.glob("*")), "a picture that did not arrive whole is not kept"
    assert phone.put(first, content=b"original 1", headers={**key, **sha(b"original 1")}).json() == {"kept": True}
    # until every picture is here the phone is not told it may throw anything away
    assert phone.get("/phone/work", headers=key).json()["transfers"][0]["trash"] == []
    assert phone.put(second, content=b"original 2", headers={**key, **sha(b"original 2")}).json() == {"kept": True}
    assert sorted(path.read_bytes() for path in kept.iterdir()) == [b"original 1", b"original 2"]

    # now it is: the copies are here, and the phone asks its user
    waiting = client.get(f"/api/transfers/{asked['transfer']}").json()
    assert waiting["state"] == "confirming" and waiting["text"].startswith("Le 2 foto sono al sicuro sul computer, nella cartella «Tolte dal telefono».")
    job = phone.get("/phone/work", headers=key).json()["transfers"][0]
    assert job["photos"] == [] and sorted(photo["media"] for photo in job["trash"]) == ["41", "42"]
    assert len(phones.photos) == 2

    # the user said yes on the phone: the pictures are no longer among the phone's
    said = phone.post(f"/phone/transfers/{job['id']}/trashed", json={"ids": [photo["id"] for photo in job["trash"]]}, headers=key)
    assert said.json() == {"noted": True}
    done = client.get(f"/api/transfers/{asked['transfer']}").json()
    assert done["state"] == "done" and sorted(done["gone"]) == sorted(ids)
    assert done["text"] == "Fatto: 2 foto tolte dal telefono. Restano 30 giorni nel suo cestino, e una copia è sul computer nella cartella «Tolte dal telefono»."
    assert phones.photos == [] and phone.get("/phone/work", headers=key).json() == {"transfers": [], "incoming": []}
    # the copies here are now the ones that stay: no way back at a click, and in words it is said for what it is
    assert done["entry"] == ""
    last = main.actions.last()
    assert (last["kind"], last["cleared"], len(last["files"])) == ("receive", 2, 2)
    # said twice, it is heard once
    assert phone.post(f"/phone/transfers/{job['id']}/trashed", json={"ids": []}, headers=key).json() == {"noted": False}


def test_a_no_on_the_phone_leaves_its_pictures_and_keeps_the_copies(home):
    phones, folder = home
    phone, key, ids = with_two_pictures()
    asked = client.post("/api/actions", json={"action": "clear", "ids": ids}).json()
    job = phone.get("/phone/work", headers=key).json()["transfers"][0]
    for photo in job["photos"]:
        phone.put(f"/phone/transfers/{job['id']}/photos/{photo['id']}", content=b"original", headers={**key, **sha(b"original")})

    phone.post(f"/phone/transfers/{job['id']}/trashed", json={"ids": [], "why": "declined"}, headers=key)

    done = client.get(f"/api/transfers/{asked['transfer']}").json()
    assert done["text"] == "Sul telefono hai detto di no: le foto sono rimaste dov'erano. La copia è sul computer, nella cartella «Tolte dal telefono»."
    assert done["gone"] == [] and len(phones.photos) == 2
    # what happened is a copy like any other, and can be taken back like one
    back = client.post("/api/actions/undo", json={"of": done["entry"]}).json()
    assert back["text"] == "Annullato: ho tolto le 2 copie dalla cartella «Tolte dal telefono». Sul telefono le foto ci sono ancora."


def test_a_phone_cannot_say_it_threw_away_what_never_arrived_here(home):
    phones, folder = home
    phone, key, ids = with_two_pictures()
    asked = client.post("/api/actions", json={"action": "clear", "ids": ids}).json()
    job = phone.get("/phone/work", headers=key).json()["transfers"][0]
    arrived, lost = job["photos"]
    phone.put(f"/phone/transfers/{job['id']}/photos/{arrived['id']}", content=b"original", headers={**key, **sha(b"original")})
    # too early: one picture is still awaited
    assert phone.post(f"/phone/transfers/{job['id']}/trashed", json={"ids": ids}, headers=key).json() == {"noted": False}
    phone.post(f"/phone/transfers/{job['id']}/missing", json={"ids": [lost["id"]]}, headers=key)

    # only the one that is here may go, and only that one is believed gone
    assert [photo["id"] for photo in phone.get("/phone/work", headers=key).json()["transfers"][0]["trash"]] == [arrived["id"]]
    phone.post(f"/phone/transfers/{job['id']}/trashed", json={"ids": ids}, headers=key)

    done = client.get(f"/api/transfers/{asked['transfer']}").json()
    assert done["gone"] == [arrived["id"]] and [photo["id"] for photo in phones.photos] == [lost["id"]]
    assert done["text"].startswith("Fatto: 1 foto tolta dal telefono.") and done["text"].endswith("1 foto il telefono non è riuscito a mandarla: non la ho toccata.")


def test_pictures_of_the_computer_go_to_the_phone_checked_and_only_to_it(home):
    phones, folder = home
    phone, key, _ = let_in()
    rose = main.photos.photos[0]["id"]

    # the yes in the page: the pictures are prepared, and the phone takes them when its app is open
    sent = client.post("/api/actions", json={"action": "send", "ids": [rose], "folder": ""}).json()
    assert (sent["kind"], sent["folder"]) == ("send", "Dal computer")
    assert sent["text"] == "Ho preparato 1 foto per il telefono. Le prende quando Regista è aperto sul telefono."
    waiting = client.get(f"/api/transfers/{sent['transfer']}").json()
    assert waiting["state"] == "waiting" and waiting["text"].startswith("Aspetto il telefono: 0 di 1 arrivate sul telefono.")
    job = phone.get("/phone/work", headers=key).json()["incoming"]
    assert job == [{"id": sent["transfer"], "folder": "Dal computer", "photos": [{"id": rose, "name": "rose.jpg"}]}]

    # another phone cannot take it, and this one gets the picture with what it is, to check it
    other, other_key, _ = let_in("Tablet")
    path = f"/phone/incoming/{sent['transfer']}/photos/{rose}"
    assert other.get(path, headers=other_key).status_code == 409
    taken = phone.get(path, headers=key)
    assert taken.content == (folder / "rose.jpg").read_bytes()
    assert taken.headers["x-regista-sha256"] == hashlib.sha256(taken.content).hexdigest()

    assert phone.post(f"/phone/incoming/{sent['transfer']}/received", json={"ids": [rose]}, headers=key).json() == {"noted": True}
    done = client.get(f"/api/transfers/{sent['transfer']}").json()
    assert done["state"] == "done" and done["text"] == "Fatto: 1 foto sul telefono, nell'album «Dal computer»."
    # once taken it is no longer offered, and nothing on this computer changed
    assert phone.get(path, headers=key).status_code == 409
    assert phone.get("/phone/work", headers=key).json()["incoming"] == []
    assert (folder / "rose.jpg").exists() and client.get("/api/actions").json()["last"] is None


def test_pictures_are_sent_only_when_a_phone_was_let_in(home):
    rose = main.photos.photos[0]["id"]

    refused = client.post("/api/actions", json={"action": "send", "ids": [rose], "folder": ""})

    assert refused.status_code == 409 and refused.json()["detail"].startswith("Non c'è nessun telefono collegato.")


def test_a_phone_can_ask_the_computer_to_take_some_of_its_pictures(home):
    phones, folder = home
    phone, key, ids = with_two_pictures()

    # one the computer knows, and one it has not been told of yet
    offered = phone.post("/phone/offer", json={"media": ["41", "99"]}, headers=key).json()
    assert (offered["count"], offered["unknown"], offered["folder"]) == (1, 1, "Dal telefono")
    job = phone.get("/phone/work", headers=key).json()["transfers"][0]
    assert job["id"] == offered["transfer"] and [photo["media"] for photo in job["photos"]] == ["41"]
    phone.put(f"/phone/transfers/{job['id']}/photos/{job['photos'][0]['id']}", content=b"original", headers={**key, **sha(b"original")})

    # they arrive as any other, and can be taken back from here like any other
    assert [path.read_bytes() for path in (folder / "Raccolte" / "Dal telefono").iterdir()] == [b"original"]
    assert client.get("/api/actions").json()["last"]["kind"] == "receive"
    assert phone.post("/phone/offer", json={"media": ["99"]}, headers=key).status_code == 409
    assert client.post("/phone/offer", json={"media": ["41"]}).status_code == 404


def test_a_phone_takes_the_models_it_looks_at_pictures_with_from_here_and_nothing_else(home, tmp_path, monkeypatch):
    folder = tmp_path / "models"
    folder.mkdir()
    monkeypatch.setattr(main, "PHONE_MODELS", folder)
    phone, key, _ = let_in()

    # until all of them are here, there are none to take
    (folder / "text.onnx").write_bytes(b"text model")
    assert phone.get("/phone/models", headers=key).json() == {"models": []}
    for name in ("vision.onnx", "vocab.txt", "dense.safetensors"):
        (folder / name).write_bytes(name.encode())
    (folder / "secret.txt").write_bytes(b"not for phones")

    listed = phone.get("/phone/models", headers=key).json()["models"]
    assert [model["name"] for model in listed] == ["text.onnx", "vision.onnx", "vocab.txt", "dense.safetensors"]
    assert listed[0] == {"name": "text.onnx", "size": 10, "sha256": hashlib.sha256(b"text model").hexdigest()}
    taken = phone.get("/phone/models/text.onnx", headers=key)
    assert taken.content == b"text model" and taken.headers["x-regista-sha256"] == listed[0]["sha256"]
    # only those files, only to a paired phone, only at its door
    assert phone.get("/phone/models/secret.txt", headers=key).status_code == 404
    assert a_phone().get("/phone/models/text.onnx").status_code == 401
    assert client.get("/phone/models/text.onnx").status_code == 404


def test_a_phone_gets_what_the_computer_read_in_its_own_pictures_and_only_those(home, monkeypatch):
    known, _ = home
    # the model of the tests stands for the one the phone looks with
    monkeypatch.setattr(phone_module, "SHARED_MODEL", known.embedder.name)
    phone, key, _ = let_in()
    phone.post("/phone/photos", json={"photos": [shot("41", "blue", stamp="1"), shot("42", "red", stamp="1")]}, headers=key)
    other, other_key, _ = let_in("Tablet")
    other.post("/phone/photos", json={"photos": [shot("43", "red")]}, headers=other_key)

    asked = [{"id": "41", "stamp": "1"}, {"id": "42", "stamp": "2"}, {"id": "43", "stamp": "1"}, {"id": "99", "stamp": "1"}]
    vectors = phone.post("/phone/vectors", json={"photos": asked}, headers=key).json()["vectors"]

    # 42 has changed on the phone since, 43 is another phone's, 99 was never sent
    assert list(vectors) == ["41"]
    numbers = np.frombuffer(base64.b64decode(vectors["41"]), dtype="<f4")
    position = next(at for at, photo in enumerate(known.photos) if photo["media"] == "41")
    assert np.allclose(numbers, known.vectors[position])
    # numbers made by another model are of no use to the phone
    monkeypatch.setattr(phone_module, "SHARED_MODEL", "another model")
    assert phone.post("/phone/vectors", json={"photos": asked}, headers=key).json() == {"vectors": {}}
    assert a_phone().post("/phone/vectors", json={"photos": asked}).status_code == 401


def test_a_request_typed_on_a_phone_is_answered_here_or_left_to_the_phone(home, monkeypatch):
    phone, key, paired = let_in()
    asked = []

    async def answering(text, device, *_):
        asked.append((text, device))
        return {"words": "Ho trovato 1 foto.", "sure": ["41"], "maybe": [], "model": "m", "seconds": 0.1}

    async def installed():
        return []

    monkeypatch.setattr(main.llm, "installed", installed)
    monkeypatch.setattr(main.orchestrator, "on_the_phone", answering)
    assert phone.post("/phone/ask", json={"text": "le foto del mare"}, headers=key).json()["answer"]["sure"] == ["41"]
    assert asked == [("le foto del mare", paired["device"])]

    async def broken(*_):
        raise RuntimeError("Ollama answered 500")

    # a model that fails leaves the answer to the phone
    monkeypatch.setattr(main.orchestrator, "on_the_phone", broken)
    assert phone.post("/phone/ask", json={"text": "le foto del mare"}, headers=key).json() == {"answer": None}
    assert phone.post("/phone/ask", json={"text": "x" * 501}, headers=key).status_code == 422
    assert a_phone().post("/phone/ask", json={"text": "le foto del mare"}).status_code == 401


def test_a_phone_finds_here_the_app_for_its_processor_and_takes_it(home, tmp_path, monkeypatch):
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "app-arm64-v8a-release.apk").write_bytes(b"an app for most phones")
    (apps / "app-x86_64-release.apk").write_bytes(b"an app for the emulator")
    # as Android's build writes it: the file for old 32-bit phones is listed, but was not copied here
    elements = [{"filters": [{"filterType": "ABI", "value": kind}], "versionCode": 437000, "outputFile": f"app-{kind}-release.apk"}
                for kind in ("arm64-v8a", "x86_64", "armeabi-v7a")]
    (apps / "output-metadata.json").write_text(json.dumps({"elements": elements}))
    monkeypatch.setattr(main, "PHONE_APP", apps)
    phone, key, _ = let_in()

    offered = phone.get("/phone/app?kinds=arm64-v8a,armeabi-v7a,armeabi", headers=key).json()["app"]
    assert offered == {"kind": "arm64-v8a", "version": 437000, "size": 22, "sha256": hashlib.sha256(b"an app for most phones").hexdigest()}
    taken = phone.get("/phone/app/arm64-v8a", headers=key)
    assert taken.content == b"an app for most phones" and taken.headers["x-regista-sha256"] == offered["sha256"]

    assert phone.get("/phone/app?kinds=armeabi-v7a", headers=key).json() == {"app": None}
    assert phone.get("/phone/app/mips", headers=key).status_code == 404
    # only a phone that was let in, and only at the door of the phones
    assert a_phone().get("/phone/app?kinds=arm64-v8a").status_code == 401
    assert a_phone().get("/phone/app/arm64-v8a").status_code == 401
    assert client.get("/phone/app/arm64-v8a").status_code == 404
    # with no app built, none is offered
    monkeypatch.setattr(main, "PHONE_APP", tmp_path / "nothing")
    assert phone.get("/phone/app?kinds=arm64-v8a", headers=key).json() == {"app": None}


def waited(condition, seconds=10) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_the_door_of_the_phones_moves_to_the_new_address_of_this_pc(home, monkeypatch):
    phones, _ = home
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(main, "PHONE_PORT", port)
    monkeypatch.setattr(main, "doors", {})
    phones.addresses = ["127.0.0.1", "10.0.0.5"]
    # a real certificate this time: the door is opened for real
    made, secret = phone_module.self_signed()
    certificate, key = phones.certificate()
    certificate.write_bytes(made)
    key.write_bytes(secret)

    def answers(host):
        try:
            with urllib.request.urlopen(f"https://{host}:{port}/phone/hello", context=ssl._create_unverified_context(), timeout=1):
                return True
        except urllib.error.HTTPError:
            # somebody is there, and asks for a key
            return True
        except OSError:
            return False

    main._open_door("127.0.0.1")
    assert waited(lambda: answers("127.0.0.1"))
    main.move_phone_door("127.0.0.1", "127.0.0.2")
    try:
        assert waited(lambda: answers("127.0.0.2")) and waited(lambda: not answers("127.0.0.1"))
        # the link that lets a phone in says the new address
        assert phones.addresses == ["127.0.0.2", "10.0.0.5"] and list(main.doors) == ["127.0.0.2"]
    finally:
        main.doors["127.0.0.2"].should_exit = True


def test_a_new_request_of_a_phone_ends_the_one_before_and_the_looking_for_it(monkeypatch):
    monkeypatch.setattr(main, "LISTEN", 0.01)
    stopped = []

    async def looking(what, seconds):
        try:
            await asyncio.sleep(seconds)
            return {"words": what}
        except asyncio.CancelledError:
            stopped.append(what)
            raise

    async def there():
        return False

    async def three():
        first = asyncio.create_task(main.only_the_last("tablet", looking("il mare", 5), there))
        other = asyncio.create_task(main.only_the_last("pixel", looking("la neve", 0.2), there))
        await asyncio.sleep(0.05)
        second = await main.only_the_last("tablet", looking("un cane", 0.1), there)
        return await first, second, await other

    # another phone's request is not touched
    assert asyncio.run(three()) == (None, {"words": "un cane"}, {"words": "la neve"})
    assert stopped == ["il mare"] and main.asking == {}


def test_a_phone_that_goes_away_stops_the_looking_for_it(monkeypatch):
    monkeypatch.setattr(main, "LISTEN", 0.01)
    stopped = []
    checks = []

    async def looking():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            stopped.append("il mare")
            raise

    async def gone():
        checks.append(1)
        return len(checks) >= 3

    assert asyncio.run(main.only_the_last("tablet", looking(), gone)) is None
    assert stopped == ["il mare"] and main.asking == {}


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
