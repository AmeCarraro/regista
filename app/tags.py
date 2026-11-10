"""Manual photo tags, keyed by the IDs supplied by the photo library."""

from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
import sqlite3
import unicodedata


def _name(tag: str) -> tuple[str, str]:
    display = " ".join(tag.split())
    if not display:
        raise ValueError("Il tag non può essere vuoto.")
    normalized = unicodedata.normalize("NFKC", display)
    return unicodedata.normalize("NFKC", normalized.casefold()), display


class Tags:
    def __init__(self, database: str | Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS tag_names (
                    key TEXT PRIMARY KEY NOT NULL,
                    display TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS photo_tags (
                    photo_id TEXT NOT NULL,
                    tag TEXT NOT NULL REFERENCES tag_names(key),
                    PRIMARY KEY (photo_id, tag)
                );
                CREATE INDEX IF NOT EXISTS photos_by_tag ON photo_tags(tag, photo_id);
            """)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def add(self, tag: str, photo_ids: Iterable[str]) -> list[str]:
        """Add one tag to the selection in one transaction and return the IDs changed."""
        key, display = _name(tag)
        identifiers = self._identifiers(photo_ids)
        if not identifiers:
            return []
        changed = []
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO tag_names VALUES (?, ?) ON CONFLICT(key) DO NOTHING", (key, display)
            )
            for identifier in identifiers:
                result = connection.execute(
                    "INSERT INTO photo_tags VALUES (?, ?) ON CONFLICT(photo_id, tag) DO NOTHING", (identifier, key)
                )
                if result.rowcount:
                    changed.append(identifier)
        return changed

    def remove(self, tag: str, photo_ids: Iterable[str]) -> list[str]:
        """Remove one tag from the selection in one transaction and return the IDs changed."""
        key, _ = _name(tag)
        identifiers = self._identifiers(photo_ids)
        if not identifiers:
            return []
        changed = []
        with closing(self._connect()) as connection, connection:
            for identifier in identifiers:
                result = connection.execute("DELETE FROM photo_tags WHERE photo_id = ? AND tag = ?", (identifier, key))
                if result.rowcount:
                    changed.append(identifier)
        return changed

    @staticmethod
    def _identifiers(photo_ids: Iterable[str]) -> tuple[str, ...]:
        identifiers = tuple(dict.fromkeys(photo_ids))
        if any(not identifier.strip() for identifier in identifiers):
            raise ValueError("L'identificativo della foto non può essere vuoto.")
        return identifiers

    def find(self, tag: str) -> list[str]:
        key, _ = _name(tag)
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT photo_id FROM photo_tags WHERE tag = ? ORDER BY photo_id", (key,))
            return [photo_id for (photo_id,) in rows]

    def for_photo(self, photo_id: str) -> list[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute("""
                SELECT tag_names.display FROM photo_tags JOIN tag_names ON tag_names.key = photo_tags.tag
                WHERE photo_tags.photo_id = ? ORDER BY tag_names.key
            """, (photo_id,))
            return [display for (display,) in rows]
