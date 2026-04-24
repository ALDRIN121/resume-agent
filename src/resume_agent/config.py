"""Application configuration — loaded from ~/.resume_generator/config.yaml + env vars."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Token / context budget constants ─────────────────────────────────────────
# Centralised here so model swaps don't silently truncate in unexpected places.
MAX_JD_TEXT_CHARS: int = 8_000       # scraped JD text sent to jd_extractor
MAX_JD_STORAGE_CHARS: int = 2_000    # JD raw_text stored on JobDescription
MAX_RESUME_JSON_CHARS: int = 6_000   # resume JSON sent to gap_analyzer / hitl
MAX_RESUME_PARSE_CHARS: int = 12_000 # resume text sent to base_resume_loader
MAX_LLM_OUTPUT_TOKENS: int = 4_096   # max_tokens for all LLM calls

# ── Paths ──────────────────────────────────────────────────────────────────────

_OLD_CONFIG_DIR = Path.home() / ".resume_agent"   # pre-rename legacy location

CONFIG_DIR = Path.home() / ".resume_generator"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
SECRETS_FILE = CONFIG_DIR / ".env"        # API keys stored here (chmod 600)
SOURCE_DIR = CONFIG_DIR / "source"        # Drop your .pdf / .tex here
BASE_RESUME_FILE = CONFIG_DIR / "base_resume.yaml"
STATE_DB = CONFIG_DIR / "state.sqlite"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def migrate_config_dir() -> None:
    """Move ~/.resume_agent → ~/.resume_generator on first run after rename."""
    if CONFIG_DIR.exists() or not _OLD_CONFIG_DIR.exists():
        return
    try:
        shutil.copytree(str(_OLD_CONFIG_DIR), str(CONFIG_DIR))
    except Exception:
        pass


# ── Sub-configs ────────────────────────────────────────────────────────────────

class ModelConfig(BaseModel):
    default: str = "gemma4:31b-cloud"
    vision: str = "claude-opus-4-6"


class ScrapingConfig(BaseModel):
    user_agent: str = "resume-generator/1.0"
    playwright_fallback: bool = True
    timeout_seconds: int = 30


class LatexConfig(BaseModel):
    tectonic_path: str = "tectonic"
    compile_timeout_seconds: int = 60


class OutputConfig(BaseModel):
    base_dir: str = "./output"


class RetriesConfig(BaseModel):
    generator_max: int = 5


# ── Main Settings ──────────────────────────────────────────────────────────────

class ResumeAgentSettings(BaseSettings):
    provider: Literal["anthropic", "openai", "ollama", "gemini", "nvidia"] = "ollama"
    model: ModelConfig = Field(default_factory=ModelConfig)
    scraping: ScrapingConfig = Field(default_factory=ScrapingConfig)
    latex: LatexConfig = Field(default_factory=LatexConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    retries: RetriesConfig = Field(default_factory=RetriesConfig)

    # Passed via env or ~/.resume_generator/.env
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: Optional[str] = Field(default=None, alias="GOOGLE_API_KEY")
    nvidia_api_key: Optional[str] = Field(default=None, alias="NVIDIA_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    nvidia_base_url: str = Field(default="", alias="NVIDIA_BASE_URL")

    model_config = SettingsConfigDict(
        env_prefix="RESUME_GENERATOR_",
        env_nested_delimiter="__",
        # Load from project .env first, then from the user-level secrets file.
        # Later entries in the list take lower priority (first match wins).
        env_file=[".env", str(SECRETS_FILE)],
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    @classmethod
    def load(cls) -> "ResumeAgentSettings":
        """Load from ~/.resume_generator/config.yaml, overlaid with env vars."""
        migrate_config_dir()
        file_data: dict = {}
        if CONFIG_FILE.exists():
            raw = CONFIG_FILE.read_text(encoding="utf-8")
            file_data = yaml.safe_load(raw) or {}
        return cls.model_validate(file_data)

    def save(self) -> None:
        """Persist current settings to ~/.resume_generator/config.yaml."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Never write secrets into the YAML — they live in SECRETS_FILE
        data = self.model_dump(
            exclude={"anthropic_api_key", "openai_api_key", "gemini_api_key", "nvidia_api_key"},
        )
        CONFIG_FILE.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")

    @property
    def output_base_dir(self) -> Path:
        return Path(self.output.base_dir)

    def is_configured(self) -> bool:
        """Return True if a config file exists and the provider key (if needed) is present."""
        if not CONFIG_FILE.exists():
            return False
        if self.provider in ("anthropic", "openai", "gemini", "nvidia"):
            return bool(
                self.anthropic_api_key
                or self.openai_api_key
                or self.gemini_api_key
                or self.nvidia_api_key
            )
        return True   # ollama needs no key
