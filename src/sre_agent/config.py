"""Configuration and environment for the SRE agent."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Agent settings loaded from environment and .env."""

    model_config = SettingsConfigDict(
        env_prefix="SRE_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Kubernetes
    kubeconfig: Path | None = Field(
        default=None,
        description="Path to kubeconfig; uses KUBECONFIG env or default location if unset",
    )
    context: str | None = Field(default=None, description="Kubernetes context to use")
    namespace: str = Field(default="default", description="Namespace to operate in")

    # LLM
    llm_provider: Literal["openai", "openai_compatible"] = Field(
        default="openai",
        description="LLM provider: openai or openai_compatible (e.g. local Ollama)",
    )
    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    openai_base_url: str | None = Field(
        default=None,
        description="Base URL for OpenAI-compatible API (e.g. http://localhost:11434/v1)",
    )
    model: str = Field(
        default="gpt-4o-mini",
        description="Model name for diagnosis and remediation reasoning",
    )
    temperature: float = Field(default=0.1, ge=0.0, le=2.0, description="LLM temperature")

    # Agent behavior
    dry_run: bool = Field(
        default=False,
        description="If true, diagnose only; do not apply remediation",
    )
    max_remediation_attempts: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Max attempts to apply a remediation before giving up",
    )


def get_settings() -> Settings:
    """Return validated settings instance."""
    return Settings()
