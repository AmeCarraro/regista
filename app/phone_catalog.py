"""Portable, sanitized SQLite snapshot for offline Android searches. No model calls."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from fastapi.responses import FileResponse

from photo_annotator import COUNT_FORMS, COUNTS
from photo_catalog import CLASSIFICATION_SQL
from photo_search import SYNONYMS

SNAPSHOT_VERSION = 1
METADATA = ('date', 'precision', 'date_source', 'place', 'city', 'country', 'place_source',
            'media_kind', 'original_filename', 'source_folder', 'source_folders')


class SnapshotResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            Path(self.path).unlink(missing_ok=True)


def snapshot(catalog, device: str) -> Path:
    with tempfile.NamedTemporaryFile(prefix='regista-catalog-', suffix='.sqlite', delete=False) as temporary:
        path = Path(temporary.name)
    try:
        with closing(sqlite3.connect(path)) as target, catalog.connect() as source:
            target.executescript('''
                PRAGMA journal_mode=DELETE;
                PRAGMA user_version=1;
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE photos(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,
                    metadata TEXT NOT NULL,tags TEXT NOT NULL,day TEXT NOT NULL,stage TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'image');
                CREATE INDEX photos_day ON photos(day DESC,id);
                CREATE VIRTUAL TABLE search_text USING fts4(id,body,notindexed=id,tokenize=unicode61);
                CREATE TABLE phone_media(asset_id TEXT NOT NULL,media TEXT NOT NULL,stamp TEXT NOT NULL);
                CREATE INDEX phone_media_asset ON phone_media(asset_id);
                CREATE TABLE albums(id TEXT PRIMARY KEY,name TEXT NOT NULL,hidden INTEGER NOT NULL);
                CREATE TABLE album_items(album_id TEXT NOT NULL,asset_id TEXT NOT NULL,PRIMARY KEY(album_id,asset_id));
                CREATE TABLE hidden_media(asset_id TEXT PRIMARY KEY);
            ''')
            # FTS5's asset_id and import hashes are not indexed for this join. Materialize
            # indexed TEMP projections once, avoiding a full-library scan for every photo.
            source.executescript('''CREATE TEMP TABLE snapshot_text(asset_id TEXT PRIMARY KEY,body TEXT);
                CREATE TEMP TABLE snapshot_media(asset_id TEXT,media TEXT,stamp TEXT);
                CREATE INDEX snapshot_media_asset ON snapshot_media(asset_id);''')
            source.execute('BEGIN')
            source.execute('INSERT INTO snapshot_text SELECT asset_id,body FROM search_text')
            source.execute("INSERT INTO snapshot_media SELECT sha256,media,stamp FROM phone_import_items WHERE device=? AND state='received'", (device,))
            source.execute('INSERT INTO snapshot_media SELECT asset_id,media,stamp FROM import_receipts WHERE device=?', (device,))
            target.executemany('INSERT INTO albums VALUES (?,?,?)', (tuple(row) for row in source.execute('SELECT id,name,hidden FROM collections')))
            target.executemany('INSERT INTO album_items VALUES (?,?)', (tuple(row) for row in source.execute('SELECT collection_id,asset_id FROM collection_items')))
            target.executemany('INSERT INTO hidden_media VALUES (?)', (tuple(row) for row in source.execute('SELECT asset_id FROM hidden_media')))
            rows = source.execute(f'''SELECT a.id,l.relative,l.metadata,
                coalesce((SELECT description FROM annotations WHERE asset_id=a.id ORDER BY id DESC LIMIT 1),'') description,
                coalesce(s.body,'') body,
                ({CLASSIFICATION_SQL}) stage
                FROM assets a JOIN file_locations l ON l.id=(SELECT id FROM file_locations
                    WHERE asset_id=a.id AND present=1 ORDER BY relative,id LIMIT 1)
                LEFT JOIN snapshot_text s ON s.asset_id=a.id ORDER BY a.id''')
            count = 0
            for row in rows:
                notes = json.loads(row['metadata'])
                safe_notes = {key: notes[key] for key in METADATA if key in notes}
                tags = catalog.effective_tags(source, row['id'])
                cursor = target.execute('INSERT INTO photos VALUES (?,?,?,?,?,?,?,?)', (
                    row['id'], notes.get('original_filename') or Path(row['relative']).name, row['description'], json.dumps(safe_notes, ensure_ascii=False),
                    json.dumps(tags, ensure_ascii=False), notes.get('date', ''), row['stage'], notes.get('media_kind','image')))
                searchable_metadata = ' '.join(str(notes.get(key, '')) for key in ('date', 'place', 'city', 'country', 'source_folder'))
                target.execute('INSERT INTO search_text(docid,id,body) VALUES (?,?,?)',
                               (cursor.lastrowid, row['id'], row['body'] + ' ' + searchable_metadata))
                target.executemany('INSERT INTO phone_media VALUES (?,?,?)', (
                    (row['id'], item['media'], item['stamp']) for item in source.execute(
                        'SELECT media,stamp FROM snapshot_media WHERE asset_id=?', (row['id'],))))
                count += 1
            meta = {'version': SNAPSHOT_VERSION, 'created_ms': int(time.time() * 1000), 'count': count,
                    'synonyms': SYNONYMS, 'counts': {key: COUNTS[value] for key, value in COUNT_FORMS.items()}}
            target.executemany('INSERT INTO meta VALUES (?,?)',
                               ((key, json.dumps(value, ensure_ascii=False)) for key, value in meta.items()))
            target.commit()
            if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Catalogo portatile non valido.')
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise
