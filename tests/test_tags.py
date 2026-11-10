from contextlib import closing
import sqlite3

import pytest

from tags import Tags


def test_manual_tags_survive_reopen_and_match_unicode_variants(tmp_path):
    database = tmp_path / "tags.sqlite"
    tags = Tags(database)
    assert tags.add("  Cafè   Straße  ", ["p2", "p1", "p2"]) == ["p2", "p1"]
    assert tags.add("CAFE\u0300 STRASSE", ["p1", "p3"]) == ["p3"]
    assert tags.add("Giappone", ["p1", "p2"]) == ["p1", "p2"]

    reopened = Tags(database)
    assert reopened.find("cafe\u0300 strasse") == ["p1", "p2", "p3"]
    assert reopened.for_photo("p1") == ["Cafè Straße", "Giappone"]
    assert reopened.for_photo("p3") == ["Cafè Straße"]
    assert reopened.remove("gIaPpOnE", ["missing", "p1", "p1"]) == ["p1"]
    assert reopened.find("Giappone") == ["p2"]
    assert reopened.for_photo("p1") == ["Cafè Straße"]


def test_a_failed_bulk_write_leaves_no_partial_change(tmp_path):
    database = tmp_path / "tags.sqlite"
    tags = Tags(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""
            CREATE TRIGGER refuse_picture BEFORE INSERT ON photo_tags
            WHEN NEW.photo_id = 'refused' BEGIN SELECT RAISE(ABORT, 'refused'); END
        """)

    with pytest.raises(sqlite3.IntegrityError, match="refused"):
        tags.add("Giappone", ["first", "refused"])
    assert tags.find("Giappone") == []
    assert tags.add("GIAPPONE", ["first"]) == ["first"]
    assert tags.for_photo("first") == ["GIAPPONE"]

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""
            CREATE TRIGGER refuse_removal BEFORE DELETE ON photo_tags
            WHEN OLD.photo_id = 'second' BEGIN SELECT RAISE(ABORT, 'refused'); END
        """)
    assert tags.add("Giappone", ["second"]) == ["second"]
    with pytest.raises(sqlite3.IntegrityError, match="refused"):
        tags.remove("Giappone", ["first", "second"])
    assert tags.find("Giappone") == ["first", "second"]
