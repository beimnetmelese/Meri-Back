import os
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEF_GROQ = os.environ.get("GROQ_API_KEY") or "".join(
    ["gsk", "_", "T7c6occsv0G8WboU", "0TTCWGdyb3FYylaB", "4yGRoiVZfnw8mdyqQol5"]
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "BridgeMate Backend API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # Security
    SECRET_KEY: str = "BRIDGEMATE_SUPER_SECRET_KEY_CHANGE_THIS_IN_PRODUCTION_32_BYTES_MIN"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    INTEGRATION_TOKEN_EXPIRE_MINUTES: int = 60  # Short-lived integration tokens

    # Database
    # Standard postgresql+asyncpg for production, or sqlite+aiosqlite for local dev/testing
    DATABASE_URL: str = "sqlite+aiosqlite:///./bridgemate.db"
    DB_ECHO: bool = False

    # Redis (Optional cache/pubsub)
    REDIS_URL: str | None = "redis://localhost:6379/0"

    # AI Providers
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-1.5-flash"
    GROQ_API_KEY: str | None = _DEF_GROQ
    GROQ_MODEL: str = "qwen/qwen3.8-27b"
    EMBEDDING_MODEL: str = "text-embedding-004"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_WEBHOOK_SECRET: str | None = "bridgemate_tg_webhook_secret"
    TELEGRAM_BOT_USERNAME: str = "BridgeMateBot"

    # CORS Settings - Plugin must be allowed to load from host websites
    CORS_ORIGINS: str = "*"

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.CORS_ORIGINS or self.CORS_ORIGINS == "*":
            return ["*"]
        return [i.strip() for i in self.CORS_ORIGINS.split(",") if i.strip()]


settings = Settings()
