from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EPUB_", extra="ignore")

    app_name: str = "EPUB Translator"
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

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def translated_dir(self) -> Path:
        return self.data_dir / "translated"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "epub_translator.db"

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.translated_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
