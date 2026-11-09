from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All config comes from environment variables (or a local .env file)."""

    # Real environment variables win over .env; extra keys in .env (like POSTGRES_USER) are ignored.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://relay:relay@localhost:5432/relay"
    redis_url: str = "redis://localhost:6379/0"
    # No default on purpose: the app refuses to start without one, so it's never left guessable.
    admin_token: str


settings = Settings()
