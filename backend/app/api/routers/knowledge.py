"""Glossary and compendium of a book."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    GlossaryEntryCreate,
    GlossaryEntryResponse,
    GlossaryUpdate,
)
from app.db.database import get_db
from app.db.models import (
    CompendiumRecord,
    GlossaryEntry,
)
from app.jobs import jobs
from app.models.schemas import CompendiumEntry

router = APIRouter()


router = APIRouter()


# === GLOSSARY ===


@router.get("/glossary/{book_id}", response_model=list[GlossaryEntryResponse])
async def get_glossary(book_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GlossaryEntry).where(GlossaryEntry.book_id == book_id))
    return result.scalars().all()


@router.put("/glossary/{book_id}")
async def update_glossary(book_id: int, data: GlossaryUpdate, db: AsyncSession = Depends(get_db)):
    # Delete existing entries
    result = await db.execute(select(GlossaryEntry).where(GlossaryEntry.book_id == book_id))
    for entry in result.scalars().all():
        await db.delete(entry)

    # Insert new entries
    for entry_data in data.entries:
        entry = GlossaryEntry(
            book_id=book_id,
            source_term=entry_data.source_term,
            target_term=entry_data.target_term,
            context=entry_data.context,
            do_not_translate=entry_data.do_not_translate,
            user_edited=True,
        )
        db.add(entry)

    await db.commit()
    return {"status": "updated", "count": len(data.entries)}


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
    if jobs.is_running(book_id):
        raise HTTPException(409, "Pause the translation before editing the compendium")
    await db.execute(delete(CompendiumRecord).where(CompendiumRecord.book_id == book_id))
    for entry in data.entries:
        db.add(CompendiumRecord(book_id=book_id, **entry.model_dump()))
    await db.commit()
    return {"status": "updated", "count": len(data.entries)}


@router.post("/glossary/{book_id}/entry", response_model=GlossaryEntryResponse)
async def add_glossary_entry(
    book_id: int,
    entry: GlossaryEntryCreate,
    db: AsyncSession = Depends(get_db),
):
    new_entry = GlossaryEntry(
        book_id=book_id,
        source_term=entry.source_term,
        target_term=entry.target_term,
        context=entry.context,
        do_not_translate=entry.do_not_translate,
        user_edited=True,
    )
    db.add(new_entry)
    await db.commit()
    await db.refresh(new_entry)
    return new_entry
