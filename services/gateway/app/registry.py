"""Model registry: loads models.yaml and answers routing/authorisation questions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

import yaml


class Classification(IntEnum):
    public = 0
    internal = 1
    confidential = 2
    strictly_confidential = 3

    @classmethod
    def parse(cls, value: str) -> Classification:
        try:
            return cls[value]
        except KeyError as exc:
            raise ValueError(f"unknown data classification '{value}'") from exc


@dataclass(frozen=True)
class ModelSpec:
    alias: str
    description: str
    provider: str
    deployment: str
    region: str
    max_classification: Classification
    context_window: int
    cost_in: float
    cost_out: float
    fallback: str | None
    status: str
    owner: str

    def cost_eur(self, prompt_tokens: int, completion_tokens: int) -> float:
        return round(
            prompt_tokens / 1000 * self.cost_in + completion_tokens / 1000 * self.cost_out, 6
        )


@dataclass(frozen=True)
class Tenant:
    id: str
    api_key: str | None
    allowed_models: frozenset[str]
    requests_per_minute: int
    monthly_budget_eur: float


class RoutingError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Registry:
    def __init__(self, models: dict[str, ModelSpec], tenants: dict[str, Tenant]):
        self.models = models
        self.tenants = tenants
        self._validate()

    @classmethod
    def load(cls, path: str | Path) -> Registry:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        models = {
            m["alias"]: ModelSpec(
                alias=m["alias"],
                description=m.get("description", ""),
                provider=m["provider"],
                deployment=m["deployment"],
                region=m.get("region", ""),
                max_classification=Classification.parse(m["max_classification"]),
                context_window=int(m["context_window"]),
                cost_in=float(m["cost_per_1k_input_tokens_eur"]),
                cost_out=float(m["cost_per_1k_output_tokens_eur"]),
                fallback=m.get("fallback"),
                status=m.get("status", "active"),
                owner=m.get("owner", ""),
            )
            for m in raw["models"]
        }
        tenants = {
            t["id"]: Tenant(
                id=t["id"],
                api_key=os.getenv(t["api_key_env"]) if t.get("api_key_env") else None,
                allowed_models=frozenset(t["allowed_models"]),
                requests_per_minute=int(t["requests_per_minute"]),
                monthly_budget_eur=float(t["monthly_budget_eur"]),
            )
            for t in raw.get("tenants", [])
        }
        return cls(models, tenants)

    def _validate(self) -> None:
        for spec in self.models.values():
            if spec.fallback and spec.fallback not in self.models:
                raise ValueError(f"{spec.alias}: fallback '{spec.fallback}' not in registry")
        for t in self.tenants.values():
            unknown = t.allowed_models - self.models.keys()
            if unknown:
                raise ValueError(f"tenant {t.id}: unknown models {sorted(unknown)}")
        # fallback chains must terminate
        for alias in self.models:
            seen: set[str] = set()
            cur: str | None = alias
            while cur:
                if cur in seen:
                    raise ValueError(f"fallback cycle involving '{alias}'")
                seen.add(cur)
                cur = self.models[cur].fallback

    def tenant_for_key(self, api_key: str | None) -> Tenant | None:
        if not api_key:
            return None
        for t in self.tenants.values():
            if t.api_key and t.api_key == api_key:
                return t
        return None

    def resolve(
        self, tenant: Tenant, alias: str, classification: Classification
    ) -> list[ModelSpec]:
        """Return the ordered candidate chain (primary + permitted fallbacks).

        Fallbacks are only included if they are also allowed for the tenant and
        cleared for the data classification — a fallback must never downgrade
        data protection.
        """
        spec = self.models.get(alias)
        if spec is None:
            raise RoutingError(404, "model_not_found", f"model '{alias}' is not registered")
        if spec.status == "blocked":
            raise RoutingError(410, "model_blocked", f"model '{alias}' is retired/blocked")
        if alias not in tenant.allowed_models:
            raise RoutingError(
                403, "model_not_allowed", f"tenant '{tenant.id}' may not use '{alias}'"
            )
        if spec.max_classification < classification:
            raise RoutingError(
                403,
                "classification_exceeded",
                f"'{alias}' is cleared up to {spec.max_classification.name}, "
                f"request is {classification.name}",
            )
        chain = [spec]
        cur = spec.fallback
        while cur:
            fb = self.models[cur]
            if (
                fb.status == "active"
                and fb.alias in tenant.allowed_models
                and fb.max_classification >= classification
            ):
                chain.append(fb)
            cur = fb.fallback
        return chain
