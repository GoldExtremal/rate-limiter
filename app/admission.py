import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class Admission:
    def __init__(self, slots: int) -> None:
        self._semaphore = asyncio.Semaphore(slots)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._semaphore:
            yield
