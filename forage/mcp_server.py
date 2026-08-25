"""The MCP surface: the same two capabilities, spoken as tools.

Failures raise `ToolError`, never a bare exception. The SDK treats anything else
as a crash and replaces the message with "Error executing tool fetch" — so the
model cannot tell "needs JavaScript, try another result" from "blocked" from
"404", which is the entire point of distinguishing them.

Two tools, not one. A combined "search and read the top N" tool would turn one
query into N page fetches, and the snippet is often enough — the model should
decide which results are worth reading.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .config import Settings
from .extract import Unextractable, extract
from .net import BlockedURL, TooLarge, fetch
from .search import SearchUnavailable, search, search_url

FETCH_DESCRIPTION = """\
Fetch a web page or PDF and return its main content as Markdown.

Navigation, footers and cookie banners are removed. Returns an error when the
page needs JavaScript to render — treat that as "try a different result",
not as a transient failure worth retrying.
"""

SEARCH_DESCRIPTION = """\
Search the web and return ranked results: title, URL and a short snippet.

Snippets are roughly 150 characters — enough to judge relevance, not enough to
answer from. Call `fetch` on the results worth reading.
"""


def allowed_hosts() -> list[str]:
    """Hosts the MCP transport will answer for.

    The SDK enables DNS-rebinding protection by default and returns 421 for any
    Host it does not recognise, which is every deployment behind a reverse
    proxy. Rather than switch the protection off, the proxy's hostname goes on
    this list explicitly.
    """
    raw = os.environ.get("FORAGE_MCP_ALLOWED_HOSTS", "")
    extra = [host.strip() for host in raw.split(",") if host.strip()]
    return ["localhost", "127.0.0.1", "localhost:8080", "127.0.0.1:8080", *extra]


def transport_security() -> TransportSecuritySettings:
    hosts = allowed_hosts()
    if "*" in hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"http://{host}" for host in hosts]
        + [f"https://{host}" for host in hosts],
    )


def build_server(get_client: Callable[[], httpx.Client], settings: Settings) -> MCPServer:
    server = MCPServer(
        name="forage",
        title="forage",
        instructions=(
            "Read web pages as Markdown. Use `search` to find candidate URLs, then "
            "`fetch` on the few worth reading — do not fetch every result."
        ),
    )

    @server.tool(name="fetch", description=FETCH_DESCRIPTION)
    def fetch_tool(url: str, links: bool = True) -> str:
        try:
            fetched = fetch(url, get_client(), settings)
        except BlockedURL as exc:
            raise ToolError(f"refused to fetch {url}: {exc}") from exc
        except TooLarge as exc:
            raise ToolError(f"{url} is too large: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"could not fetch {url}: {exc}") from exc

        if fetched.status >= 400:
            raise ToolError(f"{url} returned HTTP {fetched.status}")

        try:
            result = extract(
                fetched.body,
                content_type=fetched.content_type,
                url=fetched.url,
                encoding=fetched.encoding,
                include_links=links,
            )
        except Unextractable as exc:
            raise ToolError(
                f"no readable content at {url} ({exc}) — it may need JavaScript to render"
            ) from exc

        return result.markdown

    # Registered only when a backend is configured, so an agent never sees a
    # tool that can only fail.
    if search_url() is not None:

        @server.tool(name="search", description=SEARCH_DESCRIPTION)
        def search_tool(query: str, limit: int = 8) -> list[dict[str, object]]:
            try:
                results = search(query, get_client(), limit=limit)
            except SearchUnavailable as exc:
                raise ToolError(str(exc)) from exc
            return [
                {
                    "title": item.title,
                    "url": item.url,
                    "snippet": item.snippet,
                    "engines": item.engines,
                }
                for item in results
            ]

    return server
