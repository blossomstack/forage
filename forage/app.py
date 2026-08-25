"""HTTP surface: one useful route, plus a health check that actually extracts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import Settings
from .extract import Unextractable, extract
from .mcp_server import build_server, transport_security
from .net import BlockedURL, Fetched, TooLarge, fetch
from .search import search_url

SAMPLE = b"<html><body><article><p>forage is running.</p></article></body></html>"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    app.state.settings = settings
    app.state.client = httpx.Client(
        timeout=settings.timeout_seconds,
        headers={"User-Agent": settings.user_agent, "Accept-Encoding": "gzip, deflate"},
    )
    try:
        # Mounting a Starlette sub-app does NOT run its lifespan, and the MCP
        # session manager needs one: without this the /mcp routes exist and
        # every request fails inside the transport. It has to be entered here,
        # in the parent's lifespan.
        async with mcp_server.session_manager.run():
            yield
    finally:
        app.state.client.close()


def _client() -> httpx.Client:
    return app.state.client


mcp_server = build_server(_client, Settings.from_env())

app = FastAPI(
    title="forage",
    summary="Fetch a URL, get clean Markdown.",
    lifespan=lifespan,
)

# streamable_http_path="/" because this app is mounted at /mcp; leaving the
# default would put the endpoint at /mcp/mcp. The served URL is therefore
# "/mcp/" — Starlette redirects "/mcp" to it with a 307, which preserves the
# POST method and body, but prefer the trailing slash in client config.
app.mount(
    "/mcp",
    mcp_server.streamable_http_app(
        streamable_http_path="/",
        transport_security=transport_security(),
    ),
)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_client(request: Request) -> httpx.Client:
    return request.app.state.client


def _fetch_or_raise(url: str, client: httpx.Client, settings: Settings) -> Fetched:
    try:
        return fetch(url, client, settings)
    except BlockedURL as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail=f"upstream timeout: {exc}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}") from exc


@app.get("/extract", response_class=PlainTextResponse)
def extract_route(
    url: Annotated[str, Query(description="Absolute http(s) URL to fetch.")],
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[httpx.Client, Depends(get_client)],
    format: Annotated[Literal["markdown", "json"], Query()] = "markdown",
    links: Annotated[bool, Query(description="Keep inline links in the Markdown.")] = True,
):
    fetched = _fetch_or_raise(url, client, settings)

    # Pass the upstream status through rather than collapsing everything to 500.
    # "the page is gone" and "the extractor is broken" are different problems and
    # a caller cannot act on them the same way.
    if fetched.status >= 400:
        raise HTTPException(
            status_code=fetched.status,
            detail=f"upstream returned {fetched.status} for {fetched.url}",
        )

    try:
        result = extract(
            fetched.body,
            content_type=fetched.content_type,
            url=fetched.url,
            encoding=fetched.encoding,
            include_links=links,
        )
    except Unextractable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if format == "json":
        return JSONResponse(
            {
                "url": fetched.url,
                "kind": result.kind,
                "metadata": result.metadata,
                "markdown": result.markdown,
                "chars": len(result.markdown),
            }
        )

    return PlainTextResponse(result.markdown, media_type="text/markdown; charset=utf-8")


@app.get("/health")
def health():
    """Prove the extractor works, not merely that the process is alive.

    A liveness check that only returns {"ok": true} would stay green with a
    broken trafilatura install, which is the failure this service actually has.
    """
    result = extract(SAMPLE, content_type="text/html", url="https://example.invalid/")
    if "forage is running" not in result.markdown:
        raise HTTPException(status_code=503, detail="extractor produced no content")
    # `search` reports whether the optional SearXNG backend is wired up. The MCP
    # tool is only registered when it is, so this is the one place to see that a
    # deployment meant to have search does not.
    return {"ok": True, "search": search_url() is not None}
