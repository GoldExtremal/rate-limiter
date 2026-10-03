import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class AdmissionTimeout(Exception):
    pass


class Admission:
    def __init__(self, slots: int, timeout_sec: float) -> None:
        self._semaphore = asyncio.Semaphore(slots)
        self._timeout_sec = timeout_sec
        self.in_use = 0

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        try:
            async with asyncio.timeout(self._timeout_sec):
                await self._semaphore.acquire()
        except TimeoutError as error:
            raise AdmissionTimeout from error
        self.in_use += 1
        try:
            yield
        finally:
            self.in_use -= 1
            self._semaphore.release()
