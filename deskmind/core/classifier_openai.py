"""OpenAI-compatible API classifier (also used for local models like Ollama)."""

from __future__ import annotations

import os

from openai import OpenAI

from deskmind.core.classifier import (
    BaseClassifier,
    _build_user_prompt,
    _parse_llm_response,
    SYSTEM_PROMPT,
)
from deskmind.models.schemas import FileInfo, LLMConfig, OrganizePlan


class OpenAIClassifier(BaseClassifier):
    """Classifier for OpenAI API and compatible backends (Ollama, vLLM, etc.)."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        api_key = config.api_key or os.getenv("OPENAI_API_KEY", "sk-placeholder")
        client_kwargs = {"api_key": api_key}
        if config.api_base:
            client_kwargs["base_url"] = config.api_base
        self.client = OpenAI(**client_kwargs)

    def classify(
        self,
        files: list[FileInfo],
        rule_text: str,
    ) -> OrganizePlan:
        user_prompt = _build_user_prompt(files, rule_text)
        file_map = {f.name: f for f in files}

        response = self.client.chat.completions.create(
            model=self.config.model or "gpt-4o",
            max_tokens=4096,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        text = response.choices[0].message.content or ""
        return _parse_llm_response(text, file_map)
