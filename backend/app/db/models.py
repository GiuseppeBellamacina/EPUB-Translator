"""Database models — SQLAlchemy ORM for SQLite."""

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class BookStatus(str, enum.Enum):
    uploaded = "uploaded"
    analyzing = "analyzing"
    ready = "ready"
    translating = "translating"
    paused = "paused"  # interrupted (stop, disconnect, server restart): resumable
    completed = "completed"
    failed = "failed"  # finished with errors or crashed: resumable


class ChapterStatus(str, enum.Enum):
    pending = "pending"
    translating = "translating"
    reviewing = "reviewing"
    completed = "completed"
    failed = "failed"


class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    original_path = Column(String(512), nullable=False)
    translated_path = Column(String(512), nullable=True)
    source_language = Column(String(50), nullable=False, default="english")
    target_language = Column(String(50), nullable=False, default="italian")
    status = Column(SAEnum(BookStatus), default=BookStatus.uploaded)
    total_chapters = Column(Integer, default=0)
    translated_chapters = Column(Integer, default=0)
    analysis = Column(JSON, nullable=True)  # genre/tone/summary, reused when resuming
    token_profile = Column(JSON, nullable=True)  # cost_estimator.TokenProfile, computed once
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")
    glossary_entries = relationship(
        "GlossaryEntry", back_populates="book", cascade="all, delete-orphan"
    )
    translation_jobs = relationship(
        "TranslationJob", back_populates="book", cascade="all, delete-orphan"
    )


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    item_id = Column(String(255), nullable=False)
    title = Column(String(512), nullable=True)
    order_index = Column(Integer, nullable=False)
    original_html = Column(Text, nullable=True)
    translated_html = Column(Text, nullable=True)
    # Checkpoint: one translation per block (null = not translated yet), saved per chunk
    block_translations = Column(JSON, nullable=True)
    status = Column(SAEnum(ChapterStatus), default=ChapterStatus.pending)

    book = relationship("Book", back_populates="chapters")


class GlossaryEntry(Base):
    __tablename__ = "glossary_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    source_term = Column(String(255), nullable=False)
    target_term = Column(String(255), nullable=False)
    context = Column(Text, nullable=True)
    do_not_translate = Column(Boolean, default=False)
    user_edited = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    book = relationship("Book", back_populates="glossary_entries")


class CompendiumRecord(Base):
    """A compendium entry of a book (see agents/compendium.py)."""

    __tablename__ = "compendium_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    name = Column(String(255), nullable=False)
    kind = Column(String(20), nullable=False, default="character")
    gender = Column(String(10), nullable=False, default="unknown")
    aliases = Column(JSON, nullable=False, default=list)
    notes = Column(Text, nullable=False, default="")
    evidence = Column(Text, nullable=True)  # set when the translation corrected the gender
    user_edited = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Bookmark(Base):
    """A passage the translator was unsure about, revisited by the final doubt review."""

    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    unit = Column(Integer, nullable=False)  # Chapter.order_index
    block = Column(Integer, nullable=False)  # index in the unit's block_translations
    quote = Column(Text, nullable=False)  # the source words in doubt
    reason = Column(Text, nullable=False)
    source = Column(Text, nullable=True)  # the block's source text
    translation = Column(Text, nullable=True)  # its translation when flagged
    # a glossary change: the old translation of the term, replaced by the new one where it
    # occurs as is (no model call); elsewhere the model fixes the passage
    old_text = Column(Text, nullable=True)
    new_text = Column(Text, nullable=True)
    status = Column(String(10), nullable=False, default="open")  # open, fixed, kept
    resolution = Column(Text, nullable=True)  # the corrected translation, when fixed
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TranslationJob(Base):
    __tablename__ = "translation_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    params = Column(JSON, nullable=True)
    status = Column(String(50), default="running")
    progress = Column(Float, default=0.0)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    book = relationship("Book", back_populates="translation_jobs")


class QueueItem(Base):
    """A book waiting to be translated; the queue runs one book at a time, by position."""

    __tablename__ = "queue_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    position = Column(Integer, nullable=False)
    config = Column(JSON, nullable=False)  # run settings, see app.jobs.RunConfig
    # start from the glossary of the book translated just before it in the queue
    keep_glossary = Column(Boolean, default=False)
    keep_compendium = Column(Boolean, default=False)  # same, for the compendium
    # the queue (batch) the book was added to: id of its first item; carry-over stays inside it
    batch_id = Column(Integer, nullable=True)
    status = Column(String(20), default="pending")  # pending, running, paused, done, failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    provider_type = Column(String(50), nullable=False)  # openai, anthropic, ollama, custom
    api_key_encrypted = Column(Text, nullable=True)
    base_url = Column(String(512), nullable=True)
    default_model = Column(String(100), nullable=True)
    params = Column(JSON, nullable=True)  # temperature, max_tokens, top_p, etc.
    is_active = Column(Boolean, default=True)
    # 'config' = managed by config.yaml bootstrap, 'user' = created in the UI (NULL: legacy row)
    source = Column(String(20), nullable=True, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)
