"""Glossary and compendium of a book.

Edits are allowed while the book translates: the database is the source of truth,
and the live stores holding the book reload, so the running job uses them at once.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import GlossaryEntryCreate, GlossaryEntryResponse, GlossaryUpdate
from app.db.database import get_db
from app.db.models import CompendiumRecord, GlossaryEntry
from app.jobs import jobs
from app.models.schemas import CompendiumEntry

router = APIRouter()


# === GLOSSARY ===


@router.get("/glossary/{book_id}", response_model=list[GlossaryEntryResponse])
async def get_glossary(book_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GlossaryEntry).where(GlossaryEntry.book_id == book_id))
    return result.scalars().all()


@router.put("/glossary/{book_id}")
async def update_glossary(book_id: int, data: GlossaryUpdate, db: AsyncSession = Depends(get_db)):
    """Replace the book's glossary with the edited list (all entries become the user's)."""
    await db.execute(delete(GlossaryEntry).where(GlossaryEntry.book_id == book_id))
    for entry in data.entries:
        db.add(GlossaryEntry(book_id=book_id, user_edited=True, **entry.model_dump()))
    await db.commit()
    await jobs.knowledge.refresh_book(book_id)
    return {"status": "updated", "count": len(data.entries)}


@router.post("/glossary/{book_id}/entry", response_model=GlossaryEntryResponse)
async def add_glossary_entry(
    book_id: int, entry: GlossaryEntryCreate, db: AsyncSession = Depends(get_db)
):
    new_entry = GlossaryEntry(book_id=book_id, user_edited=True, **entry.model_dump())
    db.add(new_entry)
    await db.commit()
    await db.refresh(new_entry)
    await jobs.knowledge.refresh_book(book_id)
    return new_entry


# === COMPENDIUM ===


class CompendiumItem(CompendiumEntry):
    # the editor sends True for the entries the user changed: those are never touched by
    # the translation again; untouched learned entries keep growing
    user_edited: bool = True


class CompendiumUpdate(BaseModel):
    entries: list[CompendiumItem]


@router.get("/compendium/{book_id}")
async def get_compendium(book_id: int, db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(CompendiumRecord)
        .where(CompendiumRecord.book_id == book_id)
        .order_by(CompendiumRecord.id)
    )
    return [
        {
            "id": r.id,
            "name": r.name,
            "kind": r.kind,
            "gender": r.gender,
            "aliases": r.aliases or [],
            "notes": r.notes,
            "user_edited": bool(r.user_edited),
        }
        for r in rows.scalars()
    ]


@router.put("/compendium/{book_id}")
async def update_compendium(
    book_id: int, data: CompendiumUpdate, db: AsyncSession = Depends(get_db)
):
    """Replace the book's compendium with the edited list."""
    await db.execute(delete(CompendiumRecord).where(CompendiumRecord.book_id == book_id))
    for entry in data.entries:
        db.add(CompendiumRecord(book_id=book_id, **entry.model_dump()))
    await db.commit()
    await jobs.knowledge.refresh_book(book_id)
    return {"status": "updated", "count": len(data.entries)}
