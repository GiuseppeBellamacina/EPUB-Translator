"""The translation queue: list, add, reorder, start, stop, remove."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import (
    Book,
    QueueItem,
)
from app.jobs import RunConfig, jobs

router = APIRouter()


router = APIRouter()


# === QUEUE ===


class QueueAdd(RunConfig):
    book_ids: list[int]
    keep_glossary: bool = False
    keep_compendium: bool = False


async def queue_items(db: AsyncSession, *where) -> list[dict]:
    """Queue items in order (optionally filtered), with their book's progress."""
    rows = await db.execute(
        select(QueueItem, Book)
        .join(Book, Book.id == QueueItem.book_id)
        .where(*where)
        .order_by(QueueItem.position)
    )
    return [
        {
            "id": item.id,
            "book_id": book.id,
            "filename": book.filename,
            "status": item.status,
            "error": item.error,
            "keep_glossary": item.keep_glossary,
            "keep_compendium": bool(item.keep_compendium),
            "batch_id": item.batch_id,
            "config": item.config,
            "completed_units": book.translated_chapters or 0,
            "total_units": book.total_chapters,
        }
        for item, book in rows.all()
    ]


@router.get("/queue")
async def get_queue(db: AsyncSession = Depends(get_db)):
    """Queued books in order, with their status and progress."""
    return {"running": jobs.scheduler.running, "items": await queue_items(db)}


@router.post("/queue")
async def add_to_queue(data: QueueAdd):
    """Append books (in the given order) and run the queue."""
    config = RunConfig(**data.model_dump(exclude={"book_ids", "keep_glossary", "keep_compendium"}))
    try:
        items = await jobs.enqueue(
            data.book_ids, config, data.keep_glossary, keep_compendium=data.keep_compendium
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"queued": len(items)}


class BatchAdd(BaseModel):
    book_ids: list[int]


@router.post("/queue/{batch_id}/books")
async def add_to_batch(batch_id: int, data: BatchAdd):
    """Add books to the end of an existing queue: same settings, carry-over continues."""
    try:
        items = await jobs.enqueue(data.book_ids, batch_id=batch_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"queued": len(items)}


class QueueOrder(BaseModel):
    item_ids: list[int]


@router.put("/queue/{batch_id}/order")
async def reorder_batch(batch_id: int, data: QueueOrder):
    """New order of a queue's waiting books (running and finished ones stay in place)."""
    try:
        await jobs.queue.reorder(batch_id, data.item_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "reordered"}


@router.post("/queue/start")
async def start_queue():
    """Resume: paused books run again in their order."""
    await jobs.scheduler.resume()
    return {"running": True}


@router.post("/queue/stop")
async def stop_queue():
    """Pause the running book; the rest of the queue waits for a start."""
    jobs.scheduler.stop()
    return {"running": False}


@router.delete("/queue/{item_id}")
async def remove_from_queue(item_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(QueueItem, item_id)
    if not item:
        raise HTTPException(404, "Not in the queue")
    if item.status == "running":
        raise HTTPException(409, "Pause the book before removing it")
    await db.delete(item)
    await db.commit()
    return {"status": "removed"}


@router.delete("/queue")
async def clear_finished(db: AsyncSession = Depends(get_db)):
    """Remove the books the queue has finished (done or failed)."""
    rows = await db.execute(select(QueueItem).where(QueueItem.status.in_(("done", "failed"))))
    for item in rows.scalars():
        await db.delete(item)
    await db.commit()
    return {"status": "cleared"}
