from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All config comes from environment variables (or a local .env file)."""

    # Real environment variables win over .env; extra keys in .env (like POSTGRES_USER) are ignored.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://relay:relay@localhost:5432/relay"
    redis_url: str = "redis://localhost:6379/0"
    # No default on purpose: the app refuses to start without one, so it's never left guessable.
    admin_token: str
    # Seconds to wait before each retry: 5s, 30s, 2m, 10m, so 5 attempts in all before a
    # delivery is marked dead. Set RETRY_DELAYS='[1,2,3,4]' locally to watch it happen quickly.
    retry_delays: list[float] = [5, 30, 120, 600]


settings = Settings()
