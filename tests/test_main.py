"""The service as the page sees it, with Ollama replaced by fakes."""
import json

import pytest
from fastapi.testclient import TestClient

import llm
import main
from actions import Actions
from fakes import ColourEmbedder, picture
from photos import PhotoIndex

client = TestClient(main.app, base_url="http://127.0.0.1:8090")
GRANITE = {"name": "granite4.1:3b", "bytes": 2.1e9, "parameters": "3.4B", "capabilities": ["completion", "tools"], "loaded": True, "gpu_share": 1.0}


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_the_service_answers_only_to_its_own_names():
    # a page elsewhere that points a name of its own at this computer gets nothing
    assert client.get("/api/photos", headers={"Host": "pictures.example.com:8090"}).status_code == 400
    assert client.post("/api/actions", json={"action": "trash", "ids": ["x"]}, headers={"Host": "pictures.example.com"}).status_code == 400
    assert client.get("/api/photos", headers={"Host": "localhost:8090"}).status_code == 200


def test_models_lists_what_is_installed_and_who_gets_each_job(monkeypatch):
    async def installed():
        return [GRANITE]

    monkeypatch.setattr(llm, "installed", installed)
    monkeypatch.setenv("HOST_GPU_MB", "4096")

    body = client.get("/api/models").json()

    assert body["order"] == {"tools": ["granite4.1:3b"], "chat": ["granite4.1:3b"], "vision": []}
    assert body["models"][0]["where"] == "gpu"
    assert "problem" not in body


def test_models_says_what_is_wrong_when_ollama_is_not_running(monkeypatch):
    async def installed():
        raise ConnectionError("connection refused")

    monkeypatch.setattr(llm, "installed", installed)

    body = client.get("/api/models").json()

    assert body["models"] == [] and body["problem"] == "ConnectionError: connection refused"


def test_chat_streams_the_events_of_a_reply(monkeypatch):
    async def installed():
        return [GRANITE]

    async def stream(model, messages, max_tokens=700, schema=None):
        # the decision first, in the shape of the form, then the answer
        yield "text", '{"action": "answer", "caption": ""}' if schema else "Ciao!"
        yield "stats", {"tokens": 2, "tokens_per_second": 50.0, "load_seconds": 0}

    monkeypatch.setattr(llm, "installed", installed)
    monkeypatch.setattr(llm, "stream", stream)

    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "ciao"}]})

    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.headers["content-type"] == "application/x-ndjson"
    assert [event["type"] for event in events] == ["start", "text", "done"]
    assert events[1]["text"] == "Ciao!"


def test_a_failure_travels_as_the_last_event(monkeypatch):
    async def installed():
        raise ConnectionError("ollama is down")

    monkeypatch.setattr(llm, "installed", installed)

    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "ciao"}]})

    assert json.loads(response.text.splitlines()[-1]) == {"type": "error", "message": "ConnectionError: ollama is down"}


def test_an_empty_conversation_is_refused():
    assert client.post("/api/chat", json={"messages": []}).status_code == 422


def test_a_picture_that_is_not_known_is_not_served():
    assert client.get("/api/photos/..%2F..%2Fsecret/thumb").status_code == 404
    assert client.get("/api/photos/000000000000/full").status_code == 404


def test_the_library_reports_how_many_pictures_are_known():
    body = client.get("/api/photos").json()

    assert body["indexed"] == 0 and body["running"] is False


