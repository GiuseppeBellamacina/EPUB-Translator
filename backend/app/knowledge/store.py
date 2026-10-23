"""
Live, shared knowledge stores: one glossary and one compendium per *scope*.

A scope is one book (``book:12``), or a series (``series:7``: the books of a queue
that keeps glossary or compendium). Every reader of a scope — the chapters and the
parallel books translating it, the API editing it — gets the same instance from the
``KnowledgeRegistry``, so what one learns the others see at once.

Writes are safe without locking the readers: all of this runs on one asyncio event
loop and the in-memory mutations (``Glossary.add``, ``Compendium.merge``) contain no
``await``, so they are atomic. Only the write-through to the database awaits; a
per-store ``asyncio.Lock`` keeps those writes in order. The database is the source of
truth: a store is loaded from the rows of its books, and every accepted change is
written to the rows of every member book, so each book keeps (and resumes with) the
whole series' knowledge.
"""

import asyncio

from sqlalchemy import select

from app.db.database import async_session
from app.db.models import CompendiumRecord, GlossaryEntry
from app.knowledge.compendium import Compendium
from app.knowledge.glossary import Glossary
from app.models.schemas import CompendiumEntry, GlossaryItem


def glossary_item(row: GlossaryEntry) -> GlossaryItem:
    return GlossaryItem(
        source_term=row.source_term,
        target_term=row.target_term,
        context=row.context,
        do_not_translate=row.do_not_translate,
    )


def compendium_entry(row: CompendiumRecord) -> CompendiumEntry:
    return CompendiumEntry(
        name=row.name, kind=row.kind, gender=row.gender, aliases=row.aliases or [], notes=row.notes
    )


class _SharedStore:
    """Scope, books, write lock and the readers count of a live store.

    ``sources`` are the books whose rows the store loads (a series' earlier books);
    ``members`` the books using it, which receive every change. Loads and writes take
    the lock, so a book joining while the store loads waits for the whole knowledge.
    """

    def __init__(self, scope: str, sources: set[int] | None):
        self.scope = scope
        self.sources = set(sources or ())
        self.members: set[int] = set()
        self.users = 0  # running jobs holding the store
        self._lock = asyncio.Lock()

    @property
    def books(self) -> set[int]:
        return self.sources | self.members

    async def load(self) -> None:
        raise NotImplementedError

    async def join(self, book_id: int) -> None:
        """A book starts using the store: it receives everything known so far."""
        async with self._lock:
            if book_id in self.members:
                return
            self.members.add(book_id)
            await self._write([book_id], self._everything())

    async def refresh(self) -> None:
        """(Re)load from the database: first use, or after an edit from the UI."""
        async with self._lock:
            await self.load()

    def _everything(self) -> list:
        raise NotImplementedError

    async def _write(self, books: list[int], entries: list) -> None:
        raise NotImplementedError


class GlossaryStore(_SharedStore):
    def __init__(self, scope: str = "memory", sources: set[int] | None = None):
        super().__init__(scope, sources)
        self.glossary = Glossary()

    async def load(self) -> None:
        """User terms first (they win), then learned ones; learned near-duplicates stored
        before the check existed are deleted, per book."""
        self.glossary.clear()
        async with async_session() as db:
            result = await db.execute(
                select(GlossaryEntry)
                .where(GlossaryEntry.book_id.in_(self.books))
                .order_by(GlossaryEntry.user_edited.desc(), GlossaryEntry.id)
            )
            per_book: dict[int, Glossary] = {}
            for row in result.scalars():
                own = per_book.setdefault(row.book_id, Glossary())
                if not own.add([glossary_item(row)]) and not row.user_edited:
                    await db.delete(row)
                    continue
                self.glossary.add([glossary_item(row)])
            await db.commit()

    async def learn(self, items: list[GlossaryItem], source_text: str | None = None):
        """Add terms (validated, near-duplicates rejected) and persist the accepted ones."""
        accepted = self.glossary.add(items, source_text=source_text)
        if accepted and self.members:
            async with self._lock:
                await self._write(sorted(self.members), accepted)
        return accepted

    def _everything(self) -> list[GlossaryItem]:
        return self.glossary.entries

    async def _write(self, books: list[int], entries: list[GlossaryItem]) -> None:
        async with async_session() as db:
            for book_id in books:
                rows = await db.execute(
                    select(GlossaryEntry.source_term).where(GlossaryEntry.book_id == book_id)
                )
                known = Glossary(
                    [GlossaryItem(source_term=t, target_term=t) for t in rows.scalars()]
                )
                for item in entries:
                    if known.add([item]):  # not already a term of that book
                        db.add(GlossaryEntry(book_id=book_id, **item.model_dump()))
            await db.commit()


