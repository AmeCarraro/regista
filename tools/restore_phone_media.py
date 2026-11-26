"""Recreate missing media in their recorded Android folders from Regista ZIPs."""
import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r'[a-f0-9]{64}')
VOLUME = re.compile(r'[a-f0-9]{4}-[a-f0-9]{4}', re.IGNORECASE)
PAGE = 200


@dataclass(frozen=True)
class Original:
    destination: str
    archive: Path
    sha: str
    size: int


def phone_path(media, folder, name):
    if not name or name in ('.', '..', '.nomedia') or any(char in name for char in '/\\\0\n\r'):
        raise ValueError('Nome originale non valido.')
    if any(char in folder for char in '\\\0\n\r') or folder.startswith('/'):
        raise ValueError('Cartella originale non valida.')
    volume = ''
    if ':' in folder.partition('/')[0]:
        volume, folder = folder.split(':', 1)
    if not volume:
        if media.startswith('tree:'):
            parts = folder.casefold().split('/')
            if parts[:2] not in (['android', 'media'], ['whatsapp', 'media'], ['whatsapp business', 'media']):
                raise ValueError('Il volume originale della cartella non è registrato.')
            volume = 'primary'
        else:
            parts = media.split(':')
            volume = parts[1] if len(parts) == 3 else ''
    if volume in ('primary', 'external', 'external_primary'):
        root = '/storage/emulated/0'
    elif VOLUME.fullmatch(volume):
        root = '/storage/' + volume.upper()
    else:
        raise ValueError('Volume Android non riconosciuto.')
    parts = folder.rstrip('/').split('/') if folder.rstrip('/') else []
    if any(part in ('', '.', '..') for part in parts) or [p.casefold() for p in parts[:2]] in (
        ['android', 'data'], ['android', 'obb'],
    ):
        raise ValueError('Percorso fuori dalle cartelle condivise.')
    return str(PurePosixPath(root, *parts, name))


def read_manifest(archive):
    info = archive.getinfo('manifest.json')
    if info.file_size > 64 * 1024 * 1024:
        raise ValueError('Manifesto ZIP troppo grande.')
    return json.loads(archive.read(info))


def as_original(row, archive):
    if not SHA.fullmatch(row['sha256']) or row['size'] < 0:
        raise ValueError('Ricevuta originale non valida.')
    return Original(phone_path(row['media'], row['folder'], row['name']), archive, row['sha256'], row['size'])


def zip_sources(paths):
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            manifest = read_manifest(archive)
        if manifest.get('version') != 2 or 'sources' not in manifest:
            raise ValueError('Serve uno ZIP di importazione con i percorsi originali nel manifesto.')
        hashes = {member['sha256'] for member in manifest['originals']}
        for row in manifest['sources']:
            if row['kind'] in ('image', 'video') and row['sha256'] in hashes:
                yield row, path


