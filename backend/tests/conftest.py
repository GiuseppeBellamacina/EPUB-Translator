"""Shared fixtures. The data dir is pointed at a temp folder before `app` is imported."""

import asyncio
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

os.environ["EPUB_DATA_DIR"] = tempfile.mkdtemp(prefix="epub-tests-")
# Never bootstrap real providers from the developer's .env/config.yaml in tests
os.environ["EPUB_ENV_FILE"] = "/nonexistent/.env"
os.environ["EPUB_CONFIG_FILE"] = "/nonexistent/config.yaml"

import pytest  # noqa: E402
from langchain_core.runnables import Runnable, RunnableLambda  # noqa: E402
from pydantic import PrivateAttr  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.fake_llm import FakeChatModel, _extract_human_text  # noqa: E402
from scripts.make_sample_epub import write_sample_epub  # noqa: E402

settings.ensure_dirs()


class ScriptedLLM(FakeChatModel):
    """FakeChatModel with per-schema handlers, call log, error injection and concurrency tracking.

    - ``handlers[Schema](human_text, call_no)`` overrides the default fake output for a schema.
    - ``fail[Schema]`` is a list of exceptions raised (in order) by the next calls for that schema.
    - ``delay`` makes each call await, so concurrent callers overlap and ``peak`` is meaningful.
    """

    delay: float = 0.0
    _handlers: dict[type, Callable[[str, int], Any]] = PrivateAttr(default_factory=dict)
    _fail: dict[type, list[Exception]] = PrivateAttr(default_factory=dict)
    _calls: list[tuple[type, str]] = PrivateAttr(default_factory=list)
    _active: int = PrivateAttr(default=0)
    _peak: int = PrivateAttr(default=0)

    @property
    def handlers(self) -> dict[type, Callable[[str, int], Any]]:
        return self._handlers

    @property
    def fail(self) -> dict[type, list[Exception]]:
        return self._fail

    @property
    def calls(self) -> list[tuple[type, str]]:
        return self._calls

    @property
    def peak(self) -> int:
        return self._peak

    def calls_for(self, schema: type) -> list[str]:
        return [text for s, text in self._calls if s is schema]

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable:  # type: ignore[override]
        def _messages(prompt_value: Any) -> list:
            return prompt_value.to_messages() if hasattr(prompt_value, "to_messages") else []

        def _invoke(prompt_value: Any) -> Any:
            messages = _messages(prompt_value)
            human = _extract_human_text(messages)
            self._calls.append((schema, human))
            pending = self._fail.get(schema)
            if pending:
                raise pending.pop(0)
            handler = self._handlers.get(schema)
            if handler:
                return handler(human, len(self.calls_for(schema)))
            return self._build_result(schema, messages)

        async def _ainvoke(prompt_value: Any) -> Any:
            self._active += 1
            self._peak = max(self._peak, self._active)
            try:
                if self.delay:
                    await asyncio.sleep(self.delay)
                return _invoke(prompt_value)
            finally:
                self._active -= 1

        return RunnableLambda(_invoke, afunc=_ainvoke)


async def translate(path: Path, pipeline, output: Path | None = None, **kwargs) -> list:
    """Run translate_document on a file and return all events."""
    from app.services.documents import open_document
    from app.services.translation_service import translate_document

    output = output or path.with_name("out" + path.suffix)
    doc = open_document(path)
    return [e async for e in translate_document(doc, pipeline, output, **kwargs)]


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def sample_epub(tmp_path: Path) -> Path:
    return write_sample_epub(tmp_path / "sample_en.epub")


@pytest.fixture
async def db():
    """Fresh schema for each test."""
    from app.db.database import engine, init_db
    from app.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()
    yield
