"""One cross-event-loop Ollama arbiter; background work yields between photos."""
import asyncio
from contextlib import asynccontextmanager
import threading
import time


class InferenceScheduler:
    def __init__(self):
        self.lock = threading.Lock()
        self.guard = threading.Lock()
        self.interactive = 0
        self.last_interactive = time.monotonic()

    @asynccontextmanager
    async def slot(self, background: bool = False):
        acquired = False
        if not background:
            with self.guard:
                self.interactive += 1
                self.last_interactive = time.monotonic()
        try:
            while not acquired:
                with self.guard:
                    if not background or self.interactive == 0:
                        acquired = self.lock.acquire(blocking=False)
                if not acquired:
                    await asyncio.sleep(0.025)
            yield
        finally:
            if acquired:
                self.lock.release()
            if not background:
                with self.guard:
                    self.interactive -= 1
                    self.last_interactive = time.monotonic()


scheduler = InferenceScheduler()