def cleanup_sources(index, requested):
    db_uri = (index / 'import-batches.sqlite').resolve().as_uri() + '?mode=ro'
    catalog = (index / 'catalog.sqlite').resolve().as_uri() + '?mode=ro'
    backup = (index / 'backup-originali').resolve()
    with sqlite3.connect(db_uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('ATTACH DATABASE ? AS catalog', (catalog,))
        if requested == 'latest':
            job = db.execute('''SELECT j.id FROM cleanup_jobs j
                WHERE EXISTS(SELECT 1 FROM cleanup_files f WHERE f.job=j.id AND f.removed=1)
                ORDER BY j.updated DESC LIMIT 1''').fetchone()
            if job is None:
                return
            requested = job['id']
        rows = db.execute('''SELECT f.media,f.folder,f.name,f.sha256,f.size,b.relative,j.batch_id
            FROM cleanup_files f JOIN cleanup_jobs j ON j.id=f.job
            LEFT JOIN catalog.original_backups b ON b.asset_id=f.sha256
            WHERE f.job=? AND f.removed=1 AND f.kind IN ('image','video')''', (requested,)).fetchall()
    for row in rows:
        sha = row['sha256']
        relative = f"blocchi/{row['batch_id']}.zip" if row['batch_id'] else row['relative'] or f'{sha[:2]}/{sha}.zip'
        path = (backup / relative).resolve()
        if not path.is_relative_to(backup):
            raise ValueError('Percorso ZIP esterno alla cartella di backup.')
        yield row, path


def plan(sources):
    originals = {}
    ambiguous = set()
    unknown = 0
    for row, archive in sources:
        try:
            original = as_original(row, archive)
        except ValueError:
            unknown += 1
            continue
        existing = originals.setdefault(original.destination, original)
        if existing.sha != original.sha:
            ambiguous.add(original.destination)
    return [original for path, original in sorted(originals.items()) if path not in ambiguous], unknown, len(ambiguous)


class Phone:
    def __init__(self, adb, serial=None):
        self.adb = str(adb)
        self.serial = serial or self.run('-d', 'get-serialno').strip()
        if not self.serial or self.serial == 'unknown':
            raise ValueError('Collega un solo Android via USB e autorizza il debug.')
        if serial and self.run('-s', serial, 'get-state').strip() != 'device':
            raise ValueError('Il dispositivo indicato non è connesso ad ADB.')
        self.transport = 'ADB' if serial else 'USB'
        self.model = self.shell('getprop ro.product.model').strip()

    def run(self, *args, script=None):
        data = script.encode('utf-8') if script is not None else None
        return subprocess.run([self.adb, *args], input=data, capture_output=True, check=True).stdout.decode('utf-8')

    def shell(self, script):
        return self.run('-s', self.serial, 'shell', 'sh', script=script + '\n')

    def missing(self, originals):
        for offset in range(0, len(originals), PAGE):
            group = originals[offset:offset+PAGE]
            tests = [f"if [ -e {path} ] || [ -L {path} ]; then echo 1; else echo 0; fi"
                     for path in (shlex.quote(item.destination) for item in group)]
            found = self.shell('\n'.join(tests)).splitlines()
            if len(found) != len(group) or set(found) - {'0', '1'}:
                raise ValueError('Il telefono non ha restituito tutti i percorsi controllati.')
            yield from (item for item, exists in zip(group, found) if exists == '0')

    def restore(self, source, item):
        parent = shlex.quote(str(PurePosixPath(item.destination).parent))
        target = shlex.quote(item.destination)
        temporary = self.shell(f'set -e\nif [ -e {target} ] || [ -L {target} ]; then echo kept; exit 0; fi'
                               f'\nmkdir -p {parent}\nmktemp {parent}/.regista-ripristino-XXXXXXXX').strip()
        if temporary == 'kept':
            return 'kept'
        if (PurePosixPath(temporary).parent != PurePosixPath(item.destination).parent
                or not re.fullmatch(r'\.regista-ripristino-[a-zA-Z0-9]{8}', PurePosixPath(temporary).name)):
            raise ValueError('Percorso temporaneo Android non valido.')
        temp = shlex.quote(temporary)
        try:
            self.run('-s', self.serial, 'push', str(source), temporary)
            actual = self.shell(f'sha256sum {temp}').split()
            if not actual or actual[0] != item.sha:
                raise ValueError('SHA-256 diverso dopo la copia sul telefono.')
            # -n keeps any file created after the preview. -T prevents moving into a directory.
            status = self.shell(f'set -e\nmv -n -T {temp} {target}'
                                f'\nif [ -e {temp} ]; then echo kept; else echo restored; fi').strip()
            if status not in ('kept', 'restored'):
                raise ValueError('Il telefono non ha confermato il ripristino.')
            return status
        finally:
            try:
                self.shell(f'rm -f {temp}')
            except subprocess.CalledProcessError:
                pass


def restore(phone, missing):
    by_zip = defaultdict(list)
    for original in missing:
        by_zip[original.archive].append(original)
    totals = {'ripristinati': 0, 'gia_presenti': 0, 'errori': 0}
    with tempfile.TemporaryDirectory(prefix='regista-ripristino-') as work:
        temporary = Path(work) / 'originale'
        for path, items in by_zip.items():
            try:
                with zipfile.ZipFile(path) as archive:
                    manifest = read_manifest(archive)
                    entries = manifest['originals'] if manifest.get('version') == 2 else [manifest]
                    members = {entry['sha256']: entry for entry in entries}
                    for item in items:
                        try:
                            member = members[item.sha]
                            info = archive.getinfo(member['original'])
                            if not info.filename.startswith('original/') or info.file_size != item.size:
                                raise ValueError('Voce ZIP non corrispondente alla ricevuta.')
                            with archive.open(info) as source, temporary.open('wb') as target:
                                shutil.copyfileobj(source, target, 1024 * 1024)
                            with temporary.open('rb') as source:
                                if hashlib.file_digest(source, 'sha256').hexdigest() != item.sha:
                                    raise ValueError('SHA-256 diverso nello ZIP.')
                            result = phone.restore(temporary, item)
                            totals['ripristinati' if result == 'restored' else 'gia_presenti'] += 1
                        except (KeyError, ValueError, zipfile.BadZipFile):
                            totals['errori'] += 1
                        if sum(totals.values()) % PAGE == 0:
                            print(totals, flush=True)
            except (FileNotFoundError, KeyError, zipfile.BadZipFile):
                totals['errori'] += len(items)
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--zip', type=Path, action='append', help='ZIP di importazione (ripetibile)')
    source.add_argument('--cleanup', help='ID della rimozione Regista, oppure latest')
    parser.add_argument('--regista-dir', type=Path, default=Path(os.getenv('LOCALAPPDATA') or Path.home()) / 'Programs' / 'Regista')
    parser.add_argument('--adb', type=Path, default=ROOT / 'android' / '.tools' / 'platform-tools' / 'adb.exe')
    parser.add_argument('--adb-serial', help='Dispositivo ADB già connesso, anche tramite debug wireless')
    parser.add_argument('--apply', action='store_true', help='Consente la copia dopo la conferma interattiva')
    args = parser.parse_args()
    try:
        sources = zip_sources(args.zip) if args.zip else cleanup_sources(args.regista_dir / 'index', args.cleanup)
        originals, unknown, ambiguous = plan(sources)
        if not originals:
            print(f'Nessun file ripristinabile. Percorsi sconosciuti {unknown}, ambigui {ambiguous}.')
            return int(bool(unknown or ambiguous))
        phone = Phone(args.adb, args.adb_serial)
        missing = list(phone.missing(originals))
        print(f'{phone.model} via {phone.transport}. Mancanti {len(missing)}, già presenti {len(originals)-len(missing)}, '
              f'percorsi sconosciuti {unknown}, ambigui {ambiguous}.')
        if args.apply and missing and input('Scrivi RIPRISTINA per copiare i file mancanti: ') == 'RIPRISTINA':
            totals = restore(phone, missing)
            print(totals)
            return int(bool(totals['errori']))
        return 0
    except (OSError, ValueError, sqlite3.Error, subprocess.CalledProcessError, zipfile.BadZipFile, KeyError) as error:
        print(f'Ripristino interrotto ({type(error).__name__}). Controlla il collegamento ADB e lo ZIP selezionato. '
              'Puoi rilanciare il comando dai file ancora mancanti.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
