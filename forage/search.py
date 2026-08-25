"""Optional SearXNG proxy, used only by the MCP `search` tool.

forage does not search. When FORAGE_SEARCH_URL points at a SearXNG instance it
will relay a query to it, so an agent gets find-then-read from one endpoint
instead of two.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


class SearchUnavailable(Exception):
    """No search backend is configured, or it failed."""


@dataclass(slots=True, frozen=True)
class Result:
    title: str
    url: str
    snippet: str
    engines: list[str]


def search_url() -> str | None:
    raw = os.environ.get("FORAGE_SEARCH_URL", "").strip()
    return raw.rstrip("/") or None


def search(query: str, client: httpx.Client, *, limit: int = 8) -> list[Result]:
    base = search_url()
    if base is None:
        raise SearchUnavailable("FORAGE_SEARCH_URL is not set")

    try:
        response = client.get(
            f"{base}/search",
            params={"q": query, "format": "json"},
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise SearchUnavailable(f"search backend error: {exc}") from exc
    except ValueError as exc:
        # SearXNG ships `formats: [html]` and answers format=json with a 403;
        # some deployments return an HTML error page with a 200 instead. Either
        # way the caller needs to hear "search is misconfigured", not a parse
        # traceback.
        raise SearchUnavailable("search backend did not return JSON") from exc

    return [
        Result(
            title=item.get("title") or "",
            url=item.get("url") or "",
            snippet=item.get("content") or "",
            engines=list(item.get("engines") or []),
        )
        for item in payload.get("results", [])[:limit]
        if item.get("url")
    ]
