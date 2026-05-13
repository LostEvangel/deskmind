"""Claude API classifier implementation."""

from __future__ import annotations

import os

from anthropic import Anthropic

from deskmind.core.classifier import (
    BaseClassifier,
    _build_user_prompt,
    _parse_llm_response,
    SYSTEM_PROMPT,
)
from deskmind.models.schemas import FileInfo, LLMConfig, OrganizePlan


class ClaudeClassifier(BaseClassifier):
    """Classifier using Anthropic's Claude API."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        api_key = config.api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Set it via environment variable or in config."
            )
        self.client = Anthropic(api_key=api_key)

    def classify(
        self,
        files: list[FileInfo],
        rule_text: str,
    ) -> OrganizePlan:
        user_prompt = _build_user_prompt(files, rule_text)
        file_map = {f.name: f for f in files}

        response = self.client.messages.create(
            model=self.config.model or "claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        text = response.content[0].text
        return _parse_llm_response(text, file_map)
