"""Application configuration — loaded from ~/.resume_generator/config.yaml + env vars."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Token / context budget constants ─────────────────────────────────────────
# Centralised here so model swaps don't silently truncate in unexpected places.
MAX_JD_TEXT_CHARS: int = 48_000      # inclusive supported JD text limit
MAX_JD_STORAGE_CHARS: int = 48_000   # retained for compatibility; supported JDs are stored whole
MAX_RESUME_PARSE_CHARS: int = 48_000 # inclusive supported resume text limit
MAX_RESUME_UPLOAD_BYTES: int = 10 * 1024 * 1024
MAX_LLM_OUTPUT_TOKENS: int = 16_384  # max_tokens for all LLM calls — full LaTeX resume needs ~5–8k tokens

# ── Paths ──────────────────────────────────────────────────────────────────────

_OLD_CONFIG_DIR = Path.home() / ".resume_agent"   # pre-rename legacy location

_STATE_DIR_OVERRIDE = os.environ.get("RESUME_GENERATOR_STATE_DIR")
if _STATE_DIR_OVERRIDE is not None and not _STATE_DIR_OVERRIDE.strip():
    raise ValueError("RESUME_GENERATOR_STATE_DIR must not be empty")
CONFIG_DIR = (
    Path(_STATE_DIR_OVERRIDE).expanduser().resolve()
    if _STATE_DIR_OVERRIDE is not None
    else Path.home() / ".resume_generator"
)
CONFIG_FILE = CONFIG_DIR / "config.yaml"
SECRETS_FILE = CONFIG_DIR / ".env"        # API keys stored here (chmod 600)
SOURCE_DIR = CONFIG_DIR / "source"        # Drop your .pdf / .tex here
BASE_RESUME_FILE = CONFIG_DIR / "base_resume.yaml"
STATE_DB = CONFIG_DIR / "state.sqlite"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def migrate_config_dir() -> None:
    """Move ~/.resume_agent → ~/.resume_generator on first run after rename."""
    if _STATE_DIR_OVERRIDE is not None or CONFIG_DIR.exists() or not _OLD_CONFIG_DIR.exists():
        return
    try:
        shutil.copytree(str(_OLD_CONFIG_DIR), str(CONFIG_DIR))
    except Exception:
        pass


# ── Sub-configs ────────────────────────────────────────────────────────────────

class ModelConfig(BaseModel):
    default: str = "llama3.2"          # pullable local Ollama tag (default provider is ollama)
    vision: str = "claude-opus-4-8"


class ScrapingConfig(BaseModel):
    user_agent: str = "resume-generator/1.0"
    playwright_fallback: bool = True
    timeout_seconds: int = 30


class LatexConfig(BaseModel):
    tectonic_path: str = "tectonic"
    compile_timeout_seconds: int = 180


class OutputConfig(BaseModel):
    base_dir: str = "./output"


class RetriesConfig(BaseModel):
    generator_max: int = 5


class FeaturesConfig(BaseModel):
    enable_hr_review: bool = True  # opt-out: set false in config.yaml to skip HR pre-flight


class UIConfig(BaseModel):
    theme: str = "light"
    accent: str = "graphite"
    density: str = "comfortable"


# ── Main Settings ──────────────────────────────────────────────────────────────

class ResumeAgentSettings(BaseSettings):
    provider: Literal["anthropic", "openai", "ollama", "gemini", "nvidia", "openrouter", "commandcode"] = "ollama"
    model: ModelConfig = Field(default_factory=ModelConfig)
    scraping: ScrapingConfig = Field(default_factory=ScrapingConfig)
    latex: LatexConfig = Field(default_factory=LatexConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    retries: RetriesConfig = Field(default_factory=RetriesConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    # Passed via env or ~/.resume_generator/.env
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")
    nvidia_api_key: str | None = Field(default=None, alias="NVIDIA_API_KEY")
    ollama_api_key: str | None = Field(default=None, alias="OLLAMA_API_KEY")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    commandcode_api_key: str | None = Field(default=None, alias="COMMAND_CODE_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    nvidia_base_url: str = Field(default="", alias="NVIDIA_BASE_URL")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")

    model_config = SettingsConfigDict(
        env_prefix="RESUME_GENERATOR_",
        env_nested_delimiter="__",
        # An explicit state root must never inherit the project's dotenv file.
        env_file=[str(SECRETS_FILE)] if _STATE_DIR_OVERRIDE is not None else [".env", str(SECRETS_FILE)],
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    @classmethod
    def load(cls) -> ResumeAgentSettings:
        """Load from ~/.resume_generator/config.yaml, overlaid with env vars and SECRETS_FILE."""
        migrate_config_dir()
        file_data: dict = {}
        if CONFIG_FILE.exists():
            raw = CONFIG_FILE.read_text(encoding="utf-8")
            file_data = yaml.safe_load(raw) or {}
        # Use cls(**file_data) so pydantic-settings also reads env vars and
        # SECRETS_FILE (.env) for API keys — model_validate bypasses those sources.
        return cls(**file_data)

    def save(self) -> None:
        """Persist current settings to ~/.resume_generator/config.yaml."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Never write secrets into the YAML — they live in SECRETS_FILE
        data = self.model_dump(
            exclude={"anthropic_api_key", "openai_api_key", "gemini_api_key", "nvidia_api_key", "ollama_api_key", "openrouter_api_key", "commandcode_api_key"},
        )
        CONFIG_FILE.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")

    @property
    def output_base_dir(self) -> Path:
        return Path(self.output.base_dir)

    def is_configured(self) -> bool:
        """Return True if a config file exists and the provider key (if needed) is present."""
        if not CONFIG_FILE.exists():
            return False
        if self.provider != "ollama":
            return bool(getattr(self, f"{self.provider}_api_key", None))
        return True   # ollama needs no key
