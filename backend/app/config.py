from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    app_env: str
    host: str
    port: int
    api_token: str
    claude_model: str
    claude_allowed_models: tuple[str, ...]
    claude_warmup_prompt: str
    claude_dangerously_skip_permissions: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        allowed_models = tuple(
            model.strip()
            for model in os.getenv(
                "CLAUDE_ALLOWED_MODELS",
                "claude-haiku-4-5-20251001,claude-sonnet-4-6,claude-opus-4-6",
            ).split(",")
            if model.strip()
        )

        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            host=os.getenv("APP_HOST", "127.0.0.1"),
            port=int(os.getenv("APP_PORT", "8000")),
            api_token=os.getenv("API_TOKEN", "").strip(),
            claude_model=os.getenv("CLAUDE_MODEL", allowed_models[0] if allowed_models else "claude-haiku-4-5-20251001"),
            claude_allowed_models=allowed_models,
            claude_warmup_prompt=os.getenv("CLAUDE_WARMUP_PROMPT", "ok"),
            claude_dangerously_skip_permissions=os.getenv("CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS", "true").strip().lower()
            in {"1", "true", "yes", "on"},
        )

    def validate_model(self, model: str | None) -> str:
        chosen = (model or self.claude_model).strip()
        if chosen not in self.claude_allowed_models:
            raise ValueError(f"Unsupported Claude model: {chosen}")
        return chosen

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_token)
