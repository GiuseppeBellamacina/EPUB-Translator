"""One book's translation run: builds the models and the pipeline, follows the events,
persists the checkpoints and publishes the messages."""

import copy
import time
from collections.abc import Callable
from pathlib import Path

from langchain_core.rate_limiters import InMemoryRateLimiter

from app.agents.pipeline import TranslationPipeline
from app.core.config import settings
from app.core.encryption import decrypt_api_key
from app.core.llm_factory import LLMConfig, create_llm
from app.db.database import async_session
from app.db.models import Book, BookStatus, ProviderConfig
from app.jobs.events import FINAL, EventBus, client_message
from app.jobs.models import RunConfig
from app.knowledge.store import KnowledgeRegistry
from app.services.chunker import SmartChunker
from app.services.documents import open_document
from app.services.job_store import JobStore
from app.services.translation_service import translate_document


class JobRunner:
    def __init__(self, events: EventBus, halted: Callable[[], bool], knowledge: KnowledgeRegistry):
        self.events = events
        self._halted = halted  # a stop arrived: a book starting now is paused at once
        self.knowledge = knowledge  # live glossary/compendium stores, shared per scope
        self.active: dict[int, TranslationPipeline] = {}  # running books, for stop
        self.started: dict[int, tuple[float, int]] = {}  # (start time, units done) for the ETA
        self._limiters: dict[tuple[int, float], InMemoryRateLimiter] = {}

    def limiter_for(self, provider_id: int, rps: float | None) -> InMemoryRateLimiter | None:
        """One limiter per provider and pace: books translated in parallel share it."""
        if not rps:
            return None
        key = (provider_id, rps)
        if key not in self._limiters:
            self._limiters[key] = InMemoryRateLimiter(
                requests_per_second=rps, check_every_n_seconds=0.1, max_bucket_size=1
            )
        return self._limiters[key]

    async def run(
        self,
        book_id: int,
        config: RunConfig,
        series: int | None = None,
        series_books: frozenset[int] = frozenset(),
        share_glossary: bool = False,
        share_compendium: bool = False,
    ) -> BookStatus:
        """Translate one book; returns its final status. Raises only if it cannot start.

        In a series (``series`` = its queue, ``series_books`` its books), a shared
        glossary/compendium is one live store for all of them; otherwise the book's own.
        """
        async with async_session() as db:
            provider = await db.get(ProviderConfig, config.provider_id)
            book = await db.get(Book, book_id)
        if not provider:
            raise ValueError("Provider not found")
        if not book:
            raise ValueError("Book not found")

        params = provider.params or {}
        llm_config = LLMConfig(
            provider=provider.provider_type,
            model=config.model or provider.default_model or "gpt-4o-mini",
            api_key=(
                decrypt_api_key(provider.api_key_encrypted) if provider.api_key_encrypted else None
            ),
            base_url=provider.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            requests_per_second=None,  # the provider's shared limiter, below
            max_retries=params.get("max_retries", settings.llm_max_retries),
            structured_output_method=params.get("structured_output_method"),
        )
        llm = create_llm(llm_config)
        llm.rate_limiter = self.limiter_for(
            provider.id, params.get("requests_per_second", settings.requests_per_second)
        )
        review_llm = None
        if config.review_model and config.review_model != llm_config.model:
            # same provider and key, same limiter: the job keeps the provider's pace
            review_config = copy.copy(llm_config)
            review_config.model = config.review_model
            review_llm = create_llm(review_config)
            review_llm.rate_limiter = llm.rate_limiter
        doc = open_document(book.original_path)

        self.events.reset_log(book_id)
        store = JobStore(book_id)
        status, output_path, error = BookStatus.failed, None, None
        final_message: dict | None = None
        held = []  # knowledge stores acquired, released at the end

        def scope(shared: bool) -> tuple[str, set[int]]:
            if shared and series is not None:
                return f"series:{series}", set(series_books)
            return f"book:{book_id}", set()

        try:
            # first the checkpoint: a restart drops the learned knowledge the stores load
            resume = await store.prepare(doc.units, restart=config.restart)
            for kind, shared in (("glossary", share_glossary), ("compendium", share_compendium)):
                name, related = scope(shared)
                held.append(await self.knowledge.acquire(kind, name, book_id, related))
            glossaries, compendiums = held
            pipeline = TranslationPipeline(
                llm=llm,
                source_language=config.source_language or book.source_language or "english",
                target_language=config.target_language or book.target_language or "italian",
                chunker=SmartChunker(target_tokens=600, max_tokens=1000, overlap_blocks=2),
                max_retries=1,
                style_instructions=config.style_instructions,
                enable_review=config.enable_review,
                review_llm=review_llm,
                glossaries=glossaries,
                compendiums=compendiums,
            )
            self.active[book_id] = pipeline
            if self._halted():
                pipeline.cancel()
            self.started[book_id] = (time.time(), len(resume.completed))
            # the full config is kept on the job so the UI can show (and resume with) it
            await store.start(provider.provider_type, llm_config.model, config.model_dump())
            self.events.publish(
                book_id,
                {
                    "event": "started",
                    "message": f"Translation started: {pipeline.source_language} → "
                    f"{pipeline.target_language}"
                    + (
                        f" (resuming: {len(resume.completed)} chapter(s) done)"
                        if resume.previous
                        else ""
                    )
                    + (
                        f", sharing {len(glossaries.glossary)} glossary terms and "
                        f"{len(compendiums.compendium)} compendium entries with its series"
                        if series is not None and (share_glossary or share_compendium)
                        else ""
                    ),
                    "data": {"resumed_chapters": sorted(resume.completed)},
                },
            )

            output = settings.translated_dir / f"{book_id}_{Path(book.filename).stem}{doc.suffix}"
            async for event in translate_document(
                doc,
                pipeline,
                output,
                previous=resume.previous,
                completed=resume.completed,
                analysis=resume.analysis,
                max_concurrency=params.get("max_concurrency", settings.max_concurrency),
            ):
                await store.handle(event)
                if event.event_type == "job_complete":
                    output_path = event.data["output_path"]
                    status = (
                        BookStatus.failed if event.data["failed_units"] else BookStatus.completed
                    )
                    # sent after the DB update below: a client closing on it must see it saved
                    final_message = client_message(event)
                else:
                    self.events.publish(book_id, client_message(event))

            if pipeline._cancelled and final_message is None:
                status = BookStatus.paused
                final_message = {
                    "event": "cancelled",
                    "message": "Translation paused, progress saved",
                }
        except Exception as e:
            error = str(e)
            self.events.publish(book_id, {"event": "error", "message": f"Translation failed: {e}"})
        finally:
            for knowledge_store in held:
                self.knowledge.release(knowledge_store)
            self.active.pop(book_id, None)
            self.started.pop(book_id, None)
            await store.finish(status, output_path, error)
            if final_message:
                self.events.publish(book_id, final_message)
            self.events.publish(book_id, FINAL)
        return status
