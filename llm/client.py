"""Create and call the configured LLM provider.

A Provider is the company or service that runs the language model, such as
Doubao, DeepSeek, or OpenAI. Player Creation should not know which provider
receives the request; this module owns API keys, base URLs, model IDs, and the
small amount of provider-specific request handling.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI, OpenAIError


DEFAULT_PROVIDER = "doubao"
DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_ARK_MODEL = "doubao-seed-2-0-lite-260215"

# The original project schema remains unchanged and is still used for local
# validation. Only the request copy drops keywords outside the Structured
# Outputs subset used by the OpenAI-compatible endpoint.
API_SCHEMA_OMITTED_KEYWORDS = {
    "$schema",
    "$id",
    "title",
    "default",
    "uniqueItems",
    "minLength",
}


class LLMProviderError(Exception):
    """A user-facing provider configuration or request error."""


def _build_api_schema(local_schema: dict[str, Any]) -> dict[str, Any]:
    def prune(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: prune(item)
                for key, item in value.items()
                if key not in API_SCHEMA_OMITTED_KEYWORDS
            }
        if isinstance(value, list):
            return [prune(item) for item in value]
        return value

    return prune(copy.deepcopy(local_schema))


def _extract_refusal(response: Any) -> str | None:
    for output_item in getattr(response, "output", []) or []:
        for content_item in getattr(output_item, "content", []) or []:
            if getattr(content_item, "type", None) == "refusal":
                return getattr(content_item, "refusal", None) or "模型拒绝了请求。"
    return None


@dataclass(frozen=True)
class LLMProviderClient:
    """Provider-neutral handle used by Player Creation."""

    provider: str
    model: str
    _client: OpenAI = field(repr=False)

    def create_structured_output(
        self,
        *,
        system_prompt: str,
        user_message: str,
        schema: dict[str, Any],
        schema_name: str,
    ) -> str:
        """Call the configured provider and return strict structured text."""

        try:
            response = self._client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": _build_api_schema(schema),
                    }
                },
            )
        except OpenAIError as exc:
            raise LLMProviderError(
                f"Provider {self.provider} 请求失败（{exc.__class__.__name__}）：{exc}"
            ) from exc

        if getattr(response, "status", None) == "incomplete":
            details = getattr(response, "incomplete_details", None)
            reason = getattr(details, "reason", None) or "未知原因"
            raise LLMProviderError(
                f"Provider {self.provider} 返回了不完整响应：{reason}。"
            )

        refusal = _extract_refusal(response)
        if refusal:
            raise LLMProviderError(
                f"Provider {self.provider} 未生成 Player Creation 结果：{refusal}"
            )

        output_text = getattr(response, "output_text", None)
        if not output_text or not output_text.strip():
            raise LLMProviderError(
                f"Provider {self.provider} 没有返回有效的结构化输出。"
            )
        return output_text


def create_llm_client() -> LLMProviderClient:
    """Create the configured provider client without silently falling back."""

    provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    provider = provider or DEFAULT_PROVIDER

    if provider != "doubao":
        raise LLMProviderError(f"Provider {provider} 尚未实现。")

    api_key = os.getenv("ARK_API_KEY", "").strip()
    if not api_key:
        raise LLMProviderError(
            "未配置 ARK_API_KEY，请在项目根目录 .env 中填写火山方舟 API Key。"
        )

    base_url = os.getenv("ARK_BASE_URL", DEFAULT_ARK_BASE_URL).strip()
    base_url = base_url or DEFAULT_ARK_BASE_URL
    model = os.getenv("ARK_MODEL", DEFAULT_ARK_MODEL).strip()
    model = model or DEFAULT_ARK_MODEL

    return LLMProviderClient(
        provider=provider,
        model=model,
        _client=OpenAI(api_key=api_key, base_url=base_url),
    )
