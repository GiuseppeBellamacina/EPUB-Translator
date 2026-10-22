"""Database initialization and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateColumn

from app.core.config import settings
from app.db.models import Base

DATABASE_URL = f"sqlite+aiosqlite:///{settings.db_path}"

engine = create_async_engine(DATABASE_URL, echo=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _add_missing_columns(conn) -> None:
    """Minimal auto-migration: ALTER TABLE ADD COLUMN for model columns missing in the DB.

    shortcut: only handles added nullable columns; renames/type changes need a real
    migration tool (Alembic) if the schema starts evolving that way.
    """
    inspector = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in existing:
                ddl = CreateColumn(column).compile(dialect=conn.dialect)
                conn.exec_driver_sql(f"ALTER TABLE {table.name} ADD COLUMN {ddl}")


async def init_db():
    """Create all tables and add columns introduced since the DB was created."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI routes."""
    async with async_session() as session:
        yield session
