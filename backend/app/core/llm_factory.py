"""
LLM Factory — creates LangChain chat model instances for any supported provider.

Supported providers:
- openai: OpenAI API (GPT-4o, GPT-4o-mini, etc.)
- anthropic: Anthropic API (Claude 3.5, Claude 4, etc.)
- ollama: Local Ollama instance
- custom: Any OpenAI-compatible API endpoint
- fake: Deterministic test provider (wraps sentences with BAU.../...MIAO)

Resilience: an optional client-side rate limiter (requests per second) throttles
calls, and the provider SDKs retry 429/5xx with exponential backoff (``max_retries``).
"""

import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import Runnable

from app.core.config import settings

# OpenAI reasoning models (gpt-5 and later, the o-series) only accept the default temperature;
# by family, not a list of names, so new models (gpt-6-luna, o5) are covered.
_OPENAI_REASONING = re.compile(r"(gpt-([5-9]|\d{2,})|o\d)(?!\d)")
_CLAUDE_VERSION = re.compile(r"claude-[a-z]+-(\d+)(?:-(\d{1,2}))?(?!\d)")


def _claude_version(model: str) -> tuple[int, int] | None:
    match = _CLAUDE_VERSION.match(model)
    return (int(match.group(1)), int(match.group(2) or 0)) if match else None


def accepts_temperature(provider: str, model: str) -> bool:
    """Claude Opus 4.7+ and the 5.x family reject non-default sampling parameters (400)."""
    if provider == "anthropic":
        version = _claude_version(model)
        return version is None or version < (4, 7)
    # router names carry a vendor prefix: openai/gpt-6-luna
    return not _OPENAI_REASONING.match(model.rsplit("/", 1)[-1].lower())


def thinks_by_default(provider: str, model: str, supports_reasoning: bool) -> bool:
    """Whether a request without thinking settings makes the model reason (billed as output).

    OpenAI reasoning models always do; Claude 5.x runs adaptive thinking unless told
    otherwise, while older Claude models only think when explicitly enabled.
    """
    if provider == "anthropic":
        version = _claude_version(model)
        return supports_reasoning and version is not None and version >= (5, 0)
    return supports_reasoning


class LLMConfig:
    """Configuration for an LLM provider instance."""

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        top_p: float | None = None,
        requests_per_second: float | None = None,
        max_retries: int | None = None,
        structured_output_method: str | None = None,
        **extra_params: Any,
    ):
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.requests_per_second = requests_per_second
        self.max_retries = max_retries
        self.structured_output_method = structured_output_method
        self.extra_params = extra_params


def create_llm(config: LLMConfig) -> BaseChatModel:
    """Create a LangChain chat model from config."""

    params: dict[str, Any] = {"model": config.model}
    if accepts_temperature(config.provider, config.model):
        params["temperature"] = config.temperature
    if config.max_tokens is not None:
        params["max_tokens"] = config.max_tokens
    elif config.provider in ("openai", "anthropic", "custom"):
        # Bound every call: a model stuck repeating itself otherwise runs to its own
        # maximum (32k tokens, minutes) before failing. Reasoning models get more
        # room because thinking counts against the same limit.
        params["max_tokens"] = (
            settings.llm_max_output_tokens
            if accepts_temperature(config.provider, config.model)
            else settings.llm_reasoning_max_output_tokens
        )
    if config.provider in ("openai", "anthropic", "custom") and settings.llm_timeout:
        params["timeout"] = settings.llm_timeout  # per request; SDK default is 10 minutes
    if config.top_p is not None:
        params["top_p"] = config.top_p
    if config.requests_per_second:
        params["rate_limiter"] = InMemoryRateLimiter(
            requests_per_second=config.requests_per_second,
            check_every_n_seconds=0.1,
            max_bucket_size=1,
        )
    if config.structured_output_method:
        params["metadata"] = {"structured_output_method": config.structured_output_method}
    if config.max_retries is not None and config.provider in ("openai", "anthropic", "custom"):
        params["max_retries"] = config.max_retries

    match config.provider:
        case "fake":
            from app.core.fake_llm import FakeChatModel

            return FakeChatModel(model_name=config.model or "fake-meow")

        case "openai":
            from langchain_openai import ChatOpenAI

            if config.api_key:
                params["api_key"] = config.api_key
            if config.base_url:
                params["base_url"] = config.base_url
            params.update(config.extra_params)
            return ChatOpenAI(**params)

        case "anthropic":
            from langchain_anthropic import ChatAnthropic

            if config.api_key:
                params["api_key"] = config.api_key
            if config.base_url:
                params["base_url"] = config.base_url
            params["model_name"] = params.pop("model")
            params.update(config.extra_params)
            return ChatAnthropic(**params)

        case "ollama":
            from langchain_ollama import ChatOllama

            params["base_url"] = config.base_url or settings.ollama_base_url
            params.update(config.extra_params)
            return ChatOllama(**params)

        case "custom":
            # OpenAI-compatible endpoint (vLLM, LMStudio, Together, etc.)
            from langchain_openai import ChatOpenAI

            if not config.base_url:
                raise ValueError("Custom provider requires base_url")
            params["base_url"] = config.base_url
            if config.api_key:
                params["api_key"] = config.api_key
            else:
                params["api_key"] = "not-needed"
            params.update(config.extra_params)
            return ChatOpenAI(**params)

        case _:
            raise ValueError(f"Unsupported provider: {config.provider}")


def structured(llm: BaseChatModel, schema: type) -> Runnable:
    """``llm.with_structured_output`` honouring the provider's configured method.

    Some OpenAI-compatible endpoints (e.g. free OpenRouter models) lack ``json_schema``
    support and need ``function_calling`` or ``json_mode``.
    """
    method = (llm.metadata or {}).get("structured_output_method")
    if method:
        return llm.with_structured_output(schema, method=method)
    return llm.with_structured_output(schema)


def structured_chain(
    prompt: Runnable, llm: BaseChatModel, schema: type, attempts: int | None = None
) -> Runnable:
    """``prompt | structured output`` retried as a whole on any failure.

    Covers what SDK retries don't: unparsable/invalid structured output and errors
    that outlast the SDK's own backoff. ``attempts`` defaults to ``chain_retries``.
    """
    return (prompt | structured(llm, schema)).with_retry(
        stop_after_attempt=max(1, attempts or settings.chain_retries),
        wait_exponential_jitter=True,
    )


async def test_llm_connection(config: LLMConfig) -> dict[str, Any]:
    """Test if an LLM config works by sending a simple ping."""
    try:
        llm = create_llm(config)
        response = await llm.ainvoke("Say 'ok' and nothing else.")
        return {"success": True, "response": response.content}
    except Exception as e:
        return {"success": False, "error": str(e)}
