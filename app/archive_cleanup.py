"""A phone cleanup needs the exact imported receipt, two verified PC copies and two explicit approvals."""
import asyncio
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Literal
import uuid
import zipfile
import zlib

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from import_batches import BATCH, IDENTITY
from media_sources import source_group
from photo_catalog import fingerprint

PROTOCOL = 3
PAGE = 200
PARTS = 4
ORDER = "scan_group,(media LIKE 'tree:%'),media"


def whatsapp_folder(folder):
    parts = [part for part in re.split(r'[/\\:]+', folder.casefold()) if part]
    roots = (['android', 'media', 'com.whatsapp', 'whatsapp', 'media'],
             ['android', 'media', 'com.whatsapp.w4b', 'whatsapp business', 'media'],
             ['whatsapp', 'media'], ['whatsapp business', 'media'])
    if parts and re.fullmatch(r'primary|external_primary|external|[0-9a-f]{4}-[0-9a-f]{4}', parts[0]):
        parts = parts[1:]
    return all(part not in ('.', '..') for part in parts) and any(parts[:len(root)] == root for root in roots)


class CleanupTarget(BaseModel):
    device: str = Field(min_length=1, max_length=100)
    source: Literal['all', 'normal', 'whatsapp', 'telegram'] = 'all'
    kind: Literal['all', 'image', 'video'] = 'all'
    since: date | None = None
    until: date | None = None

    @model_validator(mode='after')
    def period(self):
        if self.since and self.until and self.since > self.until:
            raise ValueError('La data iniziale deve precedere quella finale.')
        return self


class Candidate(BaseModel):
    media: str = Field(min_length=1, max_length=300)
    stamp: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(pattern=IDENTITY)
    name: str = Field(max_length=500)
    folder: str = Field(default='', max_length=2000)
    kind: Literal['image', 'video']
    day: date | None = None
    date_source: Literal['', 'file', 'whatsapp_name', 'capture'] = ''
    method: Literal['trash', 'folder'] = 'trash'
    original: str = Field(default='', pattern=r'^(?:[0-9a-f]{64})?$')


class Matched(BaseModel):
    job_id: str = Field(pattern=BATCH)
    files: list[Candidate] = Field(max_length=PAGE)
    finished: bool = True
    offset: int | None = Field(default=None, ge=0)
    review: int | None = Field(default=None, ge=0)
    checked: int | None = Field(default=None, ge=0, le=PAGE)


class ReviewStep(BaseModel):
    review: int = Field(default=0, ge=0)


class ConfirmCleanup(ReviewStep):
    yes: bool
    keep: list[str] = Field(default_factory=list, max_length=200000)
    only: list[str] | None = Field(default=None, max_length=200000)

    @model_validator(mode='after')
    def selection(self):
        if self.keep and self.only is not None:
            raise ValueError('Usa una sola modalità di selezione.')
        return self


class CleanupChunk(ReviewStep):
    job_id: str = Field(pattern=BATCH)
    media: list[str] = Field(max_length=PAGE)


class CleanupResult(CleanupChunk):
    cancelled: bool = False
    error: str = Field(default='', max_length=1000)
    done: bool = False


