import time

import httpx
import openai
import pytest

from app.agents.translator_agent import translate_chunk
from app.core.llm_factory import LLMConfig, create_llm, structured
from app.models.schemas import TranslationResult


def _rate_limit_error() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.example/v1/chat/completions")
    return openai.RateLimitError("429", response=httpx.Response(429, request=request), body=None)


async def _translate(llm):
    return await translate_chunk(
        llm=llm,
        text="Hello.",
        context="",
        chapter_summary="",
        glossary=[],
        source_language="english",
        target_language="italian",
    )


async def test_transient_429_is_retried(llm, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.chain_retries", 3)
    llm.fail[TranslationResult] = [_rate_limit_error(), _rate_limit_error()]
    result = await _translate(llm)
    assert result.translated_text == "BAU Hello. MIAO"
    assert len(llm.calls_for(TranslationResult)) == 3


async def test_persistent_failure_raises_after_retries(llm, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.chain_retries", 2)
    llm.fail[TranslationResult] = [_rate_limit_error()] * 5
    with pytest.raises(openai.RateLimitError):
        await _translate(llm)
    assert len(llm.calls_for(TranslationResult)) == 2


def test_create_llm_wires_rate_limit_retries_and_method():
    llm = create_llm(
        LLMConfig(
            provider="custom",
            model="m:free",
            base_url="https://x/api/v1",
            requests_per_second=0.25,
            max_retries=7,
            structured_output_method="function_calling",
        )
    )
    assert llm.rate_limiter is not None
    assert llm.max_retries == 7
    assert llm.metadata == {"structured_output_method": "function_calling"}
    assert structured(llm, TranslationResult) is not None


def test_reasoning_models_get_no_temperature():
    assert (
        create_llm(LLMConfig(provider="openai", model="gpt-5-nano", api_key="x")).temperature
        is None
    )
    assert (
        create_llm(LLMConfig(provider="openai", model="gpt-4.1-nano", api_key="x")).temperature
        == 0.0
    )


async def test_rate_limiter_spaces_requests():
    from langchain_core.rate_limiters import InMemoryRateLimiter

    limiter = InMemoryRateLimiter(
        requests_per_second=20, check_every_n_seconds=0.01, max_bucket_size=1
    )
    start = time.monotonic()
    for _ in range(4):
        await limiter.aacquire()
    assert time.monotonic() - start >= 0.1
