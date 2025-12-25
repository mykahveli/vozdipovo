# ficheiro: src/vozdipovo_app/llm/settings.py

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GroqSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    api_key: str = Field(validation_alias=AliasChoices("GROQ_API_KEY", "groq_api_key"))
    timeout_seconds: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "GROQ_TIMEOUT_SECONDS",
            "groq_timeout_seconds",
        ),
    )
    base_url: str = Field(
        default="https://api.groq.com/openai/v1",
        validation_alias=AliasChoices("GROQ_BASE_URL", "groq_base_url"),
    )


class OpenRouterSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    api_key: str = Field(
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "openrouter_api_key")
    )
    timeout_seconds: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "OPENROUTER_TIMEOUT_SECONDS",
            "openrouter_timeout_seconds",
        ),
    )
    base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias=AliasChoices("OPENROUTER_BASE_URL", "openrouter_base_url"),
    )
