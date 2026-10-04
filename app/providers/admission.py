from contextlib import asynccontextmanager
import asyncio

from .errors import ProviderOverloadedError


class ProviderAdmission:
    """Bound active operations and waiters on one application event loop."""

    def __init__(self, max_concurrent: int, max_queued: int):
        if type(max_concurrent) is not int or max_concurrent < 1:
            raise ValueError("max_concurrent must be a positive integer")
        if type(max_queued) is not int or max_queued < 0:
            raise ValueError("max_queued must be a nonnegative integer")
        self._semaphore = asyncio.BoundedSemaphore(max_concurrent)
        self.active = 0
        self.queued = 0
        self.max_concurrent = max_concurrent
        self.max_queued = max_queued

    @asynccontextmanager
    async def slot(self):
        # locked() includes pending handoffs, preventing newcomers overtaking
        # existing semaphore waiters. Check and increment have no await gap.
        if self._semaphore.locked():
            if self.queued >= self.max_queued:
                raise ProviderOverloadedError("Provider queue is full")
            self.queued += 1
            try:
                await self._semaphore.acquire()
            finally:
                self.queued -= 1
        else:
            await self._semaphore.acquire()

        self.active += 1
        try:
            yield
        finally:
            self.active -= 1
            self._semaphore.release()
