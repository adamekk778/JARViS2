"""Fire-and-forget tasks are held until they end, and a failure is logged instead of lost."""
import asyncio
import gc
import logging

from jarvis import background


def test_tasks_are_held_and_failures_logged(caplog):
    done = []

    async def work():
        await asyncio.sleep(0.01)
        done.append(1)

    async def boom():
        raise RuntimeError("au")

    async def main():
        background.bg(work())
        gc.collect()                                   # nothing else holds the task: it must still finish
        background.bg(boom())
        await asyncio.sleep(0.05)

    with caplog.at_level(logging.WARNING, logger="jarvis.bg"):
        asyncio.run(main())
    assert done == [1] and not background._RUNNING
    assert any("au" in r.getMessage() for r in caplog.records)
