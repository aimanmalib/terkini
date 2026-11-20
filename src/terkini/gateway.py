"""Model calls through the Bifrost gateway (D4). Every LLM request in Terkini goes through `Gateway.chat`.

Config: config/bifrost.toml (provider slot, virtual key limits, timeouts) + config/models.toml (model ids, fallbacks, roles).
Secrets: BIFROST_URL and BIFROST_VIRTUAL_KEY from the environment. The virtual key is sent as `x-bf-vk` and never logged.
"""

from __future__ import annotations

import os
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from pydantic import BaseModel, model_validator

from terkini.packs import REPO_ROOT


class GatewayNotConfigured(RuntimeError):
    pass


class GatewayError(RuntimeError):
    pass


class ModelsConfig(BaseModel):
    models: list[str]
    fallbacks: list[str]
    extractor: str
    judge: str
    vendors: dict[str, str]

    @model_validator(mode="after")
    def _check(self) -> "ModelsConfig":
        if len(self.models) < 3:
            raise ValueError("models.toml: list at least 3 models (D4)")
        if len(self.fallbacks) < 2:
            raise ValueError("models.toml: list at least 2 fallbacks (D4)")
        named = set(self.models) | set(self.fallbacks) | {self.extractor, self.judge}
        if any(m.strip().lower() == "fallback" for m in named):
            raise ValueError("models.toml: use exact model ids, not a router alias")
        missing = sorted(m for m in self.models if m not in self.vendors)
        if missing:
            raise ValueError(f"models.toml: no vendor label for {missing}")
        return self


@dataclass(frozen=True)
class GatewayConfig:
    provider_name: str
    allow_private_network: bool
    request_timeout_seconds: int
    extra_headers: dict[str, str]
    virtual_key: dict
    timeout_seconds: float
    health_timeout_seconds: float
    models: ModelsConfig

    def all_upstream_models(self) -> list[str]:
        """Every upstream model id the virtual key must allow, in a stable order."""
        seen: list[str] = []
        for m in [*self.models.models, *self.models.fallbacks, self.models.extractor, self.models.judge]:
            if m not in seen:
                seen.append(m)
        return seen

    def ref(self, model: str) -> str:
        """Bifrost model reference: `<provider>/<upstream id>`."""
        return f"{self.provider_name}/{model}"


def load_gateway_config(root: Path = REPO_ROOT) -> GatewayConfig:
    b = tomllib.loads((root / "config" / "bifrost.toml").read_text(encoding="utf-8"))
    m = tomllib.loads((root / "config" / "models.toml").read_text(encoding="utf-8"))
    return GatewayConfig(
        provider_name=b["provider"]["name"],
        allow_private_network=bool(b["provider"].get("allow_private_network", False)),
        request_timeout_seconds=int(b["provider"]["request_timeout_seconds"]),
        extra_headers={str(k): str(v) for k, v in b["provider"].get("extra_headers", {}).items()},
        virtual_key=b["virtual_key"],
        timeout_seconds=float(b["client"]["timeout_seconds"]),
        health_timeout_seconds=float(b["client"]["health_timeout_seconds"]),
        models=ModelsConfig(**m),
    )


def load_env_file(path: Path) -> None:
    """Fill missing environment variables from a KEY=VALUE file (no shell expansion). Existing values win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str  # model that actually answered, as reported by the gateway
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    raw: dict = field(repr=False)


class Gateway:
    def __init__(self, cfg: GatewayConfig | None = None, client: httpx.Client | None = None,
                 url: str | None = None, virtual_key: str | None = None):
        self.cfg = cfg or load_gateway_config()
        base = url if url is not None else os.environ.get("BIFROST_URL", "")
        key = virtual_key if virtual_key is not None else os.environ.get("BIFROST_VIRTUAL_KEY", "")
        if not base or not key:
            raise GatewayNotConfigured("set BIFROST_URL and BIFROST_VIRTUAL_KEY (run scripts/bifrost-bootstrap.py)")
        self._base = base.rstrip("/")
        self._headers = {"x-bf-vk": key}
        self._client = client or httpx.Client(timeout=self.cfg.timeout_seconds)

    def chat(self, model: str, messages: list[dict], *, fallbacks: list[str] | None = None,
             json_mode: bool = False, temperature: float | None = 0.0) -> ChatResult:
        body: dict = {"model": self.cfg.ref(model), "messages": messages, "stream": False}
        if fallbacks:
            body["fallbacks"] = [self.cfg.ref(f) for f in fallbacks if f != model]
        if temperature is not None:
            body["temperature"] = temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        t0 = time.monotonic()
        try:
            r = self._client.post(f"{self._base}/v1/chat/completions", json=body, headers=self._headers)
        except httpx.HTTPError as e:
            # A timeout or dropped connection fails this one call; the checker records it and goes on.
            raise GatewayError(f"gateway request failed: {type(e).__name__}") from None
        took = time.monotonic() - t0
        if r.status_code != 200:
            raise GatewayError(f"gateway HTTP {r.status_code}: {_error_message(r)}")
        return parse_chat(r.json(), took)

    def list_models(self) -> list[str]:
        r = self._client.get(f"{self._base}/v1/models", headers=self._headers)
        if r.status_code != 200:
            raise GatewayError(f"gateway HTTP {r.status_code}: {_error_message(r)}")
        return [m["id"] for m in r.json().get("data", [])]


def parse_chat(data: dict, seconds: float = 0.0) -> ChatResult:
    choices = data.get("choices") or []
    if not choices:
        raise GatewayError("gateway answer has no choices")
    text = (choices[0].get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    return ChatResult(
        text=text,
        model=str(data.get("model", "")),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        seconds=seconds,
        raw=data,
    )


def _error_message(r: httpx.Response) -> str:
    try:
        err = r.json().get("error")
        if isinstance(err, dict):
            return str(err.get("message", ""))[:300]
        return str(err)[:300]
    except ValueError:
        return r.text[:300]
