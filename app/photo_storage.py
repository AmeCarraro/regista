"""Relocate only Regista-managed imports; user photo roots retain their layout."""
import json
from pathlib import Path

from photo_catalog import fingerprint
from photo_files import move_new


def adopt(catalog, import_dir):
    """Recognize the previous importer's SHA filenames, without claiming arbitrary source photos."""
    import_dir = Path(import_dir).resolve()
    with catalog.connect() as db:
        for row in db.execute('SELECT l.*,r.path FROM file_locations l JOIN library_roots r ON r.id=l.root_id WHERE l.present=1').fetchall():
            path = Path(row['path']) / row['relative']
            if path.parent == import_dir and path.stem == row['asset_id']:
                db.execute('INSERT OR IGNORE INTO managed_imports VALUES (?,?,?)',
                           (row['asset_id'], row['root_id'], import_dir.relative_to(row['path']).as_posix()))


def reconcile(catalog):
    errors = []
    with catalog.connect() as db:
        rows = db.execute('''SELECT m.asset_id,EXISTS(SELECT 1 FROM annotations n WHERE n.asset_id=m.asset_id) annotated,
            (SELECT state FROM jobs j WHERE j.asset_id=m.asset_id ORDER BY j.id DESC LIMIT 1) state FROM managed_imports m''').fetchall()
    for row in rows:
        if row['state'] == 'running':
            continue
        try:
            settle(catalog, row['asset_id'], bool(row['annotated']) and row['state'] != 'error')
        except (OSError, ValueError) as error:
            errors.append(f"Organizzazione {row['asset_id'][:8]}: {error}")
    return errors


def settle(catalog, asset_id, classified):
    if not catalog.organize_imports:
        return
    with catalog.import_lock:
        with catalog.connect() as db:
            managed = db.execute('SELECT * FROM managed_imports WHERE asset_id=?', (asset_id,)).fetchone()
        if not managed:
            return
        base = Path(managed['base_relative'])
        root = next(item for item in catalog.roots(local=True) if item['id'] == managed['root_id'])
        area = Path(root['path']) / base
        if area.resolve() != area:
            raise ValueError('La cartella di importazione è stata sostituita con un collegamento.')
        with catalog.connect() as db:
            locations = db.execute('SELECT * FROM file_locations WHERE asset_id=? AND root_id=? AND present=1',
                                   (asset_id, managed['root_id'])).fetchall()
        source, original = None, None
        for row in locations:
            relative_path = Path(row['relative'])
            if relative_path.parent in (base, base / 'Da catalogare', base / 'Classificate') and relative_path.stem == asset_id:
                candidate = catalog.safe_path(managed['root_id'], row['relative'])
                if candidate.parent not in (area, area / 'Da catalogare', area / 'Classificate'):
                    raise ValueError('La copia importata punta fuori dalle cartelle gestite.')
                if candidate.is_file():
                    source, original = candidate, row
                    break
        if source is None or fingerprint(source) != asset_id:
            raise ValueError('Copia importata non disponibile o modificata: ripeti la scansione.')
        relative = (base / ('Classificate' if classified else 'Da catalogare') / (asset_id + source.suffix.lower())).as_posix()
        destination = catalog.safe_path(managed['root_id'], relative)
        if destination.parent != area / ('Classificate' if classified else 'Da catalogare'):
            raise ValueError('La destinazione punta fuori dalle cartelle gestite.')
        if source == destination:
            return
        catalog.archive.ensure(source, asset_id, verify=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Recheck after creating directories, before relocating the verified working copy.
        if catalog.safe_path(managed['root_id'], relative) != destination:
            raise ValueError('Cartella di destinazione modificata.')
        if destination.exists():
            if fingerprint(destination) != asset_id:
                raise ValueError('Destinazione già occupata da un file diverso.')
            # Only an identical managed working copy is removed, after both backup and destination checks.
            source.unlink()
        else:
            move_new(source, destination, expected_sha=asset_id)
        stamp = destination.stat()
        with catalog.connect() as db:
            notes = json.loads(original['metadata'])
            notes['path_hint'] = relative
            landed = db.execute('SELECT id FROM file_locations WHERE root_id=? AND relative=?', (managed['root_id'], relative)).fetchone()
            if landed and landed[0] != original['id']:
                db.execute('UPDATE file_locations SET present=0 WHERE id=?', (original['id'],))
                db.execute('UPDATE file_locations SET asset_id=?,present=1,size=?,mtime_ns=?,metadata=? WHERE id=?',
                           (asset_id, stamp.st_size, stamp.st_mtime_ns, json.dumps(notes, ensure_ascii=False), landed[0]))
            else:
                db.execute('UPDATE file_locations SET relative=?,size=?,mtime_ns=?,metadata=? WHERE id=?',
                           (relative, stamp.st_size, stamp.st_mtime_ns, json.dumps(notes, ensure_ascii=False), original['id']))
