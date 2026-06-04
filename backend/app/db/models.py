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
    completed = "completed"
    failed = "failed"


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
    created_at = Column(DateTime, default=datetime.utcnow)
