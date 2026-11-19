from contextlib import closing
import asyncio
import json
import sqlite3

from PIL import Image
import pytest

from photo_annotator import VERSION
from photo_catalog import PhotoCatalog, fingerprint
from phone_catalog import SnapshotResponse, snapshot


@pytest.fixture
def catalog(tmp_path):
    root = tmp_path / 'private-pc-folder'
    root.mkdir()
    first = root / 'cats.png'
    Image.new('RGB', (24, 24), 'red').save(first)
    Image.new('RGB', (24, 24), 'blue').save(root / 'dog.png')
    library = PhotoCatalog(tmp_path / 'index' / 'catalog.sqlite')
    library.add_root(root)
    library.scan(VERSION, stable_seconds=0)
    identifier = fingerprint(first)
    library.override(identifier, 'gatti', True)
    library.override(identifier, 'due gatti', True)
    library.override(identifier, 'cane', True)
    with library.connect() as db:
        row = db.execute('SELECT metadata FROM file_locations WHERE asset_id=?', (identifier,)).fetchone()
        notes = {**json.loads(row[0]), 'date': '2025-03', 'place': 'Roma', 'place_source': 'gps',
                 'private_path': str(root), 'credentials': 'must-not-leave-the-pc'}
        db.execute('UPDATE file_locations SET metadata=? WHERE asset_id=?', (json.dumps(notes), identifier))
        db.executemany('INSERT INTO phone_import_items VALUES (?,?,?,?,?,?,?)', [
            ('phone-one', '12', 'strong-identity-12', identifier, 'cats.png', 'received', ''),
            ('phone-two', '99', 'other-phone', identifier, 'cats.png', 'received', ''),
            ('phone-one', '13', 'not-received', identifier, 'cats.png', 'wanted', '')])
    return library, identifier


def test_portable_catalog_has_sanitized_metadata_effective_tags_and_only_this_phones_ids(catalog):
    library, identifier = catalog
    path = snapshot(library, 'phone-one')
    try:
        with closing(sqlite3.connect(path)) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 1
            assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            assert db.execute('SELECT count(*) FROM photos').fetchone()[0] == 2
            assert db.execute('SELECT * FROM phone_media').fetchall() == [(identifier, '12', 'strong-identity-12')]
            notes, tags = db.execute('SELECT metadata,tags FROM photos WHERE id=?', (identifier,)).fetchone()
            assert json.loads(notes)['place'] == 'Roma'
            assert 'private_path' not in json.loads(notes) and 'credentials' not in json.loads(notes)
            assert {tag['tag'] for tag in json.loads(tags)} == {'gatti', 'due gatti', 'cane'}
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert not tables.intersection({'file_locations', 'annotations', 'original_backups', 'phone_import_items'})
            assert 'must-not-leave-the-pc' not in path.read_bytes().decode('utf-8', errors='ignore')
            assert 'private-pc-folder' not in path.read_bytes().decode('utf-8', errors='ignore')
    finally:
        path.unlink()


def test_fts4_search_preserves_count_subject_binding_corrections_and_gps_metadata(catalog):
    library, identifier = catalog
    library.override(identifier, 'cane', False)
    path = snapshot(library, 'phone-one')
    try:
        with closing(sqlite3.connect(path)) as db:
            def found(expression):
                return db.execute('SELECT id FROM search_text WHERE search_text MATCH ?', (expression,)).fetchall()
            assert found('"due gatti" OR "2 gatti"') == [(identifier,)]
            assert found('"due cani" OR "2 cani"') == []
            assert found('"cane"') == []
            assert found('"roma"') == [(identifier,)]
            assert found('"2025"') == [(identifier,)]
    finally:
        path.unlink()


def test_snapshot_is_consistent_when_corrections_arrive_during_export(catalog, monkeypatch):
    library, identifier = catalog
    original = library.effective_tags
    changed = False
    def correcting(db, asset):
        nonlocal changed
        if not changed:
            changed = True
            library.override(identifier, 'appena aggiunto', True)
        return original(db, asset)
    monkeypatch.setattr(library, 'effective_tags', correcting)
    path = snapshot(library, 'phone-one')
    try:
        with closing(sqlite3.connect(path)) as db:
            tags = json.loads(db.execute('SELECT tags FROM photos WHERE id=?', (identifier,)).fetchone()[0])
            assert 'appena aggiunto' not in {tag['tag'] for tag in tags}
        with library.connect() as db:
            assert 'appena aggiunto' in {tag['tag'] for tag in original(db, identifier)}
    finally:
        path.unlink()


def test_missing_contents_disappear_from_the_next_snapshot(catalog):
    library, identifier = catalog
    with library.connect() as db:
        db.execute('UPDATE file_locations SET present=0 WHERE asset_id=?', (identifier,))
    path = snapshot(library, 'phone-one')
    try:
        with closing(sqlite3.connect(path)) as db:
            assert db.execute('SELECT count(*) FROM photos').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM phone_media').fetchone()[0] == 0
            assert json.loads(db.execute("SELECT value FROM meta WHERE key='count'").fetchone()[0]) == 1
    finally:
        path.unlink()


def test_temporary_snapshot_is_removed_if_the_phone_disconnects_mid_response(tmp_path):
    path = tmp_path / 'temporary.sqlite'
    path.write_bytes(b'x' * 100_000)
    response = SnapshotResponse(path)
    async def receive():
        return {'type': 'http.request'}
    async def send(message):
        if message['type'] == 'http.response.body':
            raise OSError('phone disconnected')
    with pytest.raises(OSError, match='disconnected'):
        asyncio.run(response({'type': 'http', 'method': 'GET', 'headers': [], 'extensions': {}}, receive, send))
    assert not path.exists()
