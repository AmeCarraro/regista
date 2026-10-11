"""What the app does to the pictures, on a folder made for the test: nothing may ever be lost."""
import json
import os
import shutil
from pathlib import Path

import pytest

from actions import Actions, Refused, collection_name, free


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "foto"
    (root / "trip").mkdir(parents=True)
    (root / "rose.jpg").write_bytes(b"rose")
    (root / "trip" / "sea.jpg").write_bytes(b"sea")
    (root / "trip" / "rose.jpg").write_bytes(b"another rose")
    return Actions(str(root)), root


def everything(root):
    """Every file under the folder with its content: what must never shrink."""
    return sorted(path.read_bytes() for path in root.rglob("*") if path.is_file() and path.suffix == ".jpg")


def test_trashing_moves_the_pictures_aside_and_loses_nothing(library):
    actions, root = library
    before = everything(root)

    done = actions.trash(["rose.jpg", "trip/sea.jpg"])

    assert done["count"] == 2 and done["missing"] == 0
    assert not (root / "rose.jpg").exists() and not (root / "trip" / "sea.jpg").exists()
    assert (root / "trip" / "rose.jpg").exists()
    assert everything(root) == before
    assert actions.in_trash() == 2


def test_undo_brings_trashed_pictures_back_where_they_were(library):
    actions, root = library
    actions.trash(["rose.jpg", "trip/sea.jpg"])

    back = actions.undo()

    assert (back["undid"], back["count"]) == ("trash", 2)
    assert (root / "rose.jpg").read_bytes() == b"rose"
    assert (root / "trip" / "sea.jpg").read_bytes() == b"sea"
    assert actions.in_trash() == 0


def test_two_pictures_with_the_same_name_do_not_collide_in_the_trash(library):
    actions, root = library

    actions.trash(["rose.jpg", "trip/rose.jpg"])
    actions.undo()

    assert (root / "rose.jpg").read_bytes() == b"rose"
    assert (root / "trip" / "rose.jpg").read_bytes() == b"another rose"


def test_a_restored_picture_never_overwrites_what_took_its_place(library):
    actions, root = library
    actions.trash(["rose.jpg"])
    (root / "rose.jpg").write_bytes(b"a new rose")

    actions.undo()

    assert (root / "rose.jpg").read_bytes() == b"a new rose"
    assert (root / "rose (2).jpg").read_bytes() == b"rose"


def test_copies_go_to_a_folder_of_their_own_and_the_originals_stay(library):
    actions, root = library

    done = actions.copy(["rose.jpg", "trip/rose.jpg", "trip/sea.jpg"], "Giappone 2024")

    folder = root / "Raccolte" / "Giappone 2024"
    assert (done["count"], done["folder"]) == (3, "Giappone 2024")
    assert sorted(path.name for path in folder.iterdir()) == ["rose (2).jpg", "rose.jpg", "sea.jpg"]
    assert (root / "rose.jpg").exists() and (root / "trip" / "sea.jpg").exists()


def test_undoing_a_copy_moves_the_copies_to_the_trash_and_leaves_the_originals(library):
    actions, root = library
    actions.copy(["rose.jpg"], "Fiori")

    back = actions.undo()

    assert (back["undid"], back["count"], back["folder"]) == ("copy", 1, "Fiori")
    assert not (root / "Raccolte" / "Fiori" / "rose.jpg").exists()
    assert (root / "rose.jpg").read_bytes() == b"rose"
    # the copy was not deleted either
    assert actions.in_trash() == 1


def test_undo_takes_back_the_last_change_that_was_not_taken_back_yet(library):
    actions, root = library
    actions.trash(["rose.jpg"])
    actions.trash(["trip/sea.jpg"])

    actions.undo()
    assert (root / "trip" / "sea.jpg").exists() and not (root / "rose.jpg").exists()
    actions.undo()
    assert (root / "rose.jpg").exists()
    with pytest.raises(Refused):
        actions.undo()


@pytest.mark.parametrize("path", ["../outside.jpg", "trip/../../outside.jpg", ".regista/cestino/x.jpg", "Raccolte/Fiori/rose.jpg"])
def test_only_pictures_of_the_library_can_be_touched(library, tmp_path, path):
    actions, _ = library
    (tmp_path / "outside.jpg").write_bytes(b"not yours")

    with pytest.raises(Refused):
        actions.trash([path])
    with pytest.raises(Refused):
        actions.copy([path], "X")
    assert (tmp_path / "outside.jpg").read_bytes() == b"not yours"


def test_a_picture_that_is_gone_is_counted_and_the_others_go_ahead(library):
    actions, _ = library

    done = actions.trash(["rose.jpg", "vanished.jpg"])

    assert (done["count"], done["missing"]) == (1, 1)


def test_every_change_is_written_down(library):
    actions, root = library
    actions.trash(["rose.jpg"])
    actions.undo()

    lines = [json.loads(line) for line in (root / ".regista" / "registro.jsonl").read_text().splitlines()]

    assert [line["kind"] for line in lines] == ["trash", "undo"]
    assert lines[0]["files"][0]["from"] == "rose.jpg"
    assert [entry["undone"] for entry in actions.history()] == [True, False]


