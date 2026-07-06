"""Tiny .env reader/writer with no external dependencies.

The .env file lives at the repository root (one level above ``src/``).
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env() -> dict:
    """Load .env into os.environ and return it as a dict.

    Values already present in the real environment (e.g. GitHub Actions
    secrets) take precedence over the .env file, so the same code works
    locally and in CI.
    """
    data: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            data[key] = value
            os.environ.setdefault(key, value)
    # Overlay real environment (CI secrets win).
    for key in list(data) + [
        "FYERS_APP_ID", "FYERS_SECRET_KEY", "FYERS_REDIRECT_URI",
        "FYERS_FY_ID", "FYERS_PIN", "FYERS_TOTP_SECRET", "FYERS_ACCESS_TOKEN",
    ]:
        if os.environ.get(key):
            data[key] = os.environ[key]
    return data


def set_env_value(key: str, value: str) -> None:
    """Update or append a single KEY=value line in .env, preserving the rest."""
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    out, found = [], False
    for line in lines:
        if line.strip().startswith(f"{key}=") or line.strip().startswith(f"{key} ="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n")
    os.environ[key] = value
