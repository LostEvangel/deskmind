"""Configuration management — load/save DeskMind settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import yaml

from deskmind.models.schemas import DeskMindConfig, LLMConfig


def _default_config_path() -> Path:
    return Path.home() / ".deskmind" / "config.yaml"


def _ensure_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def load_config(path: Optional[Path] = None) -> DeskMindConfig:
    """Load configuration from file, merging with environment variables."""
    config_path = path or _default_config_path()

    config = DeskMindConfig()

    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # LLM config
        llm_data = data.get("llm", {})
        config.llm = LLMConfig(
            provider=llm_data.get("provider", "claude"),
            api_key=llm_data.get("api_key", ""),
            api_base=llm_data.get("api_base", ""),
            model=llm_data.get("model", ""),
        )

        # General config
        config.desktop_path = data.get("desktop_path", "")
        config.rules_path = data.get("rules_path", "")
        config.trash_enabled = data.get("trash_enabled", True)
        config.preview_required = data.get("preview_required", True)

        if "exclude_extensions" in data:
            config.exclude_extensions = data["exclude_extensions"]
        if "exclude_names" in data:
            config.exclude_names = data["exclude_names"]

    # Environment variables override file config
    provider = config.llm.provider
    provider_env_map = {
        "claude": ("ANTHROPIC_API_KEY",),
        "openai": ("OPENAI_API_KEY",),
        "deepseek": ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"),
        "local": (),
    }
    for env_var in provider_env_map.get(provider, ()):
        env_val = os.getenv(env_var)
        if env_val:
            config.llm.api_key = env_val
            break

    return config


def save_config(config: DeskMindConfig, path: Optional[Path] = None) -> Path:
    """Save configuration to file."""
    config_path = path or _default_config_path()
    _ensure_dir(config_path)

    data = {
        "llm": {
            "provider": config.llm.provider,
            "api_key": config.llm.api_key or "",
            "api_base": config.llm.api_base or "",
            "model": config.llm.model or "",
        },
        "desktop_path": config.desktop_path,
        "rules_path": config.rules_path,
        "trash_enabled": config.trash_enabled,
        "preview_required": config.preview_required,
        "exclude_extensions": config.exclude_extensions,
        "exclude_names": config.exclude_names,
    }

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    return config_path


def get_default_rules_path() -> Path:
    """Get the default path for the rules YAML file."""
    return Path.home() / ".deskmind" / "rules.yaml"


def save_default_rules(path: Optional[Path] = None) -> Path:
    """Create a default rules.yaml with examples."""
    rules_path = path or get_default_rules_path()
    _ensure_dir(rules_path)

    example = {
        "rules": [
            {
                "name": "Images",
                "folder": "Images",
                "description": "All image files",
                "include": ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.svg", "*.webp"],
                "action": "move",
            },
            {
                "name": "Documents",
                "folder": "Documents",
                "description": "Office documents and PDFs",
                "include": ["*.pdf", "*.docx", "*.doc", "*.xlsx", "*.xls", "*.pptx", "*.txt", "*.md"],
                "action": "move",
            },
            {
                "name": "Archives",
                "folder": "Archives",
                "description": "Compressed files",
                "include": ["*.zip", "*.rar", "*.7z", "*.tar", "*.gz"],
                "action": "move",
            },
        ]
    }

    with open(rules_path, "w", encoding="utf-8") as f:
        yaml.dump(example, f, default_flow_style=False, allow_unicode=True)

    return rules_path
