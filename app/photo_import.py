"""Keep a validated original in the configured import folder without overwriting files."""
import os
import json
from pathlib import Path
import shutil
import tempfile
import hashlib
import zipfile
import zlib

from PIL import Image

from photo_annotator import VERSION
from photo_catalog import fingerprint


class RestoreBackupError(ValueError):
    """The original is already backed up, but a local catalog copy could not be created."""


def restore_backup(catalog, sha: str, import_dir: Path, name: str = '') -> dict | None:
    """Restore only a verified original member, never extract archive-supplied filesystem paths.

    Missing/corrupt ZIPs require another transfer. Once the ZIP is valid, disk/decoder
    failures are reported explicitly rather than asking the phone to resend the same bytes.
    """
    try:
        archive_path = catalog.archive.path(sha)
    except ValueError as error:
        raise RestoreBackupError('Percorso del backup non disponibile sul PC.') from error
    try:
        if not archive_path.exists():
            return None
    except OSError as error:
        raise RestoreBackupError('Il backup è sul PC, ma non è accessibile. Controlla i permessi sul PC.') from error
    partial = None
    try:
        with catalog.archive.lock:
            try:
                manifest = catalog.archive.inspect(archive_path, sha)
            except (ValueError, KeyError, zipfile.BadZipFile, EOFError, zlib.error):
                return None
            staging = catalog.database.parent / 'catalog-staging'
            staging.mkdir(parents=True, exist_ok=True)
            descriptor, filename = tempfile.mkstemp(prefix='restore-', suffix='.part', dir=staging)
            partial = Path(filename)
            digest, size = hashlib.sha256(), 0
            with os.fdopen(descriptor, 'wb') as output:
                try:
                    with zipfile.ZipFile(archive_path) as archive, archive.open(manifest['original']) as original:
                        for chunk in iter(lambda: original.read(1024 * 1024), b''):
                            digest.update(chunk)
                            size += len(chunk)
                            output.write(chunk)
                except (KeyError, zipfile.BadZipFile, EOFError, zlib.error):
                    return None
                output.flush()
                os.fsync(output.fileno())
            if size != manifest['size'] or digest.hexdigest() != sha:
                return None
        # Do not hold the archive lock while keep() takes the import lock: normal
        # uploads acquire those locks in the opposite order.
        original_name = name or manifest['filename']
        result = keep(catalog, partial, import_dir, original_name)
        if result['id'] != sha:
            raise RestoreBackupError('La copia ripristinata non corrisponde al backup.')
        return {**result, 'restored_from_backup': True}
    except RestoreBackupError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise RestoreBackupError('Originale già salvato nello ZIP, ma ripristino locale non riuscito: '
                                 'controlla spazio, permessi e formato sul PC. Nessun nuovo trasferimento richiesto.') from error
    finally:
        if partial is not None:
            try:
                partial.unlink(missing_ok=True)
            except OSError as error:
                raise RestoreBackupError('Ripristino dal backup interrotto: controlla i permessi della cartella temporanea sul PC. Nessun nuovo trasferimento richiesto.') from error


def image_extension(source: Path, name: str = '') -> str:
    try:
        with Image.open(source) as image:
            extension = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'TIFF': '.tiff', 'BMP': '.bmp', 'GIF': '.gif', 'AVIF': '.avif'}[image.format]
            image.verify()
            return extension
    except (OSError, ValueError, KeyError):
        # Preserve originals that Pillow cannot decode; they stay explicitly excluded from AI.
        suffix = Path(name).suffix.lower()
        with source.open('rb') as file:
            header = file.read(64)
        if suffix in {'.heic', '.heif'} and len(header) >= 12 and header[4:8] == b'ftyp' and any(brand in header[8:] for brand in (b'heic', b'heix', b'hevc', b'hevx', b'mif1', b'msf1')):
            return suffix
        if suffix in {'.dng', '.nef', '.arw', '.cr2'} and header.startswith((b'II*\x00', b'MM\x00*')):
            return suffix
        raise ValueError('Formato non riconosciuto o immagine corrotta.')


def keep(catalog, source: Path, import_dir: Path, name: str = '') -> dict:
    extension = image_extension(source, name)
    sha = fingerprint(source)
    with catalog.import_lock:
        # The original ZIP must exist and be readable before acknowledging even a duplicate.
        catalog.archive.ensure(source, sha, name or sha + extension, verify=True)
        existing = catalog.verified_path_of(sha)
        duplicate = existing is not None
        if not duplicate:
            import_dir.mkdir(parents=True, exist_ok=True)
            root_id = catalog.add_root(import_dir, 'Dal telefono e allegati')
            root = next(item for item in catalog.roots(local=True) if item['id'] == root_id)
            pending = import_dir / 'Da catalogare'
            if pending.resolve() != pending:
                raise ValueError('La cartella di importazione contiene un collegamento non autorizzato.')
            destination = catalog.safe_path(root_id, (pending / (sha + extension)).relative_to(root['path']).as_posix())
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, landed = tempfile.mkstemp(suffix='.part', dir=import_dir)
            try:
                with os.fdopen(fd, 'wb') as target, source.open('rb') as original:
                    shutil.copyfileobj(original, target)
                    target.flush()
                    os.fsync(target.fileno())
                if fingerprint(Path(landed)) != sha:
                    raise ValueError('File modificato durante la copia.')
                if destination.exists():
                    if fingerprint(destination) != sha:
                        raise ValueError('Destinazione già presente con contenuto diverso.')
                else:
                    os.rename(landed, destination)
                catalog.register(root_id, destination, VERSION, force_hash=True)
                with catalog.connect() as db:
                    db.execute('INSERT INTO managed_imports VALUES (?,?,?) ON CONFLICT(asset_id) DO NOTHING',
                               (sha, root_id, import_dir.relative_to(root['path']).as_posix()))
                if name:
                    original_name = Path(name).name
                    _, _, notes = catalog.metadata(destination, original_name)
                    notes['original_filename'] = original_name
                    notes['path_hint'] = destination.relative_to(root['path']).as_posix()
                    if notes['date_source'] == 'path':
                        notes['date_source'] = 'phone_filename'
                    with catalog.connect() as db:
                        db.execute('UPDATE file_locations SET metadata=? WHERE root_id=? AND relative=?',
                                   (json.dumps(notes, ensure_ascii=False), root_id, notes['path_hint']))
            finally:
                Path(landed).unlink(missing_ok=True)
        return {'kept': True, 'duplicate': duplicate, 'id': sha, 'tagging': 'paused'}
