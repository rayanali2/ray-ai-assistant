"""Application configuration.

Every setting comes from the environment (ADR-0012). Nothing is hardcoded and no
secret ever lives in source.
"""

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _parse_list(value: Any) -> Any:
    """Support JSON arrays or comma-separated strings for list settings."""
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            return json.loads(value)
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAY_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = 8000

    # Single-user bearer token (ADR-0006).
    api_token: str = "change-me"

    database_url: str = "postgresql+asyncpg://ray:ray@localhost:5433/ray"

    user_name: str = "Ray User"
    user_email: str | None = None
    user_timezone: str = "UTC"

    # LLM provider selection (ADR-0001, ADR-0015). "mock" is always appended to the
    # chain, so Ray answers even with nothing configured.
    llm_provider: Literal["gemini", "ollama", "mock"] = "gemini"
    llm_router_provider: Literal["gemini", "ollama", "mock"] | None = None
    llm_fallback_provider: Literal["gemini", "ollama", "mock"] | None = "ollama"

    # Provider credentials and models. The key is a secret: it is read from the
    # environment, never logged, and never written to the database.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    # Bounds on a single Gemini request. The registry fallback chain handles
    # retries across providers; long SDK retries against an overloaded endpoint
    # are what cause 60-90 second chat hangs.
    gemini_timeout_ms: int = 15_000
    gemini_retry_attempts: int = 1
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    # Slows the mock stream so streaming is visible during development.
    mock_stream_delay_seconds: float = 0.0

    # Conversation shaping.
    llm_temperature: float = 0.7
    history_window: int = 20

    # Local embeddings (ADR-0003). The dimension must match the vector column, so
    # changing it means a migration, not just a restart.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    # "hashing" needs no torch install and no download (ADR-0016). The
    # sentence-transformer backend falls back to it rather than failing.
    embedding_backend: Literal["sentence-transformers", "hashing"] = "sentence-transformers"

    # Agent tool execution (ADR-0010, ADR-0014).
    tool_timeout_seconds: float = 30.0

    # Memory (ADR-0013).
    memory_enabled: bool = True
    # Extraction costs one cheap model call per exchange, off the response path.
    memory_extraction_enabled: bool = True
    memory_top_k: int = 5
    # A weak match is worse than no match: it spends context and invites the model
    # to use an irrelevant fact.
    memory_min_score: float = 0.35
    # Roughly 25% of a small context window, in characters (ADR-0013).
    memory_context_chars: int = 2_000

    # Voice (ADR-0009). Browser backends work with zero setup; local backends
    # (faster-whisper, Piper) land in Phase 6.
    stt_backend: Literal["browser", "local"] = "browser"
    tts_backend: Literal["browser", "local"] = "browser"
    wake_word_enabled: bool = False
    # faster-whisper model size ("tiny", "base", "small" ...) or path to a converted model.
    stt_model: str = "tiny"
    stt_language: str | None = None
    # Directory where downloaded Piper/openWakeWord models live. TTS resolves a
    # relative tts_voice against this directory.
    voice_models_dir: str = "~/.local/share/ray/voices"
    # Path to a Piper .onnx voice model. A bare filename is resolved inside voice_models_dir.
    tts_voice: str = "en_US-lessac-low.onnx"
    tts_length_scale: float = 1.0
    # Path to an openWakeWord .tflite model. Empty disables server-side wake word.
    wake_word_model: str = ""
    wake_words: Annotated[list[str], NoDecode, BeforeValidator(_parse_list)] = Field(
        default_factory=lambda: ["ray", "jarvis"]
    )

    cors_origins: Annotated[list[str], NoDecode, BeforeValidator(_parse_list)] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    @property
    def is_development(self) -> bool:
        return self.env == "development"


@lru_cache
def get_settings() -> Settings:
    """Cached so configuration is read once per process."""
    return Settings()
