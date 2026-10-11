"""The picture index without the real model: a fake one that only sees the colour of a picture."""
import pytest
from PIL import Image

from fakes import ColourEmbedder, picture
from photos import PhotoIndex


@pytest.fixture
def library(tmp_path):
    photos = tmp_path / "foto"
    picture(photos, "rose.jpg", "red")
    picture(photos / "trip", "sea.jpg", "blue")
    picture(photos / "trip", "meadow.png", "green")
    (photos / "notes.txt").write_text("not a picture")
    embedder = ColourEmbedder()
    return PhotoIndex(str(photos), str(tmp_path / "index"), embedder), embedder, photos


def test_a_sentence_finds_the_pictures_that_match_it(library):
    index, _, _ = library
    index.build()

    result = index.search("something red")

    assert [photo["name"] for photo in result["sure"]] == ["rose.jpg"]
    assert result["maybe"] == [] and result["indexed"] == 3


def test_pictures_in_subfolders_are_found_and_other_files_are_left_out(library):
    index, _, _ = library
    index.build()

    assert sorted(photo["path"] for photo in index.photos) == ["rose.jpg", "trip/meadow.png", "trip/sea.jpg"]
    assert index.state == {"running": False, "done": 3, "total": 3, "error": ""}


def test_only_new_pictures_are_read_the_second_time(library):
    index, embedder, photos = library
    index.build()
    picture(photos, "sky.jpg", "blue")

    index.build()

    # three the first time, one the second: the others were recognised by size and date
    assert embedder.pictures_read == 4
    assert {photo["name"] for photo in index.search("blue")["sure"]} == {"sea.jpg", "sky.jpg"}


def test_a_picture_that_was_deleted_is_forgotten(library):
    index, _, photos = library
    index.build()
    (photos / "rose.jpg").unlink()

    index.build()

    assert index.search("red")["sure"] == []
    assert len(index.photos) == 2


def test_the_index_survives_a_restart(library, tmp_path):
    index, _, photos = library
    index.build()

    again = PhotoIndex(str(photos), str(tmp_path / "index"), ColourEmbedder())

    assert [photo["name"] for photo in again.search("green")["sure"]] == ["meadow.png"]


def test_fingerprints_made_by_another_model_are_made_again(library, tmp_path):
    index, _, photos = library
    index.build()

    class OtherModel(ColourEmbedder):
        name = "another model"

    other = OtherModel()
    again = PhotoIndex(str(photos), str(tmp_path / "index"), other)
    assert again.photos == []
    again.build()

    assert other.pictures_read == 3


def test_a_broken_file_is_skipped(library):
    index, _, photos = library
    (photos / "broken.jpg").write_bytes(b"not really a jpeg")

    index.build()

    assert len(index.photos) == 3


def test_a_picture_is_shown_by_its_short_name_never_by_a_path(library):
    index, _, photos = library
    index.build()
    rose = next(photo for photo in index.photos if photo["path"] == "rose.jpg")

    assert index.path_of(rose["id"]) == photos / "rose.jpg"
    assert index.path_of("../../etc/passwd") is None
    assert index.thumbnail("nothing") is None
    # the small copy is a JPEG, and it is kept for the next time
    assert index.thumbnail(rose["id"])[:2] == b"\xff\xd8"
    assert len(list((index.index_dir / "thumbs").glob(f"{rose['id']}-*.jpg"))) == 1


def test_another_picture_under_the_same_name_does_not_get_the_old_small_copy(library):
    index, _, photos = library
    index.build()
    rose = next(photo for photo in index.photos if photo["path"] == "rose.jpg")
    before = index.thumbnail(rose["id"])

    # a larger picture of another colour takes the name: what is shown must be what is there
    (photos / "rose.jpg").unlink()
    Image.new("RGB", (200, 100), (0, 0, 255)).save(photos / "rose.jpg")
    index.build()

    assert index.thumbnail(rose["id"]) != before


def test_with_no_pictures_a_search_says_so(tmp_path):
    index = PhotoIndex(str(tmp_path / "missing"), str(tmp_path / "index"), ColourEmbedder())
    index.build()

    assert index.search("anything") == {"sure": [], "maybe": [], "matching": 0, "indexed": 0}


def test_a_search_says_how_many_match_also_when_it_shows_fewer(library):
    index, _, photos = library
    for number in range(5):
        picture(photos / "sky", f"sky{number}.jpg", "blue")
    index.build()

    result = index.search("blue", limit=2)

    assert len(result["sure"]) == 2 and result["matching"] == 6


def test_the_trash_and_the_copies_are_not_part_of_the_library(library):
    index, _, photos = library
    picture(photos / ".regista" / "cestino" / "20260101-000000-abcd", "old.jpg", "red")
    picture(photos / "Raccolte" / "Fiori", "rose.jpg", "red")

    index.build()

    assert sorted(photo["path"] for photo in index.photos) == ["rose.jpg", "trip/meadow.png", "trip/sea.jpg"]


def test_a_picture_can_be_forgotten_at_once(library):
    index, _, _ = library
    index.build()
    rose = next(photo for photo in index.photos if photo["path"] == "rose.jpg")

    index.forget([rose["id"], "not a picture"])

    assert index.search("red")["sure"] == [] and len(index.photos) == 2
    assert index.path_of(rose["id"]) is None
    index.forget([photo["id"] for photo in index.photos])
    assert index.search("blue") == {"sure": [], "maybe": [], "matching": 0, "indexed": 0}