class ArchiveCleanup:
    def __init__(self, batches):
        self.batches = batches
        with batches.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS cleanup_jobs(
                id TEXT PRIMARY KEY,batch_id TEXT NOT NULL,device TEXT NOT NULL,state TEXT NOT NULL,
                created REAL NOT NULL,updated REAL NOT NULL,allowed TEXT NOT NULL DEFAULT '[]',
                matched TEXT NOT NULL DEFAULT '[]',removed TEXT NOT NULL DEFAULT '[]',error TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS cleanup_files(
                    job TEXT NOT NULL,media TEXT NOT NULL,stamp TEXT NOT NULL,sha256 TEXT NOT NULL,
                    name TEXT NOT NULL,folder TEXT NOT NULL,kind TEXT NOT NULL,size INTEGER NOT NULL,
                    day TEXT NOT NULL DEFAULT '',date_source TEXT NOT NULL DEFAULT '',method TEXT NOT NULL DEFAULT '',
                    selected INTEGER NOT NULL DEFAULT 0,authorized INTEGER NOT NULL DEFAULT 0,removed INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(job,media));''')
            db.execute('BEGIN IMMEDIATE')
            file_columns = {row['name'] for row in db.execute('PRAGMA table_info(cleanup_files)')}
            if 'scan_group' not in file_columns:
                db.execute('ALTER TABLE cleanup_files ADD COLUMN scan_group INTEGER NOT NULL DEFAULT 0')
            if 'reviewed' not in file_columns:
                db.execute('ALTER TABLE cleanup_files ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0')
                db.execute("ALTER TABLE cleanup_files ADD COLUMN original TEXT NOT NULL DEFAULT ''")
            if 'policy' not in {row['name'] for row in db.execute('PRAGMA table_info(cleanup_jobs)')}:
                db.execute("ALTER TABLE cleanup_jobs ADD COLUMN policy TEXT NOT NULL DEFAULT ''")
            db.execute("""UPDATE cleanup_jobs SET state='cancelled',error='Richiesta precedente. Crea una nuova anteprima.'
                WHERE policy='' AND state IN ('verifying','finding','matched','approved')""")
            job_columns = {row['name'] for row in db.execute('PRAGMA table_info(cleanup_jobs)')}
            if 'scanned' not in job_columns:
                db.execute('ALTER TABLE cleanup_jobs ADD COLUMN scanned INTEGER NOT NULL DEFAULT 0')
                db.execute('ALTER TABLE cleanup_jobs ADD COLUMN scan_total INTEGER NOT NULL DEFAULT 0')
                db.execute('ALTER TABLE cleanup_jobs ADD COLUMN review INTEGER NOT NULL DEFAULT 0')
                for row in db.execute("SELECT id,state FROM cleanup_jobs WHERE policy!=''").fetchall():
                    total = db.execute('SELECT count(*) FROM cleanup_files WHERE job=?', (row['id'],)).fetchone()[0]
                    scanned = total if row['state'] in ('matched', 'approved', 'finished') else 0
                    if row['state'] == 'finding':
                        scanned = self.legacy_offset(db, row['id'], total)
                    db.execute('UPDATE cleanup_jobs SET scan_total=?,scanned=? WHERE id=?', (total, scanned, row['id']))
            db.execute("CREATE INDEX IF NOT EXISTS cleanup_originals ON cleanup_files(job,original) WHERE original!=''")

    @staticmethod
    def legacy_offset(db, identifier, total):
        # Older phones reported a page only after completing it. Empty trailing pages cannot be recovered.
        last = db.execute(f"""SELECT coalesce(max(position),0) FROM (
            SELECT row_number() OVER (ORDER BY {ORDER}) AS position,method FROM cleanup_files WHERE job=?
            ) WHERE method!=''""", (identifier,)).fetchone()[0]
        return min(total, (last + PAGE - 1) // PAGE * PAGE)

    @staticmethod
    def page_end(scanned, total):
        if scanned >= total:
            return total
        part = PARTS * scanned // total + 1
        boundary = (total * part + PARTS - 1) // PARTS
        return min(scanned + PAGE, boundary)

    def job(self, identifier, device=None):
        with self.batches.connect() as db:
            row = db.execute('SELECT * FROM cleanup_jobs WHERE id=?', (identifier,)).fetchone()
        if row is None or (device is not None and row['device'] != device):
            raise HTTPException(404, 'Richiesta di pulizia non disponibile per questo telefono.')
        return dict(row)

    def status(self, identifier, offset=0):
        row = self.job(identifier)
        with self.batches.connect() as db:
            counts = dict(db.execute('''SELECT coalesce(sum(reviewed=0),0) AS count,
                coalesce(sum(kind='image' AND reviewed=0),0) AS images,
                coalesce(sum(kind='video' AND reviewed=0),0) AS videos,
                coalesce(sum(method='folder' AND reviewed=0),0) AS folder_files,
                coalesce(sum(CASE WHEN reviewed=0 THEN size ELSE 0 END),0) AS bytes,
                coalesce(sum(selected AND reviewed=0),0) AS selected,coalesce(sum(removed),0) AS removed,
                coalesce(sum(selected AND removed=0 AND reviewed=0),0) AS selected_remaining
                FROM cleanup_files WHERE job=? AND method!='' ''', (identifier,)).fetchone())
            files = [dict(item) for item in db.execute('''SELECT media,sha256,name,folder,kind,day,date_source,method,size,selected,removed
                FROM cleanup_files WHERE job=? AND method!='' AND reviewed=0
                ORDER BY day,name,media LIMIT ? OFFSET ?''', (identifier, PAGE, offset))]
        fields = ('id', 'batch_id', 'device', 'state', 'created', 'updated', 'error', 'scanned', 'scan_total', 'review')
        return ({key: row[key] for key in fields} | counts | {'files': files, 'offset': offset, 'limit': PAGE,
                'parts': PARTS, 'policy': json.loads(row['policy'] or '{}')})

    def latest(self, batch=''):
        with self.batches.connect() as db:
            row = db.execute('SELECT id FROM cleanup_jobs WHERE batch_id=? ORDER BY created DESC LIMIT 1', (batch,)).fetchone()
        return self.status(row['id']) if row else None

    def prepare(self, batch, target):
        if isinstance(target, str):
            target = CleanupTarget(device=target)
        if batch:
            run = self.batches.run(batch, target.device)
            if run['state'] != 'ready' or not run['zip_sha']:
                raise HTTPException(409, 'Scegli un blocco con ZIP completato.')
        identifier = uuid.uuid4().hex
        now = time.time()
        with self.batches.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute("SELECT 1 FROM cleanup_jobs WHERE device=? AND state IN ('verifying','finding','matched','approved','reviewed')",
                                (target.device,)).fetchone()
            if active:
                raise HTTPException(409, 'Concludi o annulla prima l’altra richiesta di pulizia per questo telefono.')
            db.execute('INSERT INTO cleanup_jobs(id,batch_id,device,state,created,updated,policy) VALUES (?,?,?,?,?,?,?)',
                       (identifier, batch, target.device, 'verifying', now, now, target.model_dump_json()))
        self.batches.pool.submit(self.prepare_sync, identifier)
        return self.status(identifier)

    def receipts(self, value, target):
        sql = '''SELECT f.* FROM files f JOIN runs r ON r.id=f.batch_id
            WHERE r.device=? AND r.state='ready' AND f.state='received' AND f.kind IN ('image','video')'''
        parameters = [target.device]
        if value['batch_id']:
            sql += ' AND f.batch_id=? AND f.archive_member=1'
            parameters.append(value['batch_id'])
        with self.batches.connect() as db:
            rows = db.execute(sql + ' ORDER BY r.created DESC, f.media', parameters).fetchall()
        receipts = []
        seen = set()
        for item in rows:
            if item['media'] in seen:
                continue
            seen.add(item['media'])
            if target.kind not in ('all', item['kind']):
                continue
            if target.source == 'whatsapp' and not whatsapp_folder(item['folder']):
                continue
            if target.source in ('normal', 'telegram') and source_group(item['folder']) != target.source:
                continue
            receipts.append(item)
        return receipts

    @staticmethod
    def insert_receipts(db, identifier, receipts, group=0):
        return db.executemany('''INSERT OR IGNORE INTO cleanup_files(job,media,stamp,sha256,name,folder,kind,size,scan_group)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            [(identifier, item['media'], item['stamp'], item['sha256'], item['name'], item['folder'],
              item['kind'], item['size'], group) for item in receipts]).rowcount

    def prepare_sync(self, identifier):
        value = self.job(identifier)
        try:
            target = CleanupTarget.model_validate_json(value['policy'])
            receipts = self.receipts(value, target)
            with self.batches.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT state FROM cleanup_jobs WHERE id=?', (identifier,)).fetchone()[0] != 'verifying':
                    return
                self.insert_receipts(db, identifier, receipts)
                db.execute('UPDATE cleanup_jobs SET state=?,scan_total=?,updated=? WHERE id=?',
                           ('finding' if receipts else 'matched', len(receipts), time.time(), identifier))
        except Exception as error:
            with self.batches.connect() as db:
                db.execute("UPDATE cleanup_jobs SET state='error',error=?,updated=? WHERE id=? AND state='verifying'",
                           (str(error)[:1000], time.time(), identifier))

    def pending(self, device, protocol=PROTOCOL):
        with self.batches.connect() as db:
            row = db.execute("SELECT * FROM cleanup_jobs WHERE device=? AND state IN ('finding','matched','approved') ORDER BY created LIMIT 1",
                             (device,)).fetchone()
            if row is None:
                return {'job': None}
            if protocol == 2 and (row['review'] or (row['state'] == 'finding' and row['scanned'])):
                return {'job': None, 'upgrade_required': True}
            result = {key: row[key] for key in ('id', 'batch_id', 'state', 'scanned', 'scan_total', 'review')}
            result['policy'] = json.loads(row['policy'])
            if row['state'] == 'approved':
                count, folder_count = db.execute('''SELECT count(*),coalesce(sum(method='folder'),0)
                    FROM cleanup_files WHERE job=? AND reviewed=0 AND selected=1 AND removed=0''', (row['id'],)).fetchone()
                # Put the Android trash group first. Any provider deletion has its own confirmation.
                files = db.execute('''SELECT * FROM cleanup_files WHERE job=? AND reviewed=0 AND selected=1 AND removed=0
                    ORDER BY method DESC,media LIMIT ?''', (row['id'], PAGE)).fetchall()
                result.update(files=[dict(item) for item in files], remaining=count, folder_remaining=folder_count)
        return {'job': result}

    def candidates(self, device, identifier, offset, checkpoint=False):
        value = self.job(identifier, device)
        if value['state'] != 'finding':
            raise HTTPException(409, 'L’anteprima è già chiusa.')
        limit = PAGE
        if checkpoint:
            if offset != value['scanned']:
                raise HTTPException(409, 'Il punto di ripresa è cambiato.')
            limit = self.page_end(offset, value['scan_total']) - offset
        with self.batches.connect() as db:
            rows = db.execute(f'''SELECT media,stamp,sha256,name,folder,kind,size FROM cleanup_files
                WHERE job=? ORDER BY {ORDER} LIMIT ? OFFSET ?''', (identifier, limit, offset)).fetchall()
        return {'files': [dict(row) for row in rows], 'limit': limit}

    def matched(self, device, body):
        value = self.job(body.job_id, device)
        target = CleanupTarget.model_validate_json(value['policy'])
        with self.batches.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state,scanned,scan_total,review FROM cleanup_jobs WHERE id=?', (body.job_id,)).fetchone()
            if body.offset is not None and body.offset < row['scanned']:
                return {'received': 0, 'finished': row['state'] != 'finding', 'scanned': row['scanned']}
            if row['state'] != 'finding':
                raise HTTPException(409, 'L’anteprima è già chiusa.')
            end = row['scanned']
            finished = body.finished
            page = None
            if body.offset is not None:
                if body.offset != end or (body.review is not None and body.review != row['review']):
                    raise HTTPException(409, 'Il punto di ripresa è cambiato.')
                end = self.page_end(body.offset, row['scan_total'])
                if body.checked is not None and body.checked != end - body.offset:
                    raise HTTPException(409, 'Il lotto da controllare è cambiato.')
                page = {item['media']: item for item in db.execute(f'''SELECT * FROM cleanup_files
                    WHERE job=? ORDER BY {ORDER} LIMIT ? OFFSET ?''', (body.job_id, end - body.offset, body.offset))}
                finished = end >= row['scan_total'] or PARTS * end // row['scan_total'] > PARTS * body.offset // row['scan_total']
            elif row['scanned'] or row['review']:
                raise HTTPException(409, 'Aggiorna Regista sul telefono per riprendere la verifica.')
            elif finished:
                end = row['scan_total']
            received = 0
            for item in body.files:
                expected = (page.get(item.media) if page is not None else db.execute(
                    'SELECT * FROM cleanup_files WHERE job=? AND media=?', (body.job_id, item.media)).fetchone())
                if expected is None or any(expected[key] != getattr(item, key) for key in ('stamp', 'sha256', 'name', 'folder', 'kind')):
                    raise HTTPException(409, 'Il file non corrisponde alla copia originale di questo telefono.')
                if (target.since or target.until) and (not item.day or not item.date_source or
                        (target.since and item.day < target.since) or (target.until and item.day > target.until)):
                    raise HTTPException(409, 'La data del file è fuori dalla selezione.')
                if target.source == 'whatsapp' and item.date_source == 'capture':
                    raise HTTPException(409, 'Per WhatsApp serve una data del file sul telefono.')
                if (item.method == 'folder') != item.media.startswith('tree:'):
                    raise HTTPException(409, 'Tipo di accesso del file diverso dall’originale.')
                if item.original and db.execute("""SELECT 1 FROM cleanup_files WHERE job=? AND original=? AND original!=''""",
                                                (body.job_id, item.original)).fetchone():
                    continue
                db.execute('UPDATE cleanup_files SET day=?,date_source=?,method=?,original=? WHERE job=? AND media=?',
                           (item.day.isoformat() if item.day else '', item.date_source, item.method, item.original,
                            body.job_id, item.media))
                received += 1
            db.execute('UPDATE cleanup_jobs SET state=?,scanned=?,updated=? WHERE id=?',
                       ('matched' if finished else 'finding', end, time.time(), body.job_id))
        return {'received': received, 'finished': finished, 'scanned': end}

    def pause_review(self, identifier, review):
        with self.batches.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            value = db.execute('SELECT * FROM cleanup_jobs WHERE id=?', (identifier,)).fetchone()
            if value is None or value['review'] != review or value['state'] != 'finding':
                raise HTTPException(409, 'La verifica è già in pausa o è cambiata.')
            scanned = value['scanned'] or self.legacy_offset(db, identifier, value['scan_total'])
            db.execute("UPDATE cleanup_jobs SET state='matched',scanned=?,updated=? WHERE id=?",
                       (scanned, time.time(), identifier))
        return self.status(identifier)

    def continue_review(self, identifier, review):
        with self.batches.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("""UPDATE cleanup_jobs SET state='finding',review=review+1,error='',updated=?
                WHERE id=? AND review=? AND state IN ('matched','reviewed') AND scanned<scan_total""",
                (time.time(), identifier, review)).rowcount
            if not changed:
                raise HTTPException(409, 'Non ci sono altri file da controllare per questo lotto.')
            db.execute("UPDATE cleanup_files SET reviewed=1 WHERE job=? AND method!='' AND reviewed=0", (identifier,))
        return self.status(identifier)

    def include_videos(self, identifier, review):
        value = self.job(identifier)
        target = CleanupTarget.model_validate_json(value['policy'])
        if target.source != 'whatsapp' or target.kind != 'image':
            raise HTTPException(409, 'I video WhatsApp possono essere aggiunti a una verifica delle foto WhatsApp.')
        receipts = self.receipts(value, target.model_copy(update={'kind': 'video'}))
        with self.batches.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state,review,policy FROM cleanup_jobs WHERE id=?', (identifier,)).fetchone()
            if row['review'] != review or row['policy'] != value['policy'] or row['state'] not in ('matched', 'reviewed'):
                raise HTTPException(409, 'Metti la verifica in pausa prima di aggiungere i video.')
            count = self.insert_receipts(db, identifier, receipts, group=1)
            db.execute('UPDATE cleanup_jobs SET policy=?,scan_total=scan_total+?,updated=? WHERE id=?',
                       (target.model_copy(update={'kind': 'all'}).model_dump_json(), count, time.time(), identifier))
        return self.status(identifier)

    def resume_removal(self, identifier, review):
        # A retry keeps the original PC selection. The phone must still get new
        # authorization for each page, and the page rechecks both backup copies.
        with self.batches.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            value = db.execute('SELECT state,review,error FROM cleanup_jobs WHERE id=?', (identifier,)).fetchone()
            if value is None or value['review'] != review or value['state'] not in ('reviewed', 'cancelled') or not value['error']:
                raise HTTPException(409, 'La rimozione non è in pausa a causa di un errore.')
            remains = db.execute('''SELECT 1 FROM cleanup_files
                WHERE job=? AND selected=1 AND removed=0 AND reviewed=0 LIMIT 1''', (identifier,)).fetchone()
            if remains is None:
                raise HTTPException(409, 'Tutti i file selezionati risultano rimossi.')
            active = db.execute("""SELECT 1 FROM cleanup_jobs WHERE id<>?
                AND device=(SELECT device FROM cleanup_jobs WHERE id=?)
                AND state IN ('verifying','finding','matched','approved','reviewed')""", (identifier, identifier)).fetchone()
            if active:
                raise HTTPException(409, 'Concludi prima l’altra richiesta aperta per questo telefono.')
            db.execute("UPDATE cleanup_jobs SET state='approved',error='',updated=? WHERE id=?", (time.time(), identifier))
        return self.status(identifier)

    def verify_copies(self, job, files, *, check_archive_digest=False):
        by_archive = {}
        for item in files:
            sha = item['sha256']
            path = self.batches.zip_path(job['batch_id']) if job['batch_id'] else self.batches.catalog.archive.path(sha)
            by_archive.setdefault(path, {})[sha] = item['size']
        try:
            for path, hashes in by_archive.items():
                if path.parent.name == 'blocchi':
                    batch = self.batches.run(path.stem)
                    if batch['state'] != 'ready' or not batch['zip_sha']:
                        raise ValueError('ZIP del blocco non ancora pronto.')
                    if check_archive_digest and fingerprint(path) != batch['zip_sha']:
                        raise ValueError('SHA dello ZIP diverso da quello verificato all’importazione.')
                with zipfile.ZipFile(path) as archive:
                    if archive.getinfo('manifest.json').file_size > 64 * 1024 * 1024:
                        raise ValueError('Manifesto ZIP non valido.')
                    manifest = json.loads(archive.read('manifest.json'))
                    records = manifest['originals'] if manifest.get('version') == 2 else [manifest]
                    originals = {item['sha256']: item for item in records}
                    if len(originals) != len(records):
                        raise ValueError('Lo ZIP contiene identificativi ripetuti.')
                    for sha, size in hashes.items():
                        entry = originals[sha]
                        info = archive.getinfo(entry['original'])
                        if not info.filename.startswith('original/') or info.file_size != size or entry['size'] != size:
                            raise ValueError('Dimensione o percorso nello ZIP diverso dall’originale.')
                        with archive.open(info) as source:
                            if hashlib.file_digest(source, 'sha256').hexdigest() != sha:
                                raise ValueError('Contenuto nello ZIP diverso dall’originale.')
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, zipfile.BadZipFile, EOFError, zlib.error) as error:
            raise HTTPException(409, f'ZIP non verificato: {error}') from error
        for sha in {item['sha256'] for item in files}:
            normal = self.batches.normal_path(sha)
            if normal is None or normal.resolve().is_relative_to(self.batches.staging):
                raise HTTPException(409, 'Manca una copia normale verificata sul PC.')

    def confirm(self, identifier, yes, keep=(), only=None, review=0):
        value = self.job(identifier)
        if value['review'] != review:
            raise HTTPException(409, 'La selezione appartiene a un altro lotto.')
        if not yes:
            with self.batches.connect() as db:
                db.execute("""UPDATE cleanup_jobs SET state='cancelled',updated=? WHERE id=? AND review=?
                    AND state IN ('verifying','finding','matched','approved','reviewed')""", (time.time(), identifier, review))
            return self.status(identifier)
        if value['state'] != 'matched':
            raise HTTPException(409, 'Attendi il riepilogo dei file trovati sul telefono.')
        with self.batches.connect() as db:
            files = db.execute("SELECT * FROM cleanup_files WHERE job=? AND method!='' AND reviewed=0", (identifier,)).fetchall()
        included = {item['media'] for item in files}
        choices = set(keep if only is None else only)
        if not choices <= included:
            raise HTTPException(409, 'La scelta contiene elementi estranei all’anteprima.')
        selected_ids = included - choices if only is None else choices
        selected = [item for item in files if item['media'] in selected_ids]
        if not selected:
            raise HTTPException(409, 'Seleziona almeno un file da rimuovere.')
        self.verify_copies(value, selected, check_archive_digest=True)
        with self.batches.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE cleanup_jobs SET state='approved',updated=? WHERE id=? AND state='matched' AND review=?",
                                 (time.time(), identifier, review)).rowcount
            if not changed:
                raise HTTPException(409, 'La richiesta è cambiata durante la verifica.')
            db.executemany('UPDATE cleanup_files SET selected=1 WHERE job=? AND media=?',
                           [(identifier, item['media']) for item in selected])
        return self.status(identifier)

    def authorize(self, device, body):
        value = self.job(body.job_id, device)
        if value['state'] != 'approved' or value['review'] != body.review:
            raise HTTPException(409, 'Manca la conferma esplicita sul PC.')
        if not body.media or len(body.media) != len(set(body.media)):
            raise HTTPException(409, 'Selezione non valida.')
        with self.batches.connect() as db:
            selected = [db.execute('''SELECT * FROM cleanup_files WHERE job=? AND media=? AND reviewed=0 AND selected=1 AND removed=0''',
                                   (body.job_id, media)).fetchone() for media in body.media]
        if any(item is None for item in selected):
            raise HTTPException(409, 'Selezione diversa da quella confermata.')
        self.verify_copies(value, selected)
        with self.batches.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state,review FROM cleanup_jobs WHERE id=?', (body.job_id,)).fetchone()
            if row['state'] != 'approved' or row['review'] != body.review:
                raise HTTPException(409, 'La richiesta è stata annullata.')
            db.executemany('UPDATE cleanup_files SET authorized=1 WHERE job=? AND media=?',
                           [(body.job_id, item['media']) for item in selected])
        return {'authorized': True, 'files': [dict(item) for item in selected], 'requires_android_confirmation': True}

    def result(self, device, body):
        self.job(body.job_id, device)
        with self.batches.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state,review,scanned,scan_total FROM cleanup_jobs WHERE id=?', (body.job_id,)).fetchone()
            if body.review < row['review']:
                # The PC can already be scanning the next lot after acknowledging this result.
                return self.status(body.job_id)
            value = row['state']
            if body.review != row['review'] or value not in ('approved', 'cancelled', 'finished', 'reviewed'):
                raise HTTPException(409, 'Richiesta non approvata.')
            for media in set(body.media):
                changed = db.execute('UPDATE cleanup_files SET removed=1 WHERE job=? AND media=? AND reviewed=0 AND authorized=1',
                                     (body.job_id, media)).rowcount
                if not changed:
                    raise HTTPException(409, 'Risultato estraneo alla selezione confermata.')
            remaining = db.execute('SELECT count(*) FROM cleanup_files WHERE job=? AND reviewed=0 AND selected=1 AND removed=0',
                                   (body.job_id,)).fetchone()[0]
            state = value
            if value == 'approved' and (body.cancelled or not remaining):
                state = 'reviewed' if row['scanned'] < row['scan_total'] else ('cancelled' if body.cancelled else 'finished')
            db.execute('UPDATE cleanup_jobs SET state=?,error=?,updated=? WHERE id=?', (state, body.error, time.time(), body.job_id))
        return self.status(body.job_id)

    def revoke(self, device):
        with self.batches.connect() as db:
            db.execute("UPDATE cleanup_jobs SET state='cancelled',updated=? WHERE device=? AND state IN ('verifying','finding','matched','approved','reviewed')",
                       (time.time(), device))


