"""Keep a validated original in the configured import folder without overwriting files."""
import os
import json
from pathlib import Path
import shutil
import tempfile

from PIL import Image

from photo_annotator import VERSION
from photo_catalog import fingerprint


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
