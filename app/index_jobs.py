"""Durable annotation queue. Every service restart begins paused."""
import asyncio
import ctypes
import json
import os
import subprocess
import time
import uuid

from inference_scheduler import scheduler
from photo_annotator import VERSION, ModelChangedError
from photo_catalog import fingerprint

LEASE_SECONDS = 900
LEASE_REFRESH_SECONDS = 60


class IdleGate:
    """Best-effort telemetry; missing telemetry means no unattended inference."""
    def __init__(self):
        self.low_since = None
        self.reason = ''

    def ready(self) -> bool:
        try:
            flags = {'creationflags': 0x08000000} if os.name == 'nt' else {}
            measured = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.free', '--format=csv,noheader,nounits'],
                                      capture_output=True, text=True, timeout=3, **flags)
            cards = [tuple(float(value.strip()) for value in line.split(',')) for line in measured.stdout.strip().splitlines()]
            if measured.returncode or not cards:
                raise ValueError('Telemetria GPU non disponibile')
            if os.name == 'nt':
                class Power(ctypes.Structure):
                    _fields_ = [('ac', ctypes.c_ubyte), ('flag', ctypes.c_ubyte), ('percent', ctypes.c_ubyte),
                                ('reserved', ctypes.c_ubyte), ('life', ctypes.c_ulong), ('full', ctypes.c_ulong)]
                state = Power()
                if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(state)) or state.ac != 1:
                    raise ValueError('Modalità inattivo richiede alimentazione di rete')
            quiet = time.monotonic() - scheduler.last_interactive >= float(os.getenv('REGISTA_IDLE_SECONDS', '60'))
            quiet = quiet and all(util <= float(os.getenv('REGISTA_IDLE_GPU_PERCENT', '10')) and
                                      free >= float(os.getenv('REGISTA_IDLE_FREE_MB', '768')) for util, free in cards)
            if not quiet:
                raise ValueError('Computer occupato o memoria GPU insufficiente')
            self.low_since = self.low_since or time.monotonic()
            self.reason = 'Attendo attività GPU bassa e stabile'
            return time.monotonic() - self.low_since >= float(os.getenv('REGISTA_IDLE_STABLE_SECONDS', '30'))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.low_since = None
            self.reason = str(error)
            return False