def test_the_folder_in_the_trash_has_the_name_of_the_change_in_the_journal(library):
    actions, root = library

    done = actions.trash(["trip/sea.jpg"])

    assert (actions.trash_dir / done["id"] / "trip" / "sea.jpg").read_bytes() == b"sea"


def test_taking_a_change_back_leaves_no_empty_folders_and_keeps_the_others(library):
    actions, root = library
    actions.trash(["trip/sea.jpg"])
    actions.undo()
    # nothing is left in the trash, so the trash itself is gone; the journal stays
    assert not actions.trash_dir.exists() and actions.journal.exists()

    first = actions.copy(["rose.jpg"], "Fiori")
    actions.copy(["trip/rose.jpg"], "Fiori")
    actions.undo(first["id"])
    # the other copy is still in the folder, so the folder stays
    assert [path.name for path in (root / "Raccolte" / "Fiori").iterdir()] == ["rose (2).jpg"]
    actions.undo()
    assert not (root / "Raccolte").exists() and (root / "trip" / "rose.jpg").exists()


def test_a_change_can_be_taken_back_by_name_whatever_came_after(library):
    actions, root = library
    first = actions.trash(["rose.jpg"])
    actions.trash(["trip/sea.jpg"])

    actions.undo(first["id"])

    assert (root / "rose.jpg").exists() and not (root / "trip" / "sea.jpg").exists()
    # not twice, and not a change that never was
    with pytest.raises(Refused):
        actions.undo(first["id"])
    with pytest.raises(Refused):
        actions.undo("no such change")


def stuck(monkeypatch, name):
    """Makes one file impossible to move, as when another program holds it open."""
    real = os.rename

    def rename(source, target):
        if Path(source).name == name:
            raise PermissionError("in use")
        real(source, target)

    monkeypatch.setattr(os, "rename", rename)


def test_a_picture_that_cannot_be_moved_stays_and_the_others_go_ahead(library, monkeypatch):
    actions, root = library
    stuck(monkeypatch, "sea.jpg")

    done = actions.trash(["rose.jpg", "trip/sea.jpg"])

    assert (done["count"], done["failed"]) == (1, 1)
    assert (root / "trip" / "sea.jpg").read_bytes() == b"sea"
    # only what really moved was written down, so only that comes back
    assert [file["from"] for file in actions.last()["files"]] == ["rose.jpg"]


def test_an_undo_that_could_not_move_everything_can_be_asked_again(library, monkeypatch):
    actions, root = library
    actions.trash(["rose.jpg", "trip/sea.jpg"])
    stuck(monkeypatch, "sea.jpg")

    first = actions.undo()
    monkeypatch.undo()
    second = actions.undo()

    assert (first["count"], first["failed"]) == (1, 1)
    assert (second["count"], second["missing"], second["failed"]) == (1, 1, 0)
    assert (root / "rose.jpg").read_bytes() == b"rose" and (root / "trip" / "sea.jpg").read_bytes() == b"sea"
    with pytest.raises(Refused):
        actions.undo()


def test_a_change_that_cannot_be_written_down_is_taken_back_at_once(library):
    actions, root = library
    before = everything(root)
    # the journal cannot be written: a folder sits where the file should be
    actions.journal.mkdir(parents=True)

    with pytest.raises(OSError):
        actions.trash(["rose.jpg", "trip/sea.jpg"])
    with pytest.raises(OSError):
        actions.copy(["rose.jpg"], "Fiori")

    assert (root / "rose.jpg").read_bytes() == b"rose" and (root / "trip" / "sea.jpg").read_bytes() == b"sea"
    assert everything(root) == before and actions.in_trash() == 0


def test_a_copy_that_stops_halfway_leaves_no_broken_picture(library, monkeypatch):
    actions, root = library

    def copy2(source, target):
        Path(target).write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", copy2)

    done = actions.copy(["rose.jpg"], "Fiori")

    assert (done["count"], done["failed"], done["id"]) == (0, 1, "")
    assert list((root / "Raccolte" / "Fiori").iterdir()) == []
    assert (root / "rose.jpg").read_bytes() == b"rose" and actions.history() == []


def test_a_journal_line_cut_short_does_not_hide_the_others(library):
    actions, root = library
    actions.trash(["rose.jpg"])
    # as if the computer had stopped while writing
    with actions.journal.open("a", encoding="utf-8") as journal:
        journal.write('{"id": "2026')

    assert actions.undo()["count"] == 1
    # the undo was written on a line of its own, and is found again
    assert actions.last() is None


@pytest.mark.parametrize("written, name", [
    ("Giappone 2024", "Giappone 2024"),
    ("  le mie   foto  ", "le mie foto"),
    ("../../Windows", "Windows"),
    ('C:\\Users\\x:y*?"', "C Users x y"),
    ("...", None),
    ("", None),
])
def test_a_folder_name_cannot_lead_out_of_the_collections(written, name):
    if name is None:
        with pytest.raises(Refused):
            collection_name(written)
    else:
        assert collection_name(written) == name


def test_a_free_name_is_found_next_to_a_taken_one(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"1")
    (tmp_path / "a (2).jpg").write_bytes(b"2")

    assert free(tmp_path / "a.jpg") == tmp_path / "a (3).jpg"
    assert free(tmp_path / "b.jpg") == tmp_path / "b.jpg"
