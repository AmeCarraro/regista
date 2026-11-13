"""Compatibility bridge for existing thumbnails, proposals, journal and undo."""
import io
import json
from pathlib import Path
import sqlite3

from PIL import Image, ImageOps

from photo_annotator import VERSION
from photo_search import SearchPlan, search
from photos import photo_id


class CatalogLibrary:
    persistent = True

    def __init__(self, catalog, root, index_dir, embedder, places):
        self.catalog = catalog
        self.photos_dir = Path(root).resolve()
        self.index_dir = Path(index_dir)
        self.embedder, self.places = embedder, places  # Legacy transport object, never invoked in this path.

    @property
    def state(self):
        state = self.catalog.status()
        return {'running': state['scanning'], 'total': state['discovered'], 'done': state['discovered'],
                'indexed': state['discovered'], 'analyzed': state['analyzed'], 'coverage': state['coverage']}

    @property
    def photos(self):
        with self.catalog.connect() as db:
            photos = []
            for row in db.execute('SELECT * FROM file_locations WHERE present=1 GROUP BY asset_id'):
                notes = json.loads(row['metadata'])
                position = notes.get('gps', [None, None])
                photos.append({'id': row['asset_id'], 'path': row['relative'], 'day': notes.get('date', ''),
                               'lat': position[0], 'lon': position[1], 'country': notes.get('country', ''), 'region': notes.get('region', '')})
            return photos

    def build(self):
        if self.photos_dir.is_dir():
            self.catalog.add_root(self.photos_dir)
        self.catalog.scan(VERSION)
        self.import_legacy_tags()

    def import_legacy_tags(self):
        source = self.index_dir / 'demo-tags.sqlite'
        if not source.exists():
            return
        # Leave the legacy database intact and keep a consistent SQLite backup once.
        with sqlite3.connect(source) as legacy:
            if not legacy.execute("SELECT 1 FROM sqlite_master WHERE name='photo_tags'").fetchone():
                return
            backup = source.with_name('demo-tags.legacy-backup.sqlite')
            if not backup.exists():
                with sqlite3.connect(backup) as target:
                    legacy.backup(target)
            tags = legacy.execute('SELECT photo_id,tag FROM photo_tags').fetchall()
        with self.catalog.connect() as db:
            mapping = {photo_id(row['relative']): row['asset_id'] for row in db.execute(
                'SELECT l.* FROM file_locations l JOIN library_roots r ON r.id=l.root_id WHERE present=1 AND r.path=?', (str(self.photos_dir),))}
            for old_id, tag in tags:
                if old_id in mapping:
                    db.execute("INSERT OR IGNORE INTO overrides VALUES (?,?,1,'legacy')", (mapping[old_id], tag))
                    self.catalog.refresh_text(db, mapping[old_id])

    def canonical(self, identifier):
        if len(identifier) == 64:
            return identifier
        with self.catalog.connect() as db:
            return next((row['asset_id'] for row in db.execute('SELECT asset_id,relative FROM file_locations l JOIN library_roots r ON r.id=l.root_id WHERE present=1 AND r.path=?', (str(self.photos_dir),))
                         if photo_id(row['relative']) == identifier), identifier)

    def path_of(self, identifier):
        return self.catalog.path_of(self.canonical(identifier))

    def relative_of(self, identifier):
        # Existing Actions are scoped to their original authorized root.
        path = self.path_of(identifier)
        return path.relative_to(self.photos_dir).as_posix() if path and path.is_relative_to(self.photos_dir) else None

    def thumbnail(self, identifier):
        path = self.path_of(identifier)
        if not path:
            return None
        try:
            with Image.open(path) as image:
                picture = ImageOps.exif_transpose(image).convert('RGB')
                picture.thumbnail((384, 384))
                buffer = io.BytesIO()
                picture.save(buffer, 'JPEG', quality=85)
                return buffer.getvalue()
        except (OSError, ValueError):
            return None

    def forget(self, identifiers):
        with self.catalog.connect() as db:
            for identifier in identifiers:
                # A copy in another location remains available under the same content ID.
                for row in db.execute('SELECT * FROM file_locations WHERE asset_id=?', (self.canonical(identifier),)).fetchall():
                    try:
                        exists = self.catalog.safe_path(row['root_id'], row['relative']).is_file()
                    except OSError:
                        exists = False
                    if not exists:
                        db.execute('UPDATE file_locations SET present=0 WHERE id=?', (row['id'],))

    def search(self, description, limit=60, period=None, spot=None):
        terms = [description] if description.strip() else []
        plan = SearchPlan(terms=terms, limit=min(limit, 120), since=period[0] if period else '', until=period[1] if period else '')
        result = search(self.catalog, plan)
        return {'sure': [{**photo, 'score': 1.0} for photo in result['photos']], 'maybe': [],
                'matching': result['total'], 'indexed': result['coverage']['discovered'],
                'partial': result['coverage']['coverage'] < 100}

    def by_kind(self):
        result = {}
        with self.catalog.connect() as db:
            for photo in self.photos:
                tags = self.catalog.effective_tags(db, photo['id'])
                categories = {tag['category'] for tag in tags} or {'in_attesa'}
                for category in categories:
                    group = result.setdefault(category, {'label': {'animal': 'Animali', 'object': 'Oggetti', 'scene': 'Scene',
                        'activity': 'Attività', 'color': 'Colori', 'attribute': 'Attributi', 'manual': 'Tag personali', 'in_attesa': 'In attesa di analisi'}.get(category, category), 'sure': [], 'maybe': []})
                    group['sure'].append({'id': photo['id'], 'name': Path(photo['path']).name, 'day': photo['day'], 'score': 1.0})
        return result

    def twins(self, period=None):
        # Content is already deduplicated. Exact copies can be inspected via /api/catalog/duplicates.
        return []

    def trips(self):
        from trips import trips
        return trips([{**photo, 'name': Path(photo['path']).name} for photo in self.photos
                      if len(photo['day']) == 10 and self.relative_of(photo['id']) is not None], self.places)
