"""Azure OpenAI provider (REST, no SDK lock-in).

Authentication, in order of preference:
1. Microsoft Entra ID token via AKS Workload Identity (DefaultAzureCredential)
   — no secrets in the cluster; RBAC role "Cognitive Services OpenAI User".
2. API key — local development only.
"""

from __future__ import annotations

import time

import httpx

from .base import Completion, ProviderError

_SCOPE = "https://cognitiveservices.azure.com/.default"


class _EntraToken:
    def __init__(self) -> None:
        self._token: str | None = None
        self._expires = 0.0
        self._cred = None

    def get(self) -> str:
        if self._token and time.time() < self._expires - 300:
            return self._token
        if self._cred is None:
            from azure.identity import DefaultAzureCredential  # lazy: optional dependency

            self._cred = DefaultAzureCredential()
        tok = self._cred.get_token(_SCOPE)
        self._token, self._expires = tok.token, float(tok.expires_on)
        return self._token


class AzureOpenAIProvider:
    name = "azure_openai"

    def __init__(self, endpoint: str, api_version: str, api_key: str = "", timeout: float = 30):
        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT is not configured")
        self.endpoint = endpoint.rstrip("/")
        self.api_version = api_version
        self.api_key = api_key
        self._entra = None if api_key else _EntraToken()
        self._client = httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"api-key": self.api_key}
        assert self._entra is not None
        return {"Authorization": f"Bearer {self._entra.get()}"}

    async def chat(self, deployment, messages, *, temperature, max_tokens, response_format):
        url = (
            f"{self.endpoint}/openai/deployments/{deployment}/chat/completions"
            f"?api-version={self.api_version}"
        )
        body: dict = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if response_format:
            body["response_format"] = response_format
        try:
            r = await self._client.post(url, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProviderError(f"azure_openai transport error: {exc}") from exc

        if r.status_code == 429 or r.status_code >= 500:
            raise ProviderError(f"azure_openai {r.status_code}", status=r.status_code)
        if r.status_code == 400 and "content_filter" in r.text:
            raise ProviderError("blocked by Azure AI Content Safety", 422, retryable=False)
        if r.status_code >= 400:
            raise ProviderError(f"azure_openai {r.status_code}: {r.text[:200]}", r.status_code, False)

        data = r.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return Completion(
            content=choice["message"].get("content") or "",
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason", "stop"),
        )
