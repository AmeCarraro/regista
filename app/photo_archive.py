"""Content-addressed, verified ZIP originals, independent of catalog annotations."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import threading
import time
import uuid
import zipfile

from photo_files import move_new


class OriginalArchive:
    def __init__(self, catalog):
        self.catalog = catalog
        self.root = catalog.database.parent.resolve() / 'backup-originali'
        self.lock = threading.RLock()

    def path(self, sha):
        if not re.fullmatch('[a-f0-9]{64}', sha):
            raise ValueError('Identità originale non valida.')
        target = self.root / sha[:2] / (sha + '.zip')
        if self.root.resolve() != self.root.absolute() or not target.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Archivio fuori dalla cartella di backup.')
        return target

    def inspect(self, path, sha):
        with zipfile.ZipFile(path) as archive:
            if archive.getinfo('manifest.json').file_size > 65536:
                raise ValueError('Manifest del backup non valido.')
            manifest = json.loads(archive.read('manifest.json'))
            member = manifest['original']
            if manifest['sha256'] != sha or not member.startswith('original/') or '..' in Path(member).parts:
                raise ValueError('Identità del backup non corrispondente.')
            item = archive.getinfo(member)
            if item.file_size != manifest['size']:
                raise ValueError('Dimensione del backup non corrispondente.')
            digest = hashlib.sha256()
            with archive.open(item) as original:
                for chunk in iter(lambda: original.read(1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != sha:
                raise ValueError('SHA-256 del backup non corrispondente.')
        return manifest

    def _remember(self, sha, path, manifest):
        stamp = path.stat()
        with self.catalog.connect() as db:
            db.execute('''INSERT INTO original_backups VALUES (?,?,?,?,?,?) ON CONFLICT(asset_id)
                DO UPDATE SET relative=excluded.relative,original_size=excluded.original_size,
                archive_size=excluded.archive_size,mtime_ns=excluded.mtime_ns,verified_at=excluded.verified_at''',
                       (sha, path.relative_to(self.root).as_posix(), manifest['size'], stamp.st_size, stamp.st_mtime_ns, time.time()))
            db.execute('DELETE FROM archive_errors WHERE asset_id=?', (sha,))

    def ensure(self, source, sha, name='', *, verify=False):
        """Never acknowledge an import or relocate its working copy before this succeeds."""
        with self.lock:
            try:
                return self._ensure(Path(source), sha, name, verify)
            except Exception as error:
                with self.catalog.connect() as db:
                    db.execute('INSERT INTO archive_errors VALUES (?,?,?) ON CONFLICT(asset_id) DO UPDATE SET error=excluded.error,created=excluded.created',
                               (sha, f'Backup originale: {type(error).__name__}: {error}'[:1000], time.time()))
                raise

    def _ensure(self, source, sha, name, verify):
        destination = self.path(sha)
        with self.catalog.connect() as db:
            known = db.execute('SELECT * FROM original_backups WHERE asset_id=?', (sha,)).fetchone()
        if destination.is_file():
            stamp = destination.stat()
            if not verify and known and (known['archive_size'], known['mtime_ns']) == (stamp.st_size, stamp.st_mtime_ns):
                with self.catalog.connect() as db:
                    db.execute('DELETE FROM archive_errors WHERE asset_id=?', (sha,))
                return destination
            try:
                manifest = self.inspect(destination, sha)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, EOFError):
                pass  # Replace only after a new archive has been fully verified; retain the damaged archive.
            else:
                self._remember(sha, destination, manifest)
                return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=sha + '-', suffix='.part', dir=destination.parent)
        os.close(descriptor)
        temporary = Path(temporary)
        filename = Path(PureWindowsPath(name or source.name).name).name
        manifest = {'version': 1, 'sha256': sha, 'filename': filename, 'original': 'original/' + filename,
                    'size': source.stat().st_size, 'created_utc': datetime.now(timezone.utc).isoformat()}
        try:
            digest, size = hashlib.sha256(), 0
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
                with source.open('rb') as original, archive.open(manifest['original'], 'w', force_zip64=True) as target:
                    for chunk in iter(lambda: original.read(1024 * 1024), b''):
                        digest.update(chunk)
                        size += len(chunk)
                        target.write(chunk)
                if digest.hexdigest() != sha or size != manifest['size']:
                    raise ValueError('Originale modificato durante il backup.')
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
            self.inspect(temporary, sha)
            with temporary.open('r+b') as stored:
                os.fsync(stored.fileno())
            if destination.exists():
                try:
                    landed = self.inspect(destination, sha)
                except (OSError, ValueError, KeyError, zipfile.BadZipFile, EOFError):
                    destination.rename(destination.with_name(sha + '.corrotto-' + uuid.uuid4().hex + '.zip'))
                else:
                    self._remember(sha, destination, landed)
                    return destination
            try:
                move_new(temporary, destination)
            except FileExistsError:
                manifest = self.inspect(destination, sha)
            manifest = self.inspect(destination, sha)
            self._remember(sha, destination, manifest)
            return destination
        finally:
            temporary.unlink(missing_ok=True)
