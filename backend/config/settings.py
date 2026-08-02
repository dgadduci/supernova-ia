import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")


def _str_env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer (got {raw!r})") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    truthy = {"1", "true", "yes", "on"}
    falsy = {"0", "false", "no", "off"}
    lowered = raw.lower()
    if lowered in truthy:
        return True
    if lowered in falsy:
        return False
    raise ValueError(f"{name} must be a boolean (got {raw!r})")


@dataclass(frozen=True)
class Settings:
    llm_url: str
    llm_model: str
    llm_timeout: int
    llm_keep_alive: str
    llm_num_ctx: int
    llm_num_predict: int
    llm_log_content: bool
    llm_log_max_chars: int


def load_settings() -> Settings:
    return Settings(
        llm_url=_str_env("LLM_URL", "http://localhost:11434/api/generate"),
        llm_model=_str_env("LLM_MODEL", "qwen-27b-coding:latest"),
        llm_timeout=_int_env("LLM_TIMEOUT", 180),
        llm_keep_alive=_str_env("LLM_KEEP_ALIVE", "2h"),
        llm_num_ctx=_int_env("LLM_NUM_CTX", 8192),
        llm_num_predict=_int_env("LLM_NUM_PREDICT", 1500),
        llm_log_content=_bool_env("LLM_LOG_CONTENT", False),
        llm_log_max_chars=_int_env("LLM_LOG_MAX_CHARS", 1000),
    )


__all__ = ["Settings", "load_settings"]
