import asyncio

import pytest

from app.admission import Admission, AdmissionTimeout


async def test_slot_is_returned_after_use_and_after_error() -> None:
    admission = Admission(slots=1, timeout_sec=0.1)

    async with admission.slot():
        assert admission.in_use == 1
    with pytest.raises(RuntimeError):
        async with admission.slot():
            raise RuntimeError("inside slot")

    assert admission.in_use == 0
    async with admission.slot():
        pass


async def test_waiting_longer_than_timeout_raises() -> None:
    admission = Admission(slots=1, timeout_sec=0.05)
    release = asyncio.Event()

    async def hold_slot() -> None:
        async with admission.slot():
            await release.wait()

    holder = asyncio.create_task(hold_slot())
    await asyncio.sleep(0)
    with pytest.raises(AdmissionTimeout):
        async with admission.slot():
            pass
    release.set()
    await holder


async def test_timeout_inside_slot_is_not_an_admission_timeout() -> None:
    admission = Admission(slots=1, timeout_sec=1)

    with pytest.raises(TimeoutError) as raised:
        async with admission.slot():
            raise TimeoutError

    assert not isinstance(raised.value, AdmissionTimeout)
