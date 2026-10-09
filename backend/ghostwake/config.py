from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="GW_", extra="ignore")

    # SQLite works out of the box for local runs and tests.
    # In production point this at Neon: postgresql+psycopg://user:pass@host/db?sslmode=require
    database_url: str = "sqlite:///./ghostwake.db"

    # Anyone can read. Only requests carrying this token may escalate or dismiss alerts.
    analyst_token: str = "change-me"

    cors_origins: str = "http://localhost:5173"

    # Requests per minute per client. Keeps one open tab from burning the free LLM quota.
    copilot_per_minute: int = 15
    review_per_minute: int = 30

    # Copilot. Any OpenAI-compatible endpoint works: Groq, Gemini's OpenAI layer, or local Ollama.
    # Leave llm_base_url empty and the copilot falls back to a deterministic briefing writer.
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # Thresholds. Every number here is a judgment call; see docs/adr/0003-alert-thresholds.md
    gap_hours: float = 6.0
    spoof_knots: float = 40.0
    rendezvous_km: float = 0.5
    rendezvous_hours: float = 2.0
    imbl_warn_km: float = 5.0
    match_gate_km: float = 1.5

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
