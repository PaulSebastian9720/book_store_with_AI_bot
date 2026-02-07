from pathlib import Path
from pydantic_settings import BaseSettings

# Resolve .env relative to this file (backend_library/.env)
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://bookstore:bookstore123@localhost:5432/bookstore"
    database_url_sync: str = "postgresql://bookstore:bookstore123@localhost:5432/bookstore"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4jpassword"

    # ── LLM provider ────────────────────────────────────────────────────────
    # Para usar OpenAI:  llm_provider="openai"  (necesita OPENAI_API_KEY)
    # Para usar Ollama:  llm_provider="ollama"   (necesita Ollama corriendo local)
    llm_provider: str = "ollama"   # "openai" | "ollama"

    # OpenAI settings
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Ollama settings (local, sin API key)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # ── Embeddings ──────────────────────────────────────────────────────────
    embedding_model_name: str = "all-MiniLM-L6-v2"
    similarity_threshold: float = 0.45
    combined_similarity_threshold: float = 0.30
    confidence_gap_threshold: float = 0.05
    high_confidence_threshold: float = 0.65

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"


settings = Settings()