def routes(batches, phones=None, *, read_only=False):
    router = APIRouter()
    cleanup = ArchiveCleanup(batches)
    batches.cleanup = cleanup

    def local(request):
        if getattr(request.state, 'device', None):
            raise HTTPException(403, 'La conferma si dà dal PC.')

    def phone(request):
        device = getattr(request.state, 'device', None)
        if not device:
            raise HTTPException(403, 'Serve un telefono collegato.')
        return device

    def prepare(request, batch, body):
        local(request)
        if read_only:
            raise HTTPException(409, 'Pulizia non disponibile in sola lettura.')
        if phones is None or not any(item['id'] == body.device for item in phones.devices):
            raise HTTPException(409, 'Collega il telefono da cui vuoi rimuovere i file.')
        return cleanup.prepare(batch, body)

    @router.post('/api/imports/{batch}/cleanup')
    def prepare_archive(request: Request, batch: str, body: CleanupTarget):
        return prepare(request, batch, body)

    @router.post('/api/import-cleanup')
    def prepare_library(request: Request, body: CleanupTarget):
        return prepare(request, '', body)

    @router.get('/api/import-cleanup')
    def latest(request: Request):
        local(request)
        return {'job': cleanup.latest()}

    @router.get('/api/import-cleanup/{job}')
    def status(request: Request, job: str, offset: int = Query(default=0, ge=0)):
        local(request)
        return cleanup.status(job, offset)

    @router.post('/api/import-cleanup/{job}/confirm')
    async def confirm(request: Request, job: str, body: ConfirmCleanup):
        local(request)
        if read_only and body.yes:
            raise HTTPException(409, 'Pulizia non disponibile in sola lettura.')
        return await asyncio.to_thread(cleanup.confirm, job, body.yes, body.keep, body.only, body.review)

    @router.post('/api/import-cleanup/{job}/pause')
    def pause_review(request: Request, job: str, body: ReviewStep):
        local(request)
        if read_only:
            raise HTTPException(409, 'Pulizia non disponibile in sola lettura.')
        return cleanup.pause_review(job, body.review)

    @router.post('/api/import-cleanup/{job}/continue')
    def continue_review(request: Request, job: str, body: ReviewStep):
        local(request)
        if read_only:
            raise HTTPException(409, 'Pulizia non disponibile in sola lettura.')
        return cleanup.continue_review(job, body.review)

    @router.post('/api/import-cleanup/{job}/include-videos')
    async def include_videos(request: Request, job: str, body: ReviewStep):
        local(request)
        if read_only:
            raise HTTPException(409, 'Pulizia non disponibile in sola lettura.')
        return await asyncio.to_thread(cleanup.include_videos, job, body.review)

    @router.post('/api/import-cleanup/{job}/resume-removal')
    def resume_removal(request: Request, job: str, body: ReviewStep):
        local(request)
        if read_only:
            raise HTTPException(409, 'Pulizia non disponibile in sola lettura.')
        return cleanup.resume_removal(job, body.review)

    @router.get('/phone/import-cleanup')
    def pending(request: Request, protocol: int = 0):
        device = phone(request)
        if read_only or protocol not in (2, PROTOCOL):
            return {'job': None, 'upgrade_required': protocol not in (2, PROTOCOL)}
        return cleanup.pending(device, protocol)

    @router.get('/phone/import-cleanup/candidates')
    def candidates(request: Request, job_id: str = Query(pattern=BATCH), offset: int = Query(default=0, ge=0),
                   protocol: int = 2):
        return cleanup.candidates(phone(request), job_id, offset, checkpoint=protocol == PROTOCOL)

    @router.post('/phone/import-cleanup/matched')
    def matched(request: Request, body: Matched):
        return cleanup.matched(phone(request), body)

    @router.post('/phone/import-cleanup/authorize')
    async def authorize(request: Request, body: CleanupChunk):
        if read_only:
            raise HTTPException(409, 'Pulizia non disponibile in sola lettura.')
        return await asyncio.to_thread(cleanup.authorize, phone(request), body)

    @router.post('/phone/import-cleanup/result')
    def result(request: Request, body: CleanupResult):
        return cleanup.result(phone(request), body)

    return router
