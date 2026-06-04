from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "EPUB Translator"
    debug: bool = False

    # Paths
    data_dir: Path = Path("data")
    uploads_dir: Path = Path("data/uploads")
    translated_dir: Path = Path("data/translated")
    db_path: Path = Path("data/epub_translator.db")

    # Encryption key for API keys stored in DB
    encryption_key: str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    class Config:
        env_file = ".env"
        env_prefix = "EPUB_"


settings = Settings()

# Ensure directories exist
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.translated_dir.mkdir(parents=True, exist_ok=True)
