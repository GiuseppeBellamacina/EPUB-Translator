"""
LLM Factory — creates LangChain chat model instances for any supported provider.

Supported providers:
- openai: OpenAI API (GPT-4o, GPT-4o-mini, etc.)
- anthropic: Anthropic API (Claude 3.5, Claude 4, etc.)
- ollama: Local Ollama instance
- custom: Any OpenAI-compatible API endpoint
- fake: Deterministic test provider (wraps sentences with BAU.../...MIAO)
"""

from typing import Any

from langchain_core.language_models import BaseChatModel


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
        **extra_params: Any,
    ):
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.extra_params = extra_params


def create_llm(config: LLMConfig) -> BaseChatModel:
    """Create a LangChain chat model from config."""

    params: dict[str, Any] = {
        "model": config.model,
        "temperature": config.temperature,
    }
    if config.max_tokens is not None:
        params["max_tokens"] = config.max_tokens
    if config.top_p is not None:
        params["top_p"] = config.top_p

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

            params["base_url"] = config.base_url or "http://localhost:11434"
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


async def test_llm_connection(config: LLMConfig) -> dict[str, Any]:
    """Test if an LLM config works by sending a simple ping."""
    try:
        llm = create_llm(config)
        response = await llm.ainvoke("Say 'ok' and nothing else.")
        return {"success": True, "response": response.content}
    except Exception as e:
        return {"success": False, "error": str(e)}
