"""Persistent, content-addressed photo library. Scanning never calls a model."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
import unicodedata
import uuid

from PIL import Image

VIDEO_FORMATS = {'.mp4', '.m4v', '.mov', '.3gp', '.3g2', '.webm', '.mkv', '.avi', '.mts', '.m2ts', '.mpeg', '.mpg', '.wmv', '.ts', '.vob', '.ogv', '.flv', '.divx'}
FORMATS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.gif', '.avif', '.heic', '.heif', '.dng', '.nef', '.arw', '.cr2'} | VIDEO_FORMATS
ARCHIVE_FORMATS = {'.heic', '.heif', '.avif', '.dng', '.nef', '.arw', '.cr2', '.cr3', '.raf', '.rw2', '.orf', '.pef', '.srw'}
FORMATS |= ARCHIVE_FORMATS
EXCLUDED = {'.regista', '.git', '.cache', '__pycache__', '$recycle.bin', 'system volume information', 'raccolte', 'output'}

CLASSIFICATION_SQL = '''CASE WHEN a.excluded_reason!='' OR EXISTS(SELECT 1 FROM archive_errors e WHERE e.asset_id=a.id)
    OR (SELECT state FROM jobs j WHERE j.asset_id=a.id ORDER BY j.id DESC LIMIT 1)='error' THEN 'needs_review'
    WHEN EXISTS(SELECT 1 FROM annotations n WHERE n.asset_id=a.id) THEN 'classified' ELSE 'pending' END'''


def normalized(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class PhotoCatalog:
    def __init__(self, database: str | Path, places=None, *, organize_imports=True):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.places = places
        self.organize_imports = organize_imports
        self.scan_lock = threading.Lock()
        self.import_lock = threading.Lock()
        self.scanning = False
        self.scan_error = ''
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            existing_version = version
            if version > 3:
                raise RuntimeError('Catalogo creato da una versione più recente di Regista.')
            db.execute('PRAGMA journal_mode=WAL')
            if version == 0:
                db.executescript('''
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS library_roots (
                        id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, label TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS assets (
                        id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, format TEXT NOT NULL,
                        width INTEGER NOT NULL, height INTEGER NOT NULL, created REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS file_locations (
                        id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),
                        root_id TEXT NOT NULL REFERENCES library_roots(id), relative TEXT NOT NULL,
                        size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, present INTEGER NOT NULL,
                        metadata TEXT NOT NULL, UNIQUE(root_id, relative));
                    CREATE INDEX IF NOT EXISTS locations_asset ON file_locations(asset_id, present);
                    CREATE TABLE IF NOT EXISTS annotations (
                        id INTEGER PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),
                        version TEXT NOT NULL, model TEXT NOT NULL, digest TEXT NOT NULL,
                        quantization TEXT NOT NULL, prompt_version TEXT NOT NULL, schema_version TEXT NOT NULL,
                        description TEXT NOT NULL, result TEXT NOT NULL, seconds REAL NOT NULL,
                        created REAL NOT NULL, UNIQUE(asset_id, version));
                    CREATE TABLE IF NOT EXISTS asset_tags (
                        annotation_id INTEGER NOT NULL REFERENCES annotations(id), tag TEXT NOT NULL,
                        category TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'qwen',
                        PRIMARY KEY(annotation_id, tag));
                    CREATE TABLE IF NOT EXISTS overrides (
                        asset_id TEXT NOT NULL REFERENCES assets(id), tag TEXT NOT NULL,
                        included INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'user',
                        PRIMARY KEY(asset_id, tag));
                    CREATE TABLE IF NOT EXISTS jobs (
                        id INTEGER PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),
                        version TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                        next_run REAL NOT NULL DEFAULT 0, lease TEXT, lease_until REAL, error TEXT NOT NULL DEFAULT '',
                        UNIQUE(asset_id, version));
                    CREATE TABLE IF NOT EXISTS import_receipts (
                        device TEXT NOT NULL, media TEXT NOT NULL, stamp TEXT NOT NULL,
                        asset_id TEXT NOT NULL REFERENCES assets(id), PRIMARY KEY(device, media));
                    CREATE TABLE IF NOT EXISTS phone_import_requests (
                        device TEXT PRIMARY KEY, request_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'requested',
                        total INTEGER NOT NULL DEFAULT 0, copied INTEGER NOT NULL DEFAULT 0,
                        duplicates INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
                    CREATE VIRTUAL TABLE IF NOT EXISTS search_text USING fts5(asset_id UNINDEXED, body, tokenize='unicode61 remove_diacritics 2');
                    PRAGMA user_version=1;
                    COMMIT;
                ''')
                version = 1
            if version == 1:
                backup = self.database.with_name(self.database.stem + '.before-v2.sqlite')
                if existing_version and not backup.exists():
                    with sqlite3.connect(backup) as target:
                        db.backup(target)
                db.execute('BEGIN IMMEDIATE')
                db.execute('''CREATE TABLE IF NOT EXISTS phone_import_requests (
                    device TEXT PRIMARY KEY, request_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'requested',
                    total INTEGER NOT NULL DEFAULT 0, copied INTEGER NOT NULL DEFAULT 0,
                    duplicates INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '')''')
                if 'excluded_reason' not in {row['name'] for row in db.execute('PRAGMA table_info(assets)')}:
                    db.execute("ALTER TABLE assets ADD COLUMN excluded_reason TEXT NOT NULL DEFAULT ''")
                db.execute('PRAGMA user_version=2')
                version = 2
            if version == 2:
                backup = self.database.with_name(self.database.stem + '.before-v3.sqlite')
                if existing_version and not backup.exists():
                    # Commit the preceding migration before SQLite copies its consistent state.
                    db.commit()
                    with sqlite3.connect(backup) as target:
                        db.backup(target)
                db.executescript('''BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS original_backups(asset_id TEXT PRIMARY KEY,relative TEXT NOT NULL,
                        original_size INTEGER NOT NULL,archive_size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL,verified_at REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS archive_errors(asset_id TEXT PRIMARY KEY,error TEXT NOT NULL,created REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS managed_imports(asset_id TEXT PRIMARY KEY REFERENCES assets(id),
                        root_id TEXT NOT NULL REFERENCES library_roots(id),base_relative TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS phone_import_items(device TEXT NOT NULL,media TEXT NOT NULL,stamp TEXT NOT NULL,
                        sha256 TEXT NOT NULL,name TEXT NOT NULL DEFAULT '',state TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY(device,media));
                    PRAGMA user_version=3; COMMIT;''')
        from photo_archive import OriginalArchive
        self.archive = OriginalArchive(self)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS collections(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT NOT NULL UNIQUE,hidden INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_items(collection_id TEXT NOT NULL REFERENCES collections(id),
                asset_id TEXT NOT NULL REFERENCES assets(id),PRIMARY KEY(collection_id,asset_id));
                CREATE TABLE IF NOT EXISTS hidden_media(asset_id TEXT PRIMARY KEY REFERENCES assets(id));
                CREATE TABLE IF NOT EXISTS bulk_previews(id TEXT PRIMARY KEY,created REAL NOT NULL,payload TEXT NOT NULL);''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_root(self, path: str | Path, label: str = '') -> str:
        root = Path(path).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Scegli una cartella esistente.')
        with self.connect() as db:
            for existing in db.execute('SELECT id,path FROM library_roots'):
                known = Path(existing['path'])
                if root.is_relative_to(known):
                    return existing['id']
                if known.is_relative_to(root):
                    raise ValueError('La cartella contiene una radice già autorizzata: scegli cartelle indipendenti.')
            db.execute('INSERT OR IGNORE INTO library_roots VALUES (?, ?, ?)',
                       (uuid.uuid4().hex, str(root), label.strip()[:100] or root.name))
            return db.execute('SELECT id FROM library_roots WHERE path=?', (str(root),)).fetchone()[0]

    def roots(self, local: bool = False) -> list[dict]:
        with self.connect() as db:
            return [{key: row[key] for key in (('id', 'label', 'path') if local else ('id', 'label'))}
                    for row in db.execute('SELECT * FROM library_roots ORDER BY label')]

    def verified_path_of(self, asset_id):
        with self.connect() as db:
            locations = db.execute('SELECT * FROM file_locations WHERE asset_id=? AND present=1', (asset_id,)).fetchall()
        for location in locations:
            try:
                path = self.safe_path(location['root_id'], location['relative'])
                if not path.is_file():
                    continue
                if fingerprint(path) == asset_id:
                    return path
            except OSError:
                continue
            # A changed working file must never acknowledge a duplicate of its old content.
            with self.connect() as db:
                db.execute('UPDATE file_locations SET present=0 WHERE id=?', (location['id'],))
        return None

    def safe_path(self, root_id: str, relative: str) -> Path:
        with self.connect() as db:
            row = db.execute('SELECT path FROM library_roots WHERE id=?', (root_id,)).fetchone()
        if row is None:
            raise FileNotFoundError('Radice non autorizzata.')
        authorized = Path(row[0])
        root = authorized.resolve()
        if root != authorized:
            raise FileNotFoundError('La radice è stata sostituita con un collegamento: autorizzala di nuovo.')
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or EXCLUDED.intersection(part.casefold() for part in Path(relative).parts):
            raise FileNotFoundError('Foto fuori dalla radice autorizzata.')
        return path

    def path_of(self, asset_id: str) -> Path | None:
        with self.connect() as db:
            locations = db.execute('SELECT * FROM file_locations WHERE asset_id=? AND present=1', (asset_id,)).fetchall()
        for location in locations:
            try:
                path = self.safe_path(location['root_id'], location['relative'])
                stat = path.stat()
                if stat.st_size == location['size'] and stat.st_mtime_ns == location['mtime_ns']:
                    return path
            except OSError:
                pass
        return None

    def metadata(self, path: Path, relative: str) -> tuple[int, int, dict]:
        notes = {'path_hint': relative, 'file_mtime': path.stat().st_mtime,
                 'date': '', 'date_source': '', 'precision': '', 'place': '', 'place_source': '', 'conflicts': []}
        notes['media_kind'] = 'video' if path.suffix.lower() in VIDEO_FORMATS else 'image'
        if notes['media_kind'] == 'video':
            try:
                from video_tools import probe
                width, height, details = probe(path)
                notes.update(details)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                width = height = 0
                notes['read_error'] = str(error)[:500]
            return width, height, notes
        width = height = 0
        try:
            with Image.open(path) as image:
                width, height = image.size
                exif = image.getexif()
                original = exif.get_ifd(0x8769).get(36867) or exif.get(36867)
                if original:
                    notes['date_original'] = str(original)
                    try:
                        notes['date'] = datetime.strptime(str(original)[:19], '%Y:%m:%d %H:%M:%S').date().isoformat()
                        notes.update(date_source='exif', precision='day')
                    except ValueError:
                        notes['conflicts'].append('DateTimeOriginal non valida')
                notes['timezone'] = str(exif.get_ifd(0x8769).get(36881, ''))
            from places import position_of
            position = position_of(path)
            if position:
                notes['gps'] = position
                notes['place_source'] = 'gps'
                if self.places:
                    country, region = self.places.where(position)
                    notes.update(place=self.places.country_name(country) if country else '', country=country, region=region)
                    if self.places.known:
                        from places import _distances, NEAR
                        distances = _distances(*position, self.places.latitudes, self.places.longitudes)
                        nearest = int(distances.argmin())
                        if distances[nearest] <= NEAR:
                            notes['city'] = self.places.names[nearest]
        except (OSError, ValueError, TypeError, SyntaxError, Image.DecompressionBombError) as error:
            notes['read_error'] = type(error).__name__
        # A path is an explicitly labelled clue, never geographic proof or an invented full date.
        date_hint = re.sub(r'(?i)\b[a-f0-9]{64}\b', '', relative)
        match = re.search(r'(?<!\d)((?:19|20)\d{2})(?:[-_./]?(0[1-9]|1[0-2]))?(?:[-_./]?(0[1-9]|[12]\d|3[01]))?(?!\d)', date_hint)
        if match:
            clue = '-'.join(part for part in match.groups() if part)
            try:
                datetime.strptime(clue, {4: '%Y', 7: '%Y-%m', 10: '%Y-%m-%d'}[len(clue)])
                notes['path_date'] = clue
                if not notes['date']:
                    notes.update(date=clue, date_source='path', precision={4: 'year', 7: 'month', 10: 'day'}[len(clue)])
                elif not notes['date'].startswith(clue):
                    notes['conflicts'].append('Data EXIF diversa dalla data nel percorso')
            except ValueError:
                pass
        return width, height, notes

    def register(self, root_id: str, path: Path, version: str, *, force_hash: bool = False) -> tuple[str, bool]:
        cached = None
        with self.connect() as db:
            root = Path(db.execute('SELECT path FROM library_roots WHERE id=?', (root_id,)).fetchone()[0])
            relative = path.relative_to(root).as_posix()
            before = path.stat()
            old = db.execute('SELECT * FROM file_locations WHERE root_id=? AND relative=?', (root_id, relative)).fetchone()
            if not force_hash and old and old['size'] == before.st_size and old['mtime_ns'] == before.st_mtime_ns:
                db.execute('UPDATE file_locations SET present=1 WHERE id=?', (old['id'],))
                if not db.execute('SELECT 1 FROM annotations WHERE asset_id=?', (old['asset_id'],)).fetchone():
                    asset = db.execute('SELECT excluded_reason FROM assets WHERE id=?', (old['asset_id'],)).fetchone()
                    if asset and not asset[0]:
                        db.execute('INSERT OR IGNORE INTO jobs(asset_id,version) VALUES (?,?)', (old['asset_id'], version))
                cached = old['asset_id']
        if cached:
            self.archive.ensure(path, cached)
            return cached, False
        sha = fingerprint(path)
        width, height, notes = self.metadata(path, relative)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OSError('File in scrittura: verrà letto alla prossima scansione.')
        with self.connect() as db:
            excluded = 'Originale conservato: decoder del formato non disponibile.' if path.suffix.lower() in ARCHIVE_FORMATS and not width else ''
            db.execute('INSERT OR IGNORE INTO assets(id,sha256,format,width,height,created,excluded_reason) VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (sha, sha, path.suffix.lower(), width, height, time.time(), excluded))
            db.execute('''INSERT INTO file_locations VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(root_id, relative) DO UPDATE SET asset_id=excluded.asset_id, size=excluded.size,
                mtime_ns=excluded.mtime_ns, present=1, metadata=excluded.metadata''',
                       (uuid.uuid4().hex, sha, root_id, relative, after.st_size, after.st_mtime_ns, json.dumps(notes, ensure_ascii=False)))
            # A version change alone must never enqueue a mass reanalysis.
            known = db.execute('SELECT 1 FROM annotations WHERE asset_id=?', (sha,)).fetchone()
            if not known and not excluded:
                db.execute('INSERT OR IGNORE INTO jobs(asset_id,version) VALUES (?,?)', (sha, version))
            self.refresh_text(db, sha)
        self.archive.ensure(path, sha)
        return sha, True

    def scan(self, version: str, stable_seconds: float = 1.0) -> dict:
        if not self.scan_lock.acquire(blocking=False):
            return {'busy': True}
        self.scanning, self.scan_error = True, ''
        changed, deferred, errors = 0, 0, []
        try:
            for root in self.roots(local=True):
                folder = Path(root['path'])
                if not folder.is_dir():
                    errors.append(f"{root['label']}: cartella non disponibile")
                    continue  # A disconnected disk is not evidence that every photo was deleted.
                seen = set()
                walk_errors = []
                for current, dirs, files in os.walk(folder, followlinks=False, onerror=walk_errors.append):
                    dirs[:] = [name for name in dirs if name.casefold() not in EXCLUDED
                               and not (Path(current) / name).is_symlink()
                               and not (hasattr(os.path, 'isjunction') and os.path.isjunction(Path(current) / name))
                               and not self.database.parent.resolve().is_relative_to((Path(current) / name).resolve())]
                    for name in files:
                        path = Path(current) / name
                        if path.suffix.lower() not in FORMATS or path.is_symlink():
                            continue
                        relative = path.relative_to(folder).as_posix()
                        seen.add(relative)
                        try:
                            path = self.safe_path(root['id'], relative)
                            if time.time_ns() - path.stat().st_mtime_ns < stable_seconds * 1e9:
                                deferred += 1
                                continue
                            _, updated = self.register(root['id'], path, version)
                            changed += int(updated)
                        except (OSError, ValueError) as error:
                            errors.append(f'{name}: {error}')
                if not walk_errors:
                    with self.connect() as db:
                        for row in db.execute('SELECT id, relative FROM file_locations WHERE root_id=?', (root['id'],)).fetchall():
                            if row['relative'] not in seen:
                                db.execute('UPDATE file_locations SET present=0 WHERE id=?', (row['id'],))
                errors.extend(str(error) for error in walk_errors)
            from photo_storage import reconcile
            errors.extend(reconcile(self))
            self.scan_error = '; '.join(errors[:10])
            return {'changed': changed, 'deferred': deferred, 'errors': errors[:20]}
        finally:
            self.scanning = False
            self.scan_lock.release()

    @staticmethod
    def effective_tags(db, asset_id: str) -> list[dict]:
        row = db.execute('SELECT id FROM annotations WHERE asset_id=? ORDER BY id DESC LIMIT 1', (asset_id,)).fetchone()
        tags = {item['tag']: dict(item) for item in db.execute('SELECT tag,category,source FROM asset_tags WHERE annotation_id=?', (row[0],))} if row else {}
        for override in db.execute('SELECT * FROM overrides WHERE asset_id=?', (asset_id,)):
            if override['included']:
                tags[override['tag']] = {'tag': override['tag'], 'category': 'manual', 'source': override['source']}
            else:
                tags.pop(override['tag'], None)
        return list(tags.values())

    def refresh_text(self, db, asset_id: str):
        annotation = db.execute('SELECT description FROM annotations WHERE asset_id=? ORDER BY id DESC LIMIT 1', (asset_id,)).fetchone()
        tags = self.effective_tags(db, asset_id)
        # Rejected terms are removed from descriptions in the searchable projection too.
        description = annotation[0] if annotation else ''
        for row in db.execute('SELECT tag FROM overrides WHERE asset_id=? AND included=0', (asset_id,)):
            from photo_search import variants
            for variant in variants(row[0]):
                description = re.sub(r'(?<!\w)' + re.escape(variant) + r'(?!\w)', ' ', description, flags=re.IGNORECASE)
        db.execute('DELETE FROM search_text WHERE asset_id=?', (asset_id,))
        db.execute('INSERT INTO search_text VALUES (?,?)', (asset_id, description + ' ' + ' '.join(tag['tag'] for tag in tags)))

    def override(self, asset_id: str, tag: str, included: bool, source: str = 'user'):
        tag = normalized(tag)
        if not tag or len(tag) > 100:
            raise ValueError('Tag non valido.')
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM assets WHERE id=?', (asset_id,)).fetchone():
                raise ValueError('Foto non presente.')
            db.execute('INSERT INTO overrides VALUES (?,?,?,?) ON CONFLICT(asset_id,tag) DO UPDATE SET included=excluded.included,source=excluded.source',
                       (asset_id, tag, int(included), source))
            self.refresh_text(db, asset_id)

    def status(self) -> dict:
        with self.connect() as db:
            total = db.execute('SELECT count(DISTINCT asset_id) FROM file_locations WHERE present=1').fetchone()[0]
            annotated = db.execute('''SELECT count(*) FROM assets a WHERE EXISTS(SELECT 1 FROM file_locations l WHERE l.asset_id=a.id AND present=1)
                AND EXISTS(SELECT 1 FROM annotations n WHERE n.asset_id=a.id)''').fetchone()[0]
            counts = {row['state']: row['n'] for row in db.execute('''SELECT state,count(*) n FROM jobs j
                WHERE j.id=(SELECT max(latest.id) FROM jobs latest WHERE latest.asset_id=j.asset_id) GROUP BY state''')}
            missing = db.execute('SELECT count(*) FROM file_locations WHERE present=0').fetchone()[0]
            copies = db.execute('SELECT count(*) FROM file_locations WHERE present=1').fetchone()[0]
            excluded = db.execute("SELECT count(*) FROM assets a WHERE excluded_reason!='' AND EXISTS(SELECT 1 FROM file_locations l WHERE l.asset_id=a.id AND present=1)").fetchone()[0]
            errors = [dict(row) for row in db.execute("""SELECT asset_id,error,attempts FROM jobs j WHERE state='error'
                AND j.id=(SELECT max(latest.id) FROM jobs latest WHERE latest.asset_id=j.asset_id) ORDER BY id DESC LIMIT 20""")]
            classified = db.execute(f'''SELECT count(*) FROM assets a WHERE EXISTS(SELECT 1 FROM file_locations l WHERE l.asset_id=a.id AND present=1)
                AND ({CLASSIFICATION_SQL})='classified' ''').fetchone()[0]
            backup = dict(db.execute('SELECT count(*) count,coalesce(sum(archive_size),0) bytes FROM original_backups').fetchone())
            backup['bytes'] = db.execute('SELECT coalesce(sum(size),0) FROM (SELECT relative,max(archive_size) size FROM original_backups GROUP BY relative)').fetchone()[0]
            backup['archives'] = db.execute('SELECT count(DISTINCT relative) FROM original_backups').fetchone()[0]
            backup['errors'] = db.execute('SELECT count(*) FROM archive_errors').fetchone()[0]
            incoming = db.execute("SELECT count(DISTINCT sha256) FROM phone_import_items WHERE state!='received'").fetchone()[0]
        return {'discovered': total, 'analyzed': annotated, 'pending': counts.get('pending', 0),
                'running': counts.get('running', 0), 'errors': errors, 'failed': counts.get('error', 0),
                'missing': missing, 'copies': copies, 'excluded': excluded, 'coverage': round(100 * classified / total, 1) if total else 0,
                'scanning': self.scanning, 'scan_error': self.scan_error, 'classified': classified,
                'to_catalog': total - classified, 'backup': backup, 'awaiting_transfer': incoming}
