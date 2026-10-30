"""The pictures by kind: each in one kind, the sure ones first, screenshots by their name; nothing is moved."""
import base64

import numpy as np

import main
import orchestrator
from kinds import KINDS, Kinds, in_words
from photos import newest
from test_door import a_phone, client, home, let_in  # noqa: F401 - home is a fixture
from test_trips import ask

NAMES = [kind for kind, _, _ in KINDS]


class KindEmbedder:
    """A sentence becomes the kind whose things it names: one number for each kind."""

    def text(self, sentence):
        vector = np.zeros(len(KINDS), dtype=np.float32)
        vector[next(at for at, (_, _, things) in enumerate(KINDS) if any(sentence.endswith(thing) for thing in things))] = 1
        return vector


def leaning(**shares):
    """A picture that shows each kind as much as said."""
    vector = np.zeros(len(KINDS), dtype=np.float32)
    for kind, share in shares.items():
        vector[NAMES.index(kind)] = share
    return vector / np.linalg.norm(vector)


PHOTOS = [
    {"id": "a", "path": "Viaggi/cane.jpg", "day": "2026-05-01"},
    {"id": "b", "path": "cane al mare.jpg", "day": "2026-06-01"},
    {"id": "c", "path": "forse.jpg", "day": "2026-07-01"},
    {"id": "d", "path": "Screenshots/Screenshot_20260801.png", "day": "2026-08-01"},
    {"id": "e", "path": "chiesa.jpg", "day": ""},
]
VECTORS = np.stack([leaning(animali=0.8, oggetti=0.2), leaning(animali=0.9, persone=0.1), leaning(animali=0.5, persone=0.499), leaning(documenti=1), leaning(citta=1)])


def test_each_picture_lands_in_one_kind_the_sure_ones_first_and_screenshots_by_their_name():
    kinds = Kinds(KindEmbedder(), newest)
    sorted_out = kinds.sort(PHOTOS, VECTORS)

    # the sure ones the newest first; a picture that could be two kinds is among the less sure of the likelier
    assert [photo["id"] for photo in sorted_out["animali"]["sure"]] == ["b", "a"]
    assert [photo["id"] for photo in sorted_out["animali"]["maybe"]] == ["c"]
    # a screenshot is known by its name, whatever it shows
    assert [photo["id"] for photo in sorted_out["schermate"]["sure"]] == ["d"]
    assert sorted_out["citta"]["sure"] == [{"id": "e", "name": "chiesa.jpg", "day": "", "score": 1.0}]
    # every picture in one kind, and in one only
    assert sorted(photo["id"] for group in sorted_out.values() for photo in group["sure"] + group["maybe"]) == ["a", "b", "c", "d", "e"]
    # the same library is not worked out again; a changed one is
    assert kinds.sort(PHOTOS, VECTORS) is sorted_out
    assert kinds.sort(PHOTOS[:2], VECTORS[:2]) is not sorted_out
    assert in_words(sorted_out, 5).startswith("Ho diviso per tipo le 5 foto: Animali 3, Città e monumenti 1, Schermate 1. Le trovi in «Foto»")
    assert in_words(Kinds(KindEmbedder(), newest).sort([], np.zeros((0, 0))), 0).startswith("Non ho ancora foto da dividere")


def test_the_page_shows_the_kinds_the_pictures_of_each_and_all_of_them(home):
    listed = client.get("/api/kinds").json()
    assert listed["total"] == 1 and sum(kind["count"] for kind in listed["kinds"]) == 1
    shown = client.get(f"/api/kinds/{listed['kinds'][0]['kind']}").json()
    assert [photo["name"] for photo in shown["sure"] + shown["maybe"]] == ["rose.jpg"] and shown["place"] == "computer"
    assert [photo["name"] for photo in client.get("/api/kinds/tutte").json()["sure"]] == ["rose.jpg"]
    assert client.get("/api/kinds/nessuno").status_code == 404


def test_a_phone_takes_the_numbers_of_the_kinds_to_sort_its_own_pictures(home):
    phone, key, _ = let_in()
    given = phone.get("/phone/kinds", headers=key).json()

    assert [kind["label"] for kind in given["kinds"]] == [label for _, label, _ in KINDS] and given["margin"] == 0.01
    # the same numbers the computer sorts with, row by row, as 32-bit numbers
    said = main.photos.kinds.sentences()
    assert np.allclose(np.frombuffer(base64.b64decode(given["kinds"][1]["vector"]), dtype="<f4"), said[1])
    assert a_phone().get("/phone/kinds").status_code == 401
    assert client.get("/phone/kinds").status_code == 404


def test_a_request_to_sort_the_pictures_by_kind_is_answered_with_no_model(home, monkeypatch):
    monkeypatch.setattr(orchestrator, "decide", None)
    for text in ("cataloga le foto per tipo", "dividi le foto per tipo", "organizza le immagini per categoria", "catalogami le foto"):
        assert orchestrator.BY_KIND.search(text), text
    for text in ("le foto dei viaggi", "trovami un catalogo di mobili", "organizza le foto per viaggio"):
        assert not orchestrator.BY_KIND.search(text), text

    # the library of the fixture: one picture
    events = ask("cataloga le foto per tipo", main.photos)
    words = "".join(event["text"] for event in events if event["type"] == "text")
    assert words.startswith("Ho diviso per tipo la foto:") and "Non ho spostato niente" in words
