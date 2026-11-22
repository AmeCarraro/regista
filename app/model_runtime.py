"""Explicit control of the configured PC model, shared by the PC and paired phones."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field
import httpx2

import llm
from inference_scheduler import scheduler


class ModelCommand(BaseModel):
    command: str = Field(pattern='^(load|unload)$')


class ModelRuntime:
    def __init__(self, model, index, jobs=None):
        self.model, self.jobs = model, jobs
        self.history = Path(index) / 'model-runtime.json'
        self.guard = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='model-memory')
        self.phase = 'idle'
        self.command = ''
        self.started = 0
        self.problem = ''
        self.loaded = False
        self.installed = False
        self.checked = 0
        self.durations = {}
        try:
            raw = json.loads(self.history.read_text(encoding='utf-8'))
            if raw.get('model') == model:
                self.durations = {key: value for key, value in raw.get('seconds', {}).items()
                                  if key in ('load', 'unload') and isinstance(value, (float, int)) and 0 <= value < 86400}
        except (OSError, ValueError, TypeError):
            pass

    async def inspect(self, client):
        tags, running = await asyncio.gather(client.get(f'{llm.OLLAMA_URL}/api/tags'), client.get(f'{llm.OLLAMA_URL}/api/ps'))
        tags.raise_for_status()
        running.raise_for_status()
        exact = next((m for m in tags.json().get('models', []) if m.get('name') == self.model), None)
        in_memory = any(m.get('name') == self.model or m.get('model') == self.model or
                        (exact and exact.get('digest') and m.get('digest') == exact['digest'])
                        for m in running.json().get('models', []))
        with self.guard:
            self.installed, self.loaded, self.checked = exact is not None, in_memory, time.time()
        return exact is not None, in_memory

    def snapshot(self):
        with self.guard:
            busy = self.phase in ('waiting', 'loading', 'unloading')
            return {'model': self.model, 'loaded': self.loaded, 'installed': self.installed, 'phase': self.phase,
                    'busy': busy, 'command': self.command, 'started': self.started,
                    'elapsed': round(time.time() - self.started, 1) if busy else 0,
                    'last_seconds': dict(self.durations), 'problem': self.problem, 'checked': self.checked,
                    'analysis_paused': self.jobs is None or self.jobs.mode == 'paused'}

    async def status(self):
        try:
            async with httpx2.AsyncClient(timeout=5) as client:
                await self.inspect(client)
            with self.guard:
                if self.phase == 'idle':
                    self.problem = ''
        except Exception as error:
            with self.guard:
                if self.phase == 'idle':
                    self.problem = f'Ollama non raggiungibile: {error}'[:500]
        return self.snapshot()

    def start(self, command):
        with self.guard:
            # Duplicate taps, including taps from two devices, share one operation.
            if self.phase in ('waiting', 'loading', 'unloading'):
                return self.snapshot()
            self.command, self.phase, self.started, self.problem = command, 'waiting', time.time(), ''
            if command == 'unload' and self.jobs:
                self.jobs.memory_unloading = True
                self.jobs.pause()
            self.pool.submit(lambda: asyncio.run(self.perform(command)))
            return self.snapshot()

    async def perform(self, command):
        try:
            # Let a claimed annotation finish, including one already waiting for the GPU.
            # Its queued request must not reload the model after this explicit unload.
            if command == 'unload' and self.jobs:
                while self.jobs.current:
                    await asyncio.sleep(.1)
            async with scheduler.slot(), httpx2.AsyncClient(timeout=llm.inference_timeout()) as client:
                installed, loaded = await self.inspect(client)
                if not installed and command == 'load':
                    raise ValueError(f'Modello configurato non installato: {self.model}. Nessun download avviato.')
                with self.guard:
                    self.phase = 'loading' if command == 'load' else 'unloading'
                begin = time.monotonic()
                # Even an already loaded model receives keep_alive=-1 so it remains available.
                if command == 'load' or loaded:
                    response = await client.post(f'{llm.OLLAMA_URL}/api/generate', json={
                        'model': self.model, 'stream': False, 'keep_alive': -1 if command == 'load' else 0,
                        'options': {'num_ctx': llm.NUM_CTX},
                    })
                    response.raise_for_status()
                _, actual = await self.inspect(client)
                if actual != (command == 'load'):
                    raise ValueError('Ollama non ha confermato il cambio di stato. Riprova.')
                llm.pin(self.model, command == 'load')
                with self.guard:
                    self.durations[command] = round(time.monotonic() - begin, 2)
                    self.history.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.history.with_suffix('.tmp')
                    temporary.write_text(json.dumps({'model': self.model, 'seconds': self.durations}), encoding='utf-8')
                    temporary.replace(self.history)
                    self.phase = 'idle'
        except Exception as error:
            with self.guard:
                self.phase, self.problem = 'error', str(error)[:500]
        finally:
            if self.jobs:
                self.jobs.memory_unloading = False


def routes(runtime):
    router = APIRouter()

    @router.get('/api/model-runtime')
    async def status():
        return await runtime.status()

    @router.post('/api/model-runtime')
    def control(body: ModelCommand):
        return runtime.start(body.command)

    return router
