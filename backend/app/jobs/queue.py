"""Queue persistence (repository): every read and write of the ``queue_items`` table.

A *batch* is one queue: books added together share the run settings and, when
asked, carry glossary and compendium from the previous book of the same batch.
Items are ordered by ``position``; statuses: pending, running, paused, done, failed.
"""

from datetime import datetime

from sqlalchemy import func, select, update

from app.db.database import async_session
from app.db.models import Book, ProviderConfig, QueueItem
from app.jobs.models import RunConfig

WAITING = ("pending", "paused")


class QueueRepository:
    async def add(
        self,
        book_ids: list[int],
        config: RunConfig | None,
        keep_glossary: bool,
        keep_compendium: bool,
        front: bool,
        batch_id: int | None,
        running: set[int],
    ) -> list[QueueItem]:
        """Add books as a new batch, or to the end of batch ``batch_id`` with its settings.

        A book already waiting gets the new settings and place. ``running`` are the
        books being translated now: they cannot be queued again.
        """
        async with async_session() as db:
            batch: list[QueueItem] = []
            if batch_id is not None:
                result = await db.execute(
                    select(QueueItem)
                    .where(QueueItem.batch_id == batch_id)
                    .order_by(QueueItem.position)
                )
                batch = list(result.scalars())
                if not batch:
                    raise ValueError("Queue not found")
                config = RunConfig(**batch[-1].config)
                keep_glossary = any(i.keep_glossary for i in batch)
                keep_compendium = any(i.keep_compendium for i in batch)
            if config is None or not await db.get(ProviderConfig, config.provider_id):
                raise ValueError("Provider not found")
            for book_id in book_ids:
                if not await db.get(Book, book_id):
                    raise ValueError(f"Book {book_id} not found")
                if book_id in running:
                    raise ValueError("A translation is already running for this book")
            waiting = await db.execute(
                select(QueueItem).where(
                    QueueItem.book_id.in_(book_ids), QueueItem.status.in_(WAITING)
                )
            )
            for item in waiting.scalars():
                await db.delete(item)
            await db.flush()

            if batch:
                # right after the batch's last book: later batches move down
                start = max(i.position for i in batch) + 1
                await db.execute(
                    update(QueueItem)
                    .where(QueueItem.position >= start)
                    .values(position=QueueItem.position + len(book_ids))
                )
            else:
                bounds = (
                    await db.execute(
                        select(func.min(QueueItem.position), func.max(QueueItem.position))
                    )
                ).one()
                start = (bounds[0] or 0) - len(book_ids) if front else (bounds[1] or 0) + 1
            # added to a paused batch: they wait for its resume instead of running ahead of it
            status = "paused" if any(i.status == "paused" for i in batch) else "pending"
            items = [
                QueueItem(
                    book_id=book_id,
                    position=start + n,
                    batch_id=batch_id,
                    config=config.model_dump(),
                    keep_glossary=keep_glossary,
                    keep_compendium=keep_compendium,
                    status=status,
                )
                for n, book_id in enumerate(book_ids)
            ]
            db.add_all(items)
            await db.flush()
            for item in items:
                item.batch_id = item.batch_id or items[0].id  # a new batch: its first item's id
            await db.commit()
        return items

    async def pending(self) -> list[QueueItem]:
        async with async_session() as db:
            result = await db.execute(
                select(QueueItem).where(QueueItem.status == "pending").order_by(QueueItem.position)
            )
            return list(result.scalars())

    async def set_status(self, item_id: int, status: str, error: str | None = None) -> None:
        async with async_session() as db:
            values: dict = {"status": status, "error": error}
            if status == "running":  # "start over" applies once, not to a later resume
                config = await db.scalar(select(QueueItem.config).where(QueueItem.id == item_id))
                values["config"] = {**(config or {}), "restart": False}
            # a bulk UPDATE: the item may have been removed meanwhile (book deleted)
            await db.execute(update(QueueItem).where(QueueItem.id == item_id).values(**values))
            await db.commit()

    async def batch_books(self, batch_id: int | None) -> frozenset[int]:
        """The books of a batch (a series sharing glossary/compendium)."""
        async with async_session() as db:
            result = await db.execute(
                select(QueueItem.book_id).where(QueueItem.batch_id == batch_id)
            )
            return frozenset(result.scalars())

    async def reorder(self, batch_id: int, item_ids: list[int]) -> None:
        """Put a batch's waiting books in the given order, even while it runs.

        They take the same set of positions they had, so running and finished books, and
        other batches, keep their place.
        """
        async with async_session() as db:
            result = await db.execute(
                select(QueueItem).where(
                    QueueItem.batch_id == batch_id, QueueItem.status.in_(WAITING)
                )
            )
            waiting = {item.id: item for item in result.scalars()}
            if sorted(item_ids) != sorted(waiting):
                raise ValueError("The order must list exactly the queue's waiting books")
            positions = sorted(item.position for item in waiting.values())
            for item_id, position in zip(item_ids, positions):
                waiting[item_id].position = position
            await db.commit()

    async def remove_waiting(self, book_id: int) -> bool:
        """Remove a book that is waiting (not running) from the queue."""
        async with async_session() as db:
            result = await db.execute(
                select(QueueItem).where(QueueItem.book_id == book_id, QueueItem.status.in_(WAITING))
            )
            items = list(result.scalars())
            for item in items:
                await db.delete(item)
            await db.commit()
        return bool(items)

    async def is_waiting(self, book_id: int) -> bool:
        async with async_session() as db:
            status = await db.scalar(
                select(QueueItem.status).where(
                    QueueItem.book_id == book_id, QueueItem.status == "pending"
                )
            )
        return status is not None

    async def pause_waiting(self, before: datetime) -> None:
        """Pending books added up to ``before`` (a stop) become paused."""
        async with async_session() as db:
            await db.execute(
                update(QueueItem)
                .where(QueueItem.status == "pending", QueueItem.created_at <= before)
                .values(status="paused")
            )
            await db.commit()

    async def unpause(self) -> None:
        async with async_session() as db:
            await db.execute(
                update(QueueItem).where(QueueItem.status == "paused").values(status="pending")
            )
            await db.commit()

    async def recover(self) -> None:
        """Startup: the interrupted queue (running and waiting books) waits for a resume."""
        async with async_session() as db:
            await db.execute(
                update(QueueItem)
                .where(QueueItem.status.in_(("running", "pending")))
                .values(status="paused")
            )
            await db.commit()