class CompendiumStore(_SharedStore):
    def __init__(self, scope: str = "memory", sources: set[int] | None = None):
        super().__init__(scope, sources)
        self.compendium = Compendium()

    async def load(self) -> None:
        self.compendium.clear()
        async with async_session() as db:
            result = await db.execute(
                select(CompendiumRecord)
                .where(CompendiumRecord.book_id.in_(self.books))
                .order_by(CompendiumRecord.user_edited.desc(), CompendiumRecord.id)
            )
            rows = list(result.scalars())
        self.compendium.merge([compendium_entry(r) for r in rows if r.user_edited], user=True)
        self.compendium.merge([compendium_entry(r) for r in rows if not r.user_edited])

    async def learn(self, updates: list[CompendiumEntry], source_text: str | None = None):
        """Fold updates in and persist the entries that changed."""
        changed = self.compendium.merge(updates, source_text=source_text)
        if changed and self.members:
            async with self._lock:
                await self._write(sorted(self.members), changed)
        return changed

    def _everything(self) -> list[CompendiumEntry]:
        return self.compendium.entries

    async def _write(self, books: list[int], entries: list[CompendiumEntry]) -> None:
        """Upsert by name (entries carry their full state); user rows are left alone."""
        async with async_session() as db:
            for book_id in books:
                result = await db.execute(
                    select(CompendiumRecord).where(CompendiumRecord.book_id == book_id)
                )
                rows = {r.name.lower(): r for r in result.scalars()}
                for entry in entries:
                    row = rows.get(entry.name.lower())
                    if row is None:
                        row = rows[entry.name.lower()] = CompendiumRecord(book_id=book_id)
                        db.add(row)
                    elif row.user_edited:
                        continue
                    for key, value in entry.model_dump().items():
                        setattr(row, key, value)
            await db.commit()


class KnowledgeRegistry:
    """One live store per (kind, scope), kept while a job uses it."""

    def __init__(self):
        self._stores: dict[tuple[str, str], _SharedStore] = {}

    async def acquire(self, kind: str, scope: str, book_id: int, related: set[int]):
        """The live store of ``scope`` for a starting book, loaded on first use.

        ``related`` are the scope's other books whose stored knowledge it includes (a
        series' earlier books).
        """
        key = (kind, scope)
        store = self._stores.get(key)
        if store is None:
            cls = GlossaryStore if kind == "glossary" else CompendiumStore
            store = self._stores[key] = cls(scope, related | {book_id})
            await store.refresh()  # under the lock: a book joining meanwhile waits for it
        await store.join(book_id)
        store.users += 1
        return store

    def release(self, store: _SharedStore) -> None:
        store.users -= 1
        if store.users <= 0:  # nobody translating with it: the database alone is the truth
            self._stores = {k: s for k, s in self._stores.items() if s is not store}

    async def refresh_book(self, book_id: int) -> None:
        """A book's knowledge was edited: live stores holding it reload."""
        for store in list(self._stores.values()):
            if book_id in store.books:
                await store.refresh()