class IndexJobs:
    def __init__(self, catalog, annotator):
        self.catalog, self.annotator = catalog, annotator
        self.mode = 'paused'
        self.current = ''
        self.problem = ''
        self.idle = IdleGate()
        self.task = None

    def status(self):
        return {**self.catalog.status(), 'mode': self.mode, 'current': self.current, 'problem': self.problem,
                'waiting_reason': self.idle.reason if self.mode == 'idle' else '', 'version': VERSION}

    async def start(self, mode='manual'):
        # Verify first, leaving the queue untouched when the requested tag is absent.
        await self.annotator.verify()
        self.problem = ''
        self.mode = mode
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run())

    def pause(self):
        self.mode = 'paused'

    async def close(self):
        self.pause()
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def retry(self):
        with self.catalog.connect() as db:
            db.execute("UPDATE jobs SET state='pending',attempts=0,next_run=0,error='' WHERE state='error'")

    def reanalyze(self, ids: list[str]):
        with self.catalog.connect() as db:
            for asset_id in dict.fromkeys(ids):
                asset = db.execute('SELECT excluded_reason FROM assets WHERE id=?', (asset_id,)).fetchone()
                if not asset:
                    raise ValueError('Foto non presente.')
                if asset['excluded_reason']:
                    raise ValueError(asset['excluded_reason'])
                # Do not delete a valid result until its replacement has been fully validated.
                db.execute("""INSERT INTO jobs(asset_id,version) VALUES (?,?) ON CONFLICT(asset_id,version)
                    DO UPDATE SET state='pending',attempts=0,next_run=0,error='' WHERE jobs.state!='running'""", (asset_id, VERSION))

    def claim(self):
        now = time.time()
        with self.catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE jobs SET state='pending',lease=NULL,lease_until=NULL WHERE state='running' AND lease_until<?", (now,))
            db.execute("UPDATE jobs SET state='superseded' WHERE state='pending' AND version!=?", (VERSION,))
            if db.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone():
                return None
            row = db.execute("""SELECT j.* FROM jobs j WHERE state='pending' AND next_run<=?
                AND EXISTS(SELECT 1 FROM file_locations l WHERE l.asset_id=j.asset_id AND l.present=1)
                ORDER BY id LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            lease = uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running',lease=?,lease_until=?,attempts=attempts+1 WHERE id=?", (lease, now + LEASE_SECONDS, row['id']))
            return {**dict(row), 'lease': lease, 'attempts': row['attempts'] + 1}

    def renew(self, job):
        with self.catalog.connect() as db:
            return db.execute("UPDATE jobs SET lease_until=? WHERE id=? AND lease=? AND state='running'",
                              (time.time() + LEASE_SECONDS, job['id'], job['lease'])).rowcount == 1

    async def annotate(self, job, path):
        # Keep ownership while waiting for the GPU or a slow response, without limiting inference time.
        task = asyncio.create_task(self.annotator.annotate(path))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=LEASE_REFRESH_SECONDS)
                if done:
                    return task.result()
                if not self.renew(job):
                    raise ValueError('La prenotazione del lavoro non è più valida: nessuna annotazione salvata.')
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def finish(self, job, result):
        with self.catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute("SELECT 1 FROM jobs WHERE id=? AND lease=? AND state='running'", (job['id'], job['lease'])).fetchone()
            if current is None:
                return
            existing = db.execute('SELECT id FROM annotations WHERE asset_id=? AND version=?', (job['asset_id'], job['version'])).fetchone()
            if existing:
                db.execute('DELETE FROM asset_tags WHERE annotation_id=?', (existing[0],))
                db.execute('DELETE FROM annotations WHERE id=?', (existing[0],))
            annotation = db.execute('''INSERT INTO annotations(asset_id,version,model,digest,quantization,prompt_version,
                schema_version,description,result,seconds,created) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (job['asset_id'], job['version'], result['model'], result['digest'], result['quantization'],
                 result['prompt_version'], result['schema_version'], result['description'], json.dumps(result['raw'], ensure_ascii=False),
                 result['seconds'], time.time())).lastrowid
            for tag in result['tags']:
                db.execute('INSERT OR IGNORE INTO asset_tags(annotation_id,tag,category) VALUES (?,?,?)', (annotation, tag['tag'], tag['category']))
            db.execute("UPDATE jobs SET state='done',lease=NULL,lease_until=NULL,error='' WHERE id=?", (job['id'],))
            self.catalog.refresh_text(db, job['asset_id'])

    async def one(self):
        job = self.claim()
        if not job:
            return False
        self.current = job['asset_id']
        try:
            path = self.catalog.path_of(job['asset_id'])
            if path is None or await asyncio.to_thread(fingerprint, path) != job['asset_id']:
                raise ValueError('Foto cambiata o non disponibile: ripeti la scansione.')
            result = await self.annotate(job, path)
            if await asyncio.to_thread(fingerprint, path) != job['asset_id']:
                raise ValueError('Foto modificata durante l’analisi: ripeti la scansione.')
            self.finish(job, result)
        except asyncio.CancelledError:
            with self.catalog.connect() as db:
                db.execute("UPDATE jobs SET state='pending',lease=NULL,lease_until=NULL WHERE id=? AND lease=?", (job['id'], job['lease']))
            raise
        except Exception as error:
            if isinstance(error, ModelChangedError):
                self.problem = str(error)
                self.pause()
            with self.catalog.connect() as db:
                db.execute("""UPDATE jobs SET state=?,next_run=?,error=?,lease=NULL,lease_until=NULL
                    WHERE id=? AND lease=?""", ('error' if job['attempts'] >= 3 else 'pending', time.time() + 5 * 2 ** job['attempts'],
                                              f'{type(error).__name__}: {error}'[:1000], job['id'], job['lease']))
        finally:
            self.current = ''
        return True

    async def run(self):
        try:
            while True:
                if self.mode == 'paused' or (self.mode == 'idle' and not await asyncio.to_thread(self.idle.ready)):
                    await asyncio.sleep(2)
                    continue
                if not await self.one():
                    await asyncio.sleep(2)
                await asyncio.sleep(0)  # Interactive waiters get the next inference slot.
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.problem = f'{type(error).__name__}: {error}'
            self.pause()
