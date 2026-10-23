from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRANSLATIO_", extra="ignore")

    app_name: str = "Translatio"
    debug: bool = False

    # Single data directory (repo-root data/ mounted at /data in the containers)
    data_dir: Path = Path("/data")

    # Encryption key for API keys stored in DB
    encryption_key: str = ""

    # Provider bootstrap: .env with API keys (mounted as a file) and the dev config.yaml
    env_file: Path | None = None
    config_file: Path = Path("/config/config.yaml")

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Translation defaults; overridable by config.yaml `translation:` and per provider `params`
    max_concurrency: int = 2  # chapters translated in parallel
    requests_per_second: float = 0.5  # client-side rate limit per job (0 = unlimited)
    llm_max_retries: int = 5  # SDK retries with backoff (honours Retry-After on 429)
    chain_retries: int = 3  # retries of a whole agent call (parse errors, residual failures)
    llm_max_output_tokens: int = 4096  # per call; a chunk is <= ~1000 source tokens
    llm_reasoning_max_output_tokens: int = 16384  # reasoning models: thinking shares the cap
    llm_timeout: float = 120  # seconds per request (0 = SDK default, 10 minutes)

    # Ollama on the host, seen from the backend container (provider base_url overrides it)
    ollama_base_url: str = "http://host.docker.internal:11434"
    enable_review: bool = True

    # Model prices for cost estimates (LiteLLM's public list; "" = offline, bundled snapshot)
    pricing_url: str = (
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    )
    pricing_refresh_hours: float = 24

    def apply_overrides(self, overrides: dict) -> None:
        for key, value in overrides.items():
            if key in type(self).model_fields:
                setattr(self, key, value)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def translated_dir(self) -> Path:
        return self.data_dir / "translated"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "translatio.db"

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.translated_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