# ---- changes to the pictures, on a folder made for the test


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A folder of three pictures that the service knows, in place of the real one."""
    folder = tmp_path / "foto"
    picture(folder, "rose.jpg", "red")
    picture(folder / "trip", "sea.jpg", "blue")
    picture(folder / "trip", "sky.jpg", "blue")
    index = PhotoIndex(str(folder), str(tmp_path / "index"), ColourEmbedder())
    index.build()
    monkeypatch.setattr(main, "photos", index)
    monkeypatch.setattr(main, "actions", Actions(str(folder)))
    # read at once and here, not in a thread that would outlive the test
    monkeypatch.setattr(main, "read_photos", index.build)
    return index, folder


def ids(index, *paths):
    return [photo["id"] for photo in index.photos if photo["path"] in paths]


def test_a_confirmed_change_moves_pictures_to_the_trash_and_can_be_taken_back(library):
    index, folder = library
    blue = ids(index, "trip/sea.jpg", "trip/sky.jpg")

    done = client.post("/api/actions", json={"action": "trash", "ids": blue}).json()

    assert done["text"] == "Fatto: 2 foto nel cestino. Per riaverle basta dirmi «annulla»."
    assert done["memory"] == "The user confirmed: 2 photos were moved to the trash."
    assert (done["kind"], sorted(done["ids"])) == ("trash", sorted(blue))
    assert not (folder / "trip" / "sea.jpg").exists() and [photo["path"] for photo in index.photos] == ["rose.jpg"]
    # the page learns what happened, not where the files are
    assert "files" not in done
    state = client.get("/api/actions").json()
    assert state["writable"] is True and state["trash"] == 2
    assert (state["last"]["id"], state["last"]["kind"], state["last"]["count"]) == (done["id"], "trash", 2)

    back = client.post("/api/actions/undo", json={"of": done["id"]})

    assert back.json()["text"] == "Annullato: 2 foto di nuovo al loro posto."
    # the pictures that came back are named as they were, so the page can show them again
    assert (back.json()["kind"], back.json()["id"], sorted(back.json()["ids"])) == ("undo", "", sorted(blue))
    assert (folder / "trip" / "sea.jpg").exists() and len(index.photos) == 3
    assert client.get(f"/api/photos/{blue[0]}/thumb").status_code == 200
    assert client.get("/api/actions").json() == {"writable": True, "trash": 0, "last": None}
    # not twice
    again = client.post("/api/actions/undo", json={"of": done["id"]})
    assert again.status_code == 409 and again.json()["detail"] == "Questa modifica è già stata annullata."


def test_a_confirmed_copy_goes_into_a_folder_of_its_own_and_can_be_taken_back(library):
    index, folder = library

    done = client.post("/api/actions", json={"action": "copy", "ids": ids(index, "rose.jpg"), "folder": "Fiori"}).json()

    assert done["text"] == "Fatto: 1 foto copiata nella cartella «Fiori»."
    assert (folder / "Raccolte" / "Fiori" / "rose.jpg").exists() and (folder / "rose.jpg").exists()
    # the copy is not a new picture of the library
    assert len(index.photos) == 3

    back = client.post("/api/actions/undo", json={}).json()

    assert back["text"] == "Annullato: ho tolto la copia dalla cartella «Fiori». Gli originali sono al loro posto."
    assert not (folder / "Raccolte" / "Fiori" / "rose.jpg").exists() and (folder / "rose.jpg").exists()


def test_a_copy_needs_the_name_of_its_folder(library):
    index, folder = library

    response = client.post("/api/actions", json={"action": "copy", "ids": ids(index, "rose.jpg"), "folder": "  "})

    assert response.status_code == 409 and response.json()["detail"] == "Dimmi come chiamare la cartella."
    assert not (folder / "Raccolte").exists()


def test_only_pictures_the_service_knows_can_be_touched(library):
    _, folder = library

    done = client.post("/api/actions", json={"action": "trash", "ids": ["../../outside", "000000000000"]}).json()

    assert (done["count"], done["missing"], done["id"]) == (0, 2, "") and done["text"] == "Non ho spostato niente. 2 foto non c'erano più."
    assert not (folder / ".regista").exists()
    assert client.post("/api/actions", json={"action": "burn", "ids": ["x"]}).status_code == 422
    assert client.post("/api/actions", json={"action": "trash", "ids": []}).status_code == 422


def test_a_change_cannot_be_sent_by_a_form_on_another_site(library):
    index, folder = library
    body = json.dumps({"action": "trash", "ids": ids(index, "rose.jpg")})

    # what a page elsewhere can post without the browser asking this service first: plain text, or a form
    for kind in ("text/plain", "application/x-www-form-urlencoded"):
        response = client.post("/api/actions", content=body, headers={"Content-Type": kind})
        assert response.status_code == 422, kind

    assert (folder / "rose.jpg").exists() and not (folder / ".regista").exists()


def test_with_nothing_to_take_back_undo_says_so(library):
    response = client.post("/api/actions/undo", json={})

    assert response.status_code == 409 and response.json()["detail"] == "Non c'è niente da annullare."


def test_the_chat_proposes_a_change_and_touches_nothing(library, monkeypatch):
    index, folder = library

    async def installed():
        return [GRANITE]

    async def stream(model, messages, max_tokens=700, schema=None):
        yield "text", '{"action": "trash_photos", "caption": "", "folder": ""}'
        yield "stats", {"tokens": 2, "tokens_per_second": 50.0, "load_seconds": 0}

    monkeypatch.setattr(llm, "installed", installed)
    monkeypatch.setattr(llm, "stream", stream)
    rose = ids(index, "rose.jpg")

    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "eliminale"}], "selection": rose})

    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["start", "text", "proposal", "done"]
    assert events[2]["photos"] == [{"id": rose[0], "name": "rose.jpg"}]
    assert (folder / "rose.jpg").exists() and not (folder / ".regista").exists()


def test_a_small_copy_is_sent_again_only_if_it_changed(library):
    index, _ = library
    rose = ids(index, "rose.jpg")[0]

    first = client.get(f"/api/photos/{rose}/thumb")
    again = client.get(f"/api/photos/{rose}/thumb", headers={"If-None-Match": first.headers["etag"]})

    assert first.status_code == 200 and first.content[:2] == b"\xff\xd8"
    assert again.status_code == 304 and again.content == b""
