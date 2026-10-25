"""'Sposta': pictures moved into a folder of the library, proposed first, carried out after a yes, taken back by 'annulla'."""
import asyncio

import pytest

import orchestrator
from actions import Actions, Refused
from test_actions import everything
from test_main import client, ids
from test_main import library as service_library  # noqa: F401  (a fixture)
from test_orchestrator import Changes, Photos, form, phones, proposed, said, script  # noqa: F401  (phones is a fixture)
from test_orchestrator import ask as ask_director


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "foto"
    (root / "trip").mkdir(parents=True)
    (root / "rose.jpg").write_bytes(b"rose")
    (root / "trip" / "sea.jpg").write_bytes(b"sea")
    (root / "trip" / "sky.jpg").write_bytes(b"sky")
    return Actions(str(root)), root


def test_moving_puts_the_pictures_in_a_folder_of_the_library_and_loses_nothing(library):
    actions, root = library
    before = everything(root)

    done = actions.move(["trip/sea.jpg", "trip/sky.jpg"], "Mare")

    assert (done["kind"], done["count"], done["folder"]) == ("move", 2, "Mare")
    assert (root / "Mare" / "sea.jpg").exists() and (root / "Mare" / "sky.jpg").exists()
    assert not (root / "trip" / "sea.jpg").exists()
    assert everything(root) == before
    # one already there stays as it is
    assert actions.move(["Mare/sea.jpg"], "Mare")["count"] == 0


def test_a_move_is_taken_back_and_leaves_no_empty_folder(library):
    actions, root = library
    done = actions.move(["rose.jpg"], "Fiori")

    back = actions.undo(done["id"])

    assert (back["undid"], back["count"]) == ("move", 1)
    assert (root / "rose.jpg").read_bytes() == b"rose" and not (root / "Fiori").exists()


def test_the_folders_of_regista_are_not_where_pictures_are_moved(library):
    actions, _ = library
    with pytest.raises(Refused, match="«raccolte» è una cartella di Regista"):
        actions.move(["rose.jpg"], "raccolte")


def test_moving_pictures_of_this_computer_is_proposed_with_its_folder(monkeypatch):
    script(monkeypatch, [form("move_photos", "a dog", "Cani")])

    events, photos = ask_director("sposta le foto dei cani nella cartella Cani", photos=Photos(sure=3, maybe=0), actions=Changes())

    assert proposed(events) == {"type": "proposal", "action": "move", "folder": "Cani", "photos": [{"id": f"p{n}", "name": f"p{n}.jpg"} for n in range(3)]}
    assert said(events) == "Sposto queste 3 foto nella cartella «Cani»? Lasciano il posto dove sono: con «annulla» tornano dov'erano."
    assert events[-1]["memory"].endswith('Proposed to move them into the folder "Cani" (3 photos). Nothing was done: the user must confirm.')


def test_moving_pictures_off_the_phone_copies_them_here_into_that_folder_and_then_clears_them(monkeypatch, phones):
    phones.devices[0]["android"] = 33
    script(monkeypatch, [form("move_photos", "something blue", "Mare")])

    events, _ = ask_director("sposta dal telefono al computer le foto blu, nella cartella Mare", phones=phones, actions=Changes())

    proposal = proposed(events)
    assert (proposal["action"], proposal["folder"]) == ("clear", "Mare")


def test_a_confirmed_move_can_be_taken_back(service_library):  # noqa: F811
    index, folder = service_library
    blue = ids(index, "trip/sea.jpg", "trip/sky.jpg")

    done = client.post("/api/actions", json={"action": "move", "ids": blue, "folder": "Mare"}).json()

    assert done["text"] == "Fatto: 2 foto spostate nella cartella «Mare». Per rimetterle dov'erano basta dirmi «annulla»."
    assert (done["kind"], sorted(done["ids"])) == ("move", sorted(blue))
    # still pictures of the library, in their new place
    assert sorted(photo["path"] for photo in index.photos) == ["Mare/sea.jpg", "Mare/sky.jpg", "rose.jpg"]

    back = client.post("/api/actions/undo", json={"of": done["id"]}).json()

    assert back["text"] == "Annullato: 2 foto di nuovo dov'erano, fuori dalla cartella «Mare»."
    assert sorted(back["ids"]) == sorted(blue) and (folder / "trip" / "sea.jpg").exists() and not (folder / "Mare").exists()
