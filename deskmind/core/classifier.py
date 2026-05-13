"""LLM classifier abstraction — supports Claude, OpenAI, and local models."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from deskmind.models.schemas import DeskMindConfig, FileInfo, LLMConfig, OrganizePlan

SYSTEM_PROMPT = """You are DeskMind, an AI desktop file organization assistant.
Your job is to analyze a list of desktop files and create an organization plan.

Each file can be handled in TWO ways:

1. **Folder mode** (action: "move") — Move the file into a named folder.
   Use for general categorization (e.g. "Documents", "Images", "Projects").

2. **Zone mode** (action: "arrange") — The file will be grouped into a
   named zone folder on the desktop. The zone name describes its visual
   area (e.g. "top-right", "games-area", "work-files").
   The system will create folders with the zone name and move files there.

Decide per file which mode fits best based on the user's rule.

Rules for decision-making:
- Group related files together (by type, project, or purpose)
- Zone names can be descriptive: "work-files", "games-corner", "to-review"
- Never suggest deleting files unless the user explicitly asks
- "archive" means files that haven't been modified in a long time
- Be practical — don't create too many folders or zones

You must respond in this exact JSON format:
{
  "summary": "Brief summary of what the plan does",
  "created_folders": ["FolderName1", "FolderName2"],
  "actions": [
    {
      "file": "filename.pdf",
      "action": "move",
      "target_folder": "Documents",
      "new_name": null,
      "reason": "PDF document filed away"
    },
    {
      "file": "game.exe",
      "action": "arrange",
      "zone": "games-corner",
      "reason": "Game shortcut, grouped in games zone"
    }
  ]
}

Action must be one of: "move", "arrange", "copy", "archive".
- "move" requires "target_folder"
- "arrange" requires "zone" (any descriptive name like area or theme)
- If new_name is null, keep the original name.
- Include EVERY file in the actions list — don't skip any.
"""


def _build_user_prompt(
    files: list[FileInfo],
    rule_text: str,
) -> str:
    """Build the prompt sent to the LLM with file list and user rule."""
    lines = [f"## User's organization rule\n{rule_text}\n", "## Desktop files\n"]
    lines.append(f"{'Name':<40} {'Size':<10} {'Modified':<20} {'Type'}")
    lines.append("-" * 90)
    for f in files:
        modified = f.modified_at.strftime("%Y-%m-%d %H:%M")
        size_str = _format_size(f.size_bytes)
        ftype = "DIR" if f.is_directory else f.extension or "(no ext)"
        lines.append(f"{f.name:<40} {size_str:<10} {modified:<20} {ftype}")
    return "\n".join(lines)


def _format_size(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    elif bytes_ < 1024**2:
        return f"{bytes_ / 1024:.1f} KB"
    else:
        return f"{bytes_ / 1024**2:.1f} MB"


def _parse_llm_response(
    response_text: str,
    file_map: dict[str, FileInfo],
) -> OrganizePlan:
    """Parse LLM JSON response into an OrganizePlan."""
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    data = json.loads(text)

    from deskmind.models.schemas import ActionType, OrganizeAction

    actions = []
    for ad in data.get("actions", []):
        file_name = ad["file"]
        file_info = file_map.get(file_name)
        if file_info is None:
            # Try matching by full path or basename
            for name, info in file_map.items():
                if name == file_name or info.name == file_name:
                    file_info = info
                    break
        if file_info is None:
            continue  # skip files not found in the scan

        actions.append(OrganizeAction(
            file_path=file_info.path,
            action=ActionType(ad.get("action", "move")),
            target_folder=ad.get("target_folder"),
            zone=ad.get("zone"),
            new_name=ad.get("new_name"),
            reason=ad.get("reason", ""),
        ))

    return OrganizePlan(
        actions=actions,
        summary=data.get("summary", ""),
        created_folders=data.get("created_folders", []),
    )


class BaseClassifier(ABC):
    """Abstract base for all LLM classifiers."""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    def classify(
        self,
        files: list[FileInfo],
        rule_text: str,
    ) -> OrganizePlan:
        """Classify files and return an organization plan."""
        ...

    @classmethod
    def create(cls, config: LLMConfig) -> BaseClassifier:
        """Factory method to create the right classifier."""
        provider = config.provider
        if provider == "claude":
            from .classifier_claude import ClaudeClassifier
            return ClaudeClassifier(config)
        elif provider in ("openai", "deepseek"):
            from .classifier_openai import OpenAIClassifier
            base_url = config.api_base
            if provider == "deepseek" and not base_url:
                base_url = "https://api.deepseek.com/v1"
            deepseek_config = LLMConfig(
                provider=provider,
                api_key=config.api_key,
                api_base=base_url or "",
                model=config.model or ("deepseek-chat" if provider == "deepseek" else "gpt-4o"),
            )
            return OpenAIClassifier(deepseek_config)
        elif provider == "local":
            from .classifier_openai import OpenAIClassifier
            local_config = LLMConfig(
                provider="local",
                api_key=config.api_key,
                api_base=config.api_base or "http://localhost:11434/v1",
                model=config.model or "qwen2.5:7b",
            )
            return OpenAIClassifier(local_config)
        raise ValueError(f"Unknown LLM provider: {provider}")

    @staticmethod
    def make_plan(
        files: list[FileInfo],
        rule_text: str,
        llm_config: LLMConfig,
    ) -> OrganizePlan:
        """Convenience: create classifier, classify, return plan."""
        classifier = BaseClassifier.create(llm_config)
        return classifier.classify(files, rule_text)
