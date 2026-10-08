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
    EMBEDDING_MODEL: str = "nomic-embed-text"
    OLLAMA_TIMEOUT: float = 120.0

    # MinIO / LanceDB Settings
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadminpassword"
    MINIO_BUCKET: str = "lancedb"
    MINIO_REGION: str = "us-east-1"
    MINIO_SECURE: bool = False

    # Vector RAG Settings
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    VECTOR_TOP_K: int = 5

    model_config = SettingsConfigDict(
        env_file=(".env", "app/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()