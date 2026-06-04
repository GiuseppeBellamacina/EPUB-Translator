"""
Fake LLM — a deterministic chat model for testing the translation pipeline
without calling any real provider.

Its "translation" simply wraps every sentence with ``BAU`` at the start and
``MIAO`` at the end, so the effect of the pipeline is obvious and verifiable.
It also satisfies the structured-output calls made by the analyzer and reviewer
agents (returning a trivial analysis and always approving translations).
"""

import re
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda

from app.models.schemas import AnalysisResult, ReviewResult, TranslationResult

_TRANSLATE_MARKER = re.compile(r"TRANSLATE the following from .*?:\s*\n\n(.*)$", re.DOTALL)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def meow_transform(text: str) -> str:
    """Wrap each sentence with ``BAU`` at the start and ``MIAO`` at the end.

    Paragraph breaks (``\\n\\n``) are preserved so EPUB structure stays intact.
    """
    paragraphs = text.split("\n\n")
    transformed_paragraphs: list[str] = []
    for paragraph in paragraphs:
        stripped = paragraph.strip()
        if not stripped:
            transformed_paragraphs.append(paragraph)
            continue
        sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s]
        transformed = " ".join(f"BAU {sentence} MIAO" for sentence in sentences)
        transformed_paragraphs.append(transformed)
    return "\n\n".join(transformed_paragraphs)


def _extract_human_text(messages: list[BaseMessage]) -> str:
    """Return the content of the last human message in the prompt."""
    for message in reversed(messages):
        if message.type == "human":
            return str(message.content)
    return ""


def _extract_source_text(human_text: str) -> str:
    """Pull out the text to translate from the rendered human prompt."""
    match = _TRANSLATE_MARKER.search(human_text)
    return match.group(1).strip() if match else human_text.strip()


class FakeChatModel(BaseChatModel):
    """A deterministic chat model that BAU-wraps/MIAO-wraps sentences."""

    model_name: str = "fake-meow"

    @property
    def _llm_type(self) -> str:
        return "fake-meow"

    def _build_result(self, schema: type, messages: list[BaseMessage]) -> Any:
        """Build a structured-output instance for the requested schema."""
        if schema is TranslationResult:
            source = _extract_source_text(_extract_human_text(messages))
            return TranslationResult(translated_text=meow_transform(source), new_terms=[])
        if schema is AnalysisResult:
            return AnalysisResult(
                genre="test",
                tone="neutral",
                characters=[],
                key_terms=[],
                do_not_translate=[],
                summary="Fake analysis produced by the BAU/MIAO test provider.",
            )
        if schema is ReviewResult:
            return ReviewResult(
                approved=True,
                issues=[],
                corrected_text=None,
                glossary_violations=[],
            )
        # Fallback: best-effort empty instance.
        return schema()  # type: ignore[call-arg]

    def with_structured_output(  # type: ignore[override]
        self,
        schema: Any,
        **kwargs: Any,
    ) -> Runnable:
        """Return a runnable that deterministically produces ``schema`` instances."""

        def _invoke(prompt_value: Any) -> Any:
            if hasattr(prompt_value, "to_messages"):
                messages = prompt_value.to_messages()
            elif isinstance(prompt_value, list):
                messages = prompt_value
            else:
                messages = [AIMessage(content=str(prompt_value))]
            return self._build_result(schema, messages)

        return RunnableLambda(_invoke)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = AIMessage(content="ok")
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, **kwargs)
