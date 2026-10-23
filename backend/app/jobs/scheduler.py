"""The queue's worker pool: up to ``max_parallel_books`` books at the same time.

Workers claim waiting books in queue order. The books of a queue that keeps
glossary or compendium share one live store of it, so they may run in parallel too.
A stop pauses the running books and halts the pool: the books waiting at that
moment become paused, and only ``resume`` runs them again.
"""

import asyncio
import logging
from datetime import datetime

from app.db.models import BookStatus, QueueItem
from app.jobs.events import FINAL, EventBus
from app.jobs.models import RunConfig
from app.jobs.queue import QueueRepository
from app.jobs.runner import JobRunner
from app.knowledge.store import KnowledgeRegistry
from app.services import app_settings

logger = logging.getLogger(__name__)


class QueueScheduler:
    def __init__(self, queue: QueueRepository, events: EventBus, knowledge: KnowledgeRegistry):
        self.queue = queue
        self.events = events
        self.runner = JobRunner(events, halted=lambda: self.halted, knowledge=knowledge)
        self.halted = False
        self._halted_at: datetime | None = None  # when the last stop happened
        self._workers: set[asyncio.Task] = set()
        self._claimed: dict[int, int | None] = {}  # queue item id -> batch id, being run

    @property
    def running(self) -> bool:
        return bool(self._workers)

    def kick(self) -> None:
        """Run the queue (also after a stop)."""
        self.halted = False
        self.fill()

    def fill(self) -> None:
        """Start workers up to the number of books to translate at the same time."""
        while len(self._workers) < app_settings.load().max_parallel_books:
            task = asyncio.create_task(self._worker())
            self._workers.add(task)  # the reference keeps it alive
            task.add_done_callback(self._workers.discard)

    def stop(self, book_id: int | None = None) -> bool:
        """Pause the running book (any, or ``book_id``) and halt the queue."""
        targets = [p for b, p in self.runner.active.items() if book_id in (None, b)]
        if book_id is None or targets:
            self.halted, self._halted_at = True, datetime.utcnow()
        for pipeline in targets:
            pipeline.cancel()
        return bool(targets)

    async def resume(self) -> None:
        """Run the paused books again (in their order), then anything else waiting."""
        await self.queue.unpause()
        self.kick()

    async def shutdown(self) -> None:
        """App shutdown: pause the running books so their state is saved."""
        self.stop()
        if not self._workers:
            return
        try:
            results = await asyncio.wait_for(
                asyncio.shield(asyncio.gather(*self._workers, return_exceptions=True)),
                timeout=20,
            )
            for result in results:
                if isinstance(result, Exception):  # a crashed worker must not block shutdown
                    logger.error("Queue worker failed: %r", result)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    async def _claim_next(self) -> QueueItem | None:
        """The first waiting book a worker may start, claimed so no other worker takes it."""
        items = await self.queue.pending()
        # no await from here on: checking and claiming happen without another worker between
        for item in items:
            if item.id in self._claimed:
                continue
            self._claimed[item.id] = item.batch_id
            return item
        return None

    async def _worker(self) -> None:
        while True:
            if self._halted_at:  # a stop: the books waiting then pause, newer starts still run
                at, self._halted_at = self._halted_at, None
                await self.queue.pause_waiting(at)
            if self.halted or len(self._workers) > app_settings.load().max_parallel_books:
                break  # halted, or fewer books in parallel than before
            if not (item := await self._claim_next()):
                break
            try:
                await self._run_item(item)
            finally:
                self._claimed.pop(item.id, None)
            self.fill()  # a finished book may let a waiting one of its queue start

    async def _run_item(self, item: QueueItem) -> None:
        await self.queue.set_status(item.id, "running")  # item holds the config read before
        shared = item.keep_glossary or item.keep_compendium
        try:
            status = await self.runner.run(
                item.book_id,
                RunConfig(**item.config),
                series=item.batch_id if shared else None,
                series_books=await self.queue.batch_books(item.batch_id) if shared else frozenset(),
                share_glossary=bool(item.keep_glossary),
                share_compendium=bool(item.keep_compendium),
            )
            error = None
        except Exception as e:  # could not start (provider gone, unreadable file...)
            status, error = BookStatus.failed, str(e)
            self.events.publish(
                item.book_id, {"event": "error", "message": f"Failed to start: {e}"}
            )
            self.events.publish(item.book_id, FINAL)
        await self.queue.set_status(
            item.id,
            {BookStatus.completed: "done", BookStatus.paused: "paused"}.get(status, "failed"),
            error,
        )
