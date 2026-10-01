"""Deterministic offline provider for local dev, CI and DR drills.

If the request asks for JSON (`response_format={"type":"json_object"}`) and the
system prompt carries a `MOCK_JSON:` hint, that JSON is returned — this lets
downstream services be tested end-to-end without any cloud dependency.
"""

from __future__ import annotations

import json

from .base import Completion, ProviderError


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class MockProvider:
    name = "mock"

    def __init__(self, fail_deployments: set[str] | None = None):
        self.fail_deployments = fail_deployments or set()

    async def chat(self, deployment, messages, *, temperature, max_tokens, response_format):
        if deployment in self.fail_deployments:
            raise ProviderError(f"mock outage on {deployment}", status=503)
        prompt = "\n".join(m.get("content", "") for m in messages)
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        if response_format and response_format.get("type") == "json_object":
            hint = next(
                (
                    m["content"].split("MOCK_JSON:", 1)[1].strip()
                    for m in messages
                    if m.get("role") == "system" and "MOCK_JSON:" in m.get("content", "")
                ),
                None,
            )
            content = hint or json.dumps({"echo": last_user[:200]})
        else:
            content = f"[mock:{deployment}] {last_user[:500]}"
        return Completion(
            content=content,
            prompt_tokens=_approx_tokens(prompt),
            completion_tokens=_approx_tokens(content),
        )
