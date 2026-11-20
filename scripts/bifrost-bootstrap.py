"""Seed the local Bifrost gateway: one OpenAI-compatible provider and one virtual key with a budget and rate limit (D4).

Reads config/bifrost.toml + config/models.toml. Secrets come from the environment (or .env) and are never printed:
  BIFROST_URL, BIFROST_SETUP_TOKEN, PROVIDER_BASE_URL, PROVIDER_API_KEY.
Writes BIFROST_VIRTUAL_KEY=<value> to --out (mode 0600; default .env.bifrost, ignored by git).
Running it again reuses the provider and the key by name.

Usage: uv run scripts/bifrost-bootstrap.py [--out .env.bifrost]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

from terkini.gateway import load_gateway_config, load_env_file

REPO = Path(__file__).resolve().parent.parent


def need(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"bootstrap: {name} is not set (see .env.example)")
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(REPO / ".env.bifrost"))
    args = ap.parse_args()

    load_env_file(REPO / ".env")
    cfg = load_gateway_config()
    base = need("BIFROST_URL").rstrip("/")
    headers = {"x-bifrost-setup-token": need("BIFROST_SETUP_TOKEN")}
    upstream, upstream_key = need("PROVIDER_BASE_URL"), need("PROVIDER_API_KEY")
    models = cfg.all_upstream_models()
    http = httpx.Client(base_url=base, headers=headers, timeout=30)

    started = time.monotonic()
    while True:
        try:
            if http.get("/health").status_code == 200:
                break
        except httpx.TransportError:
            pass
        if time.monotonic() - started > cfg.health_timeout_seconds:
            sys.exit(f"bootstrap: gateway did not report healthy within {cfg.health_timeout_seconds} s")
        time.sleep(2)
    print(f"bootstrap: gateway healthy after {time.monotonic() - started:.0f} s")

    prov = cfg.provider_name
    if http.get(f"/api/providers/{prov}").status_code != 200:
        r = http.post("/api/providers", json={
            "provider": prov,
            "network_config": {"base_url": upstream, "allow_private_network": cfg.allow_private_network,
                               "extra_headers": cfg.extra_headers},
        })
        if r.status_code != 200:
            sys.exit(f"bootstrap: provider create failed: HTTP {r.status_code}")
        # v2.5.1 ignores keys on provider create; keys have their own endpoint.
        r = http.post(f"/api/providers/{prov}/keys", json={
            "name": "upstream", "value": upstream_key, "models": models, "weight": 1,
        })
        if r.status_code != 200:
            sys.exit(f"bootstrap: provider key create failed: HTTP {r.status_code}")
        print(f"bootstrap: provider {prov} created with {len(models)} models")
    else:
        print(f"bootstrap: provider {prov} already present")

    vk = cfg.virtual_key
    existing = http.get("/api/governance/virtual-keys")
    found = {k["name"]: k.get("value") for k in (existing.json().get("virtual_keys") or [])} if existing.status_code == 200 else {}
    value = found.get(vk["name"])
    if value:
        print(f"bootstrap: virtual key {vk['name']} reused")
    else:
        r = http.post("/api/governance/virtual-keys", json={
            "name": vk["name"],
            "budgets": vk.get("budgets", []),
            "rate_limit": vk.get("rate_limit", {}),
            # v2.5.1 blocks every model when allowed_models is ['*']; list them explicitly.
            "provider_configs": [{"provider": prov, "allowed_models": models, "key_ids": ["*"], "weight": 1}],
        })
        value = (r.json().get("virtual_key") or {}).get("value") if r.status_code == 200 else None
        if not value:
            sys.exit(f"bootstrap: virtual key create failed: HTTP {r.status_code}")
        print(f"bootstrap: virtual key {vk['name']} created")

    out = Path(args.out)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"BIFROST_VIRTUAL_KEY={value}\n")
    print(f"bootstrap: virtual key written to {out.name} (value not shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
