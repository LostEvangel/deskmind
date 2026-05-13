from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class ActionType(str, Enum):
    move = "move"
    copy = "copy"
    delete = "delete"
    archive = "archive"
    arrange = "arrange"  # keep on desktop, reposition to a zone


class FileCategory(str, Enum):
    document = "document"
    image = "image"
    video = "video"
    audio = "audio"
    archive = "archive"
    code = "code"
    shortcut = "shortcut"
    folder = "folder"
    other = "other"


@dataclass
class FileInfo:
    """Metadata of a single file on the desktop."""
    path: Path
    name: str
    extension: str
    size_bytes: int
    created_at: datetime
    modified_at: datetime
    is_directory: bool
    category: Optional[FileCategory] = None
    llm_classification: Optional[str] = None

    @property
    def relative_path(self) -> str:
        return str(self.path)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["path"] = str(self.path)
        d["created_at"] = self.created_at.isoformat()
        d["modified_at"] = self.modified_at.isoformat()
        return d


@dataclass
class OrganizeAction:
    """A single action to perform on a file."""
    file_path: Path
    action: ActionType = ActionType.move
    target_folder: Optional[str] = None
    zone: Optional[str] = None
    new_name: Optional[str] = None
    reason: str = ""
    skip: bool = False

    def to_dict(self) -> dict:
        d: dict = {
            "file": str(self.file_path),
            "action": self.action.value,
            "new_name": self.new_name,
            "reason": self.reason,
            "skip": self.skip,
        }
        if self.target_folder:
            d["target_folder"] = self.target_folder
        if self.zone:
            d["zone"] = self.zone
        return d


@dataclass
class OrganizePlan:
    """Full organization plan returned by the LLM."""
    actions: list[OrganizeAction]
    summary: str = ""
    created_folders: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "created_folders": self.created_folders,
            "actions": [a.to_dict() for a in self.actions],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class Rule:
    """A structured or natural-language rule for organizing files."""
    name: str = ""
    folder: str = ""
    description: str = ""
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    age: Optional[str] = None
    action: ActionType = ActionType.move
    natural_language: str = ""


LLMProvider = str  # "claude" | "openai" | "deepseek" | "local"


@dataclass
class LLMConfig:
    """Configuration for an LLM provider."""
    provider: LLMProvider = "claude"
    api_key: str = ""
    api_base: str = ""
    model: str = ""

    @classmethod
    def default_for_provider(cls, provider: LLMProvider) -> "LLMConfig":
        defaults = {
            "claude": LLMConfig(
                provider="claude",
                model="claude-sonnet-4-20250514",
            ),
            "openai": LLMConfig(
                provider="openai",
                model="gpt-4o",
            ),
            "deepseek": LLMConfig(
                provider="deepseek",
                api_base="https://api.deepseek.com/v1",
                model="deepseek-chat",
            ),
            "local": LLMConfig(
                provider="local",
                api_base="http://localhost:11434/v1",
                model="qwen2.5:7b",
            ),
        }
        return defaults.get(provider, defaults["claude"])


@dataclass
class DeskMindConfig:
    """Main configuration for DeskMind."""
    desktop_path: str = ""
    llm: LLMConfig = field(default_factory=LLMConfig)
    rules_path: str = ""
    trash_enabled: bool = True
    preview_required: bool = True
    exclude_extensions: list[str] = field(default_factory=lambda: [
        ".tmp", ".lnk", ".ini",
    ])
    exclude_names: list[str] = field(default_factory=lambda: [
        "desktop.ini",
    ])

    @property
    def resolved_desktop(self) -> Path:
        if self.desktop_path:
            return Path(self.desktop_path)
        return Path.home() / "Desktop"
