"""Translation jobs and the book queue, run as server tasks.

A job runs independently of any client: WebSocket clients only follow its
messages, so closing the page does not pause it. Every start goes through the
queue. The parts:

- ``events.EventBus``: messages, recent log and subscribers (observer)
- ``queue.QueueRepository``: the ``queue_items`` table (repository)
- ``runner.JobRunner``: one book's run (models, pipeline, checkpoints)
- ``scheduler.QueueScheduler``: the worker pool (parallel books, stop/resume)

``jobs`` is the one service the API uses; ``reset`` gives a fresh state at app startup.
"""

from app.jobs.events import FINAL, EventBus
from app.jobs.models import RunConfig
from app.jobs.queue import QueueRepository
from app.jobs.scheduler import QueueScheduler

__all__ = ["FINAL", "RunConfig", "jobs"]


class JobsService:
    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.events = EventBus()
        self.queue = QueueRepository()
        self.scheduler = QueueScheduler(self.queue, self.events)
        self.runner = self.scheduler.runner

    async def enqueue(
        self,
        book_ids: list[int],
        config: RunConfig | None = None,
        keep_glossary: bool = False,
        front: bool = False,
        keep_compendium: bool = False,
        batch_id: int | None = None,
    ):
        """Add books as a new queue (or to queue ``batch_id``, with its settings), then run."""
        items = await self.queue.add(
            book_ids,
            config,
            keep_glossary,
            keep_compendium,
            front,
            batch_id,
            running=set(self.runner.active),
        )
        self.scheduler.kick()
        return items

    def is_running(self, book_id: int) -> bool:
        return book_id in self.runner.active

    async def is_waiting(self, book_id: int) -> bool:
        """Pending in a queue that is running (it will start by itself)."""
        return self.scheduler.running and await self.queue.is_waiting(book_id)

    async def recover(self) -> None:
        await self.queue.recover()


jobs = JobsService()
