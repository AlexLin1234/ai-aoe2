from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from openai import OpenAI
from .schemas import Plan


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


class StructuredAgentClient:
    def __init__(self, model: str, max_output_tokens: int):
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.client = OpenAI()

    def request(self, system: str, text: str, image_url: str | None) -> tuple[Plan, Usage]:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
        if image_url:
            content.append({"type": "input_image", "image_url": image_url})
        response = self.client.responses.parse(
            model=self.model,
            max_output_tokens=self.max_output_tokens,
            input=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            text_format=Plan,
        )
        if response.output_parsed is None:
            raise ValueError("strategist returned no validated plan")
        usage = getattr(response, "usage", None)
        return response.output_parsed, Usage(
            getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0)
        )
