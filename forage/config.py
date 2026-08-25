"""Runtime configuration. Every knob is an env var; none are required."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in ("1", "true", "yes", "on")


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 forage/1"
)


@dataclass(slots=True, frozen=True)
class Settings:
    timeout_seconds: float = 20.0
    max_bytes: int = 8 * 1024 * 1024
    max_redirects: int = 5
    # Off by default: the URL is typically chosen by a model, and a service that
    # will fetch http://10.0.0.5/ on request is a proxy into whatever network it
    # runs on. Turn on only for a deployment with no private network worth
    # reaching, or for tests.
    allow_private_addresses: bool = False
    user_agent: str = DEFAULT_USER_AGENT

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            timeout_seconds=float(os.environ.get("FORAGE_TIMEOUT_SECONDS", 20.0)),
            max_bytes=_int("FORAGE_MAX_BYTES", 8 * 1024 * 1024),
            max_redirects=_int("FORAGE_MAX_REDIRECTS", 5),
            allow_private_addresses=_bool("FORAGE_ALLOW_PRIVATE_ADDRESSES", False),
            user_agent=os.environ.get("FORAGE_USER_AGENT", DEFAULT_USER_AGENT),
        )
