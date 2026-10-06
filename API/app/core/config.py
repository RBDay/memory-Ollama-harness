from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Memory Ollama API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # MongoDB Settings
    MONGO_URI: str = "mongodb://mongo:27017/"
    DATABASE_NAME: str = "memory"
    SESSIONS_COLLECTION: str = "sessions"
    MEMORY_COLLECTION: str = "memory"

    # Ollama Settings
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434/v1"
    MODEL_NAME: str = "qwen2.5-coder:7b"
    OLLAMA_TIMEOUT: float = 120.0

    model_config = SettingsConfigDict(
        env_file=(".env", "app/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()