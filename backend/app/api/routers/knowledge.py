"""Glossary and compendium of a book.

Edits are allowed while the book translates: the database is the source of truth,
and the live stores holding the book reload, so the running job uses them at once.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import GlossaryEntryCreate, GlossaryEntryResponse, GlossaryUpdate
from app.db.database import get_db
from app.db.models import CompendiumRecord, GlossaryEntry, QueueItem
from app.jobs import jobs
from app.knowledge.compendium import mention_names
from app.models.schemas import CompendiumEntry
from app.services.fixes import follow_change, remember_yes, series_books, start_fixes

router = APIRouter()


async def _entry(db: AsyncSession, model, book_id: int, entry_id: int):
    row = await db.get(model, entry_id)
    if row is None or row.book_id != book_id:
        raise HTTPException(404, "Entry not found")
    return row


async def _save(db: AsyncSession, book_id: int, row=None) -> None:
    """Commit an edit; the live stores holding the book reload, so a running job uses it."""
    await db.commit()
    if row is not None:
        await db.refresh(row)
    await jobs.knowledge.refresh_book(book_id)


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
    await _save(db, book_id, new_entry)
    return new_entry


@router.put("/glossary/{book_id}/entry/{entry_id}")
async def edit_glossary_entry(
    book_id: int, entry_id: int, entry: GlossaryEntryCreate, db: AsyncSession = Depends(get_db)
):
    """Change one term, also while translating: it becomes the user's. A new translation
    of the same term is followed to the passages already translated (``services.fixes``)."""
    row = await _entry(db, GlossaryEntry, book_id, entry_id)
    old = row.source_term if row.do_not_translate else row.target_term
    new = entry.source_term if entry.do_not_translate else entry.target_term
    same_term = row.source_term.strip().lower() == entry.source_term.strip().lower()
    for key, value in entry.model_dump().items():
        setattr(row, key, value)
    row.user_edited = True
    await _save(db, book_id, row)
    result = GlossaryEntryResponse.model_validate(row).model_dump()
    if same_term and old.strip() != new.strip():
        term = entry.source_term.strip()
        result |= await follow_change(
            QueueItem.keep_glossary,
            book_id,
            [term],
            quote=term,
            reason=f"Glossary: {term} is now translated {new.strip()} (was {old.strip()}); "
            "make the words around it agree",
            old_text=old.strip(),
            new_text=new.strip(),
        )
    return result


@router.delete("/glossary/{book_id}/entry/{entry_id}")
async def delete_glossary_entry(book_id: int, entry_id: int, db: AsyncSession = Depends(get_db)):
    """Also from the series' other books, unless edited there: it would come back."""
    row = await _entry(db, GlossaryEntry, book_id, entry_id)
    books = await series_books(book_id, QueueItem.keep_glossary)
    await db.execute(
        delete(GlossaryEntry).where(
            GlossaryEntry.book_id.in_(books - {book_id}),
            func.lower(GlossaryEntry.source_term) == row.source_term.lower(),
            GlossaryEntry.user_edited.is_not(True),
        )
    )
    await db.delete(row)
    await _save(db, book_id)
    return {"status": "deleted"}


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
    return [_compendium_row(r) for r in rows.scalars()]


def _compendium_row(r: CompendiumRecord) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "kind": r.kind,
        "gender": r.gender,
        "aliases": r.aliases or [],
        "notes": r.notes,
        "evidence": r.evidence or "",  # set: the translation corrected the gender
        "user_edited": bool(r.user_edited),
    }


@router.post("/compendium/{book_id}/entry")
async def add_compendium_entry(
    book_id: int, entry: CompendiumEntry, db: AsyncSession = Depends(get_db)
):
    row = CompendiumRecord(book_id=book_id, user_edited=True, **entry.model_dump())
    db.add(row)
    await _save(db, book_id, row)
    return _compendium_row(row)


@router.put("/compendium/{book_id}/entry/{entry_id}")
async def edit_compendium_entry(
    book_id: int, entry_id: int, entry: CompendiumEntry, db: AsyncSession = Depends(get_db)
):
    """Change one entry, also while translating: it becomes the user's. A new gender (or
    new notes) is followed to the passages already translated (``services.fixes``)."""
    row = await _entry(db, CompendiumRecord, book_id, entry_id)
    old_gender, old_notes = row.gender, (row.notes or "").strip()
    for key, value in entry.model_dump().items():
        setattr(row, key, value)
    row.user_edited = True
    await _save(db, book_id, row)
    result = _compendium_row(row)
    names, notes = mention_names(entry), entry.notes.strip()
    if entry.gender in ("male", "female") and entry.gender != old_gender:
        reason = f"{entry.name}: gender {old_gender} → {entry.gender}"
        result |= await follow_change(
            QueueItem.keep_compendium, book_id, names, quote=entry.name, reason=reason
        )
    elif notes and notes != old_notes:  # rarely needs rewriting: ask first
        reason = f"{entry.name}: the notes now say “{notes}”"
        result |= await follow_change(
            QueueItem.keep_compendium, book_id, names, auto=False, quote=entry.name, reason=reason
        )
    return result


class FixRequest(BaseModel):
    remember: bool = False  # the user said yes: do not ask again for this book


@router.post("/books/{book_id}/fixes")
async def fix_bookmarks(book_id: int, data: FixRequest | None = None):
    """Review the book's open bookmarks now (a review-only run for a completed book)."""
    if data and data.remember:
        await remember_yes([book_id])
    return {"started": await start_fixes(book_id)}


@router.delete("/compendium/{book_id}/entry/{entry_id}")
async def delete_compendium_entry(book_id: int, entry_id: int, db: AsyncSession = Depends(get_db)):
    """Also from the series' other books, unless edited there: it would come back."""
    row = await _entry(db, CompendiumRecord, book_id, entry_id)
    books = await series_books(book_id, QueueItem.keep_compendium)
    await db.execute(
        delete(CompendiumRecord).where(
            CompendiumRecord.book_id.in_(books - {book_id}),
            func.lower(CompendiumRecord.name) == row.name.lower(),
            CompendiumRecord.user_edited.is_not(True),
        )
    )
    await db.delete(row)
    await _save(db, book_id)
    return {"status": "deleted"}


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
