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


@pytest.mark.parametrize(
    "provider, model, temperature",
    [
        ("openai", "gpt-4.1-nano", True),
        ("openai", "gpt-4o-mini", True),
        ("openai", "gpt-5-mini", False),
        ("openai", "gpt-6-luna", False),  # newer families must not need a code change
        ("openai", "gpt-10", False),
        ("openai", "o3-mini", False),
        ("openai", "o5", False),
        ("custom", "openai/gpt-6-luna", False),  # router name
        ("custom", "meta-llama/llama-3.3-70b-instruct:free", True),
        ("ollama", "qwen3:8b", True),
    ],
)
def test_openai_reasoning_models_get_no_temperature(provider, model, temperature):
    from app.core.llm_factory import accepts_temperature

    assert accepts_temperature(provider, model) is temperature


@pytest.mark.parametrize(
    "model, temperature, thinks",
    [
        ("claude-haiku-4-5", True, False),
        ("claude-haiku-4-5-20251001", True, False),
        ("claude-sonnet-4-6", True, False),
        ("claude-opus-4-7", False, False),
        ("claude-sonnet-5", False, True),
        ("claude-haiku-5-5", False, True),
        ("claude-opus-5-5", False, True),
    ],
)
def test_claude_sampling_and_thinking_rules(model, temperature, thinks):
    from app.core.llm_factory import accepts_temperature, thinks_by_default

    assert accepts_temperature("anthropic", model) is temperature
    assert thinks_by_default("anthropic", model, supports_reasoning=True) is thinks


def test_every_call_has_an_output_cap_and_a_timeout():
    nano = create_llm(LLMConfig(provider="openai", model="gpt-4.1-nano", api_key="x"))
    assert nano.max_tokens == 4096 and nano.request_timeout == 120
    reasoning = create_llm(LLMConfig(provider="openai", model="gpt-5-nano", api_key="x"))
    assert reasoning.max_tokens == 16384
    claude = create_llm(LLMConfig(provider="anthropic", model="claude-haiku-5-5", api_key="x"))
    assert claude.max_tokens == 16384 and claude.default_request_timeout == 120
    explicit = create_llm(
        LLMConfig(provider="custom", model="m", base_url="https://x/v1", max_tokens=100)
    )
    assert explicit.max_tokens == 100


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
