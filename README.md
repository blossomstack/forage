# forage

Fetch a URL, get clean Markdown. One small container, no browser.

```bash
docker run -p 8080:8080 ghcr.io/blossomstack/forage:latest

curl 'http://localhost:8080/extract?url=https://en.wikipedia.org/wiki/Foraging'
```

REST for scripts, [MCP](#mcp) at `/mcp/` for agents.

```
image: ~230 MB      memory: ~130 MB      typical page: 0.2–0.9s
```

## Why

Search APIs give you URLs and a ~160-character snippet. Something still has to turn
those URLs into text an LLM can read. The managed options that do both — Firecrawl,
Exa — bill per request; the self-hosted ones that bundle a browser cost about 4 GB of
disk and several seconds per page.

Most pages do not need a browser. forage is the part you actually need most of the
time: an HTTP fetch, [trafilatura](https://trafilatura.readthedocs.io) for main-content
extraction, and a PDF text path. When it is not enough, it fails loudly with a
`422` so a caller can escalate to a renderer, rather than silently returning a
navigation menu.

## API

### `GET /extract`

| Parameter | Default | Meaning |
|---|---|---|
| `url` | required | Absolute `http`/`https` URL |
| `format` | `markdown` | `markdown` returns `text/markdown`; `json` adds metadata |
| `links` | `true` | Keep inline links. `false` drops the URLs, keeps the anchor text |

```bash
curl 'http://localhost:8080/extract?url=https://example.com/post&format=json'
```

```json
{
  "url": "https://example.com/post",
  "kind": "html",
  "metadata": { "title": "…", "author": "…", "date": "…", "sitename": "…" },
  "markdown": "# …",
  "chars": 4213
}
```

Status codes are meant to be acted on:

| Code | Means |
|---|---|
| `200` | Markdown in the body |
| `403` | The URL is blocked — bad scheme, or it resolves to a non-public address |
| `413` | Body exceeded `FORAGE_MAX_BYTES` |
| `422` | Fetched fine, but nothing readable came out — **escalate to a renderer** |
| `4xx`/`5xx` | Passed through from upstream. A `404` here means the page is gone |
| `502`/`504` | The fetch itself failed or timed out |

Upstream status is passed through deliberately. The obvious implementation calls
`raise_for_status()` and turns every upstream problem into an opaque `500`, which
leaves a caller unable to tell "this page is gone, try the next result" from
"this service is broken, stop calling it".

### `GET /health`

Runs a real extraction and fails if no content comes out. A liveness check that
only proves the process is alive would stay green with a broken extractor
install, which is the failure mode this service actually has.

## MCP

The same two capabilities are also served over MCP (Streamable HTTP) at **`/mcp/`** —
mind the trailing slash; `/mcp` answers with a 307 to it.

```json
{ "mcpServers": { "forage": { "type": "http", "url": "http://localhost:8080/mcp/" } } }
```

| Tool | |
|---|---|
| `fetch(url, links=true)` | The page as Markdown |
| `search(query, limit=8)` | Ranked results — **only registered when `FORAGE_SEARCH_URL` is set** |

Two tools rather than one combined "search and read the top N". Eager fetching turns one
query into N page loads, and the ~150-character snippet is usually enough for the model to
pick the two results worth reading.

`search` proxies to a [SearXNG](https://docs.searxng.org) instance. Note that instance needs
`search.formats` to include `json`, or it answers `format=json` with a hard 403.

Tool failures carry their reason — "no readable content … it may need JavaScript to render"
is a different instruction to a model than "returned HTTP 404". This requires raising the
SDK's `ToolError`: any other exception is treated as a crash and the message is replaced
with a bare `Error executing tool fetch`, which tells a model nothing.

### Behind a reverse proxy

The MCP SDK enables DNS-rebinding protection by default and answers **421** for any `Host`
it does not recognise — which is every deployment behind a proxy, and it reads like a broken
route rather than a setting. List the proxy's hostname:

```
FORAGE_MCP_ALLOWED_HOSTS=forage.example.com,forage.example.com:443
```

`*` disables the check entirely. Prefer the allowlist: forage has no authentication, so
network placement is the only other control.

The default list covers `localhost` and `127.0.0.1`, with and without `:8080`. **Publishing
the container on a different host port breaks MCP** — `-p 9000:8080` makes the `Host` header
`localhost:9000`, which is not on that list, and every MCP call returns 421 while the REST
routes keep working perfectly. Add the port you publish on.

## Configuration

Everything has a working default; none of these are required.

| Variable | Default | |
|---|---|---|
| `FORAGE_PORT` | `8080` | |
| `FORAGE_HOST` | `0.0.0.0` | |
| `FORAGE_TIMEOUT_SECONDS` | `20` | Per-request upstream timeout |
| `FORAGE_MAX_BYTES` | `8388608` | Body cap, enforced while streaming |
| `FORAGE_MAX_REDIRECTS` | `5` | |
| `FORAGE_ALLOW_PRIVATE_ADDRESSES` | `false` | See below |
| `FORAGE_USER_AGENT` | a Chrome UA | |
| `FORAGE_SEARCH_URL` | unset | SearXNG base URL; enables the MCP `search` tool |
| `FORAGE_MCP_ALLOWED_HOSTS` | unset | Extra `Host` values the MCP transport accepts |

## The SSRF guard

The URL usually comes from a model, so forage refuses any URL that resolves to a
non-public address — private ranges, loopback, link-local (including
`169.254.169.254`, the cloud metadata endpoint), and reserved space. Non-`http(s)`
schemes are refused outright.

**The guard runs on every redirect hop**, not just the URL you passed. A public URL
that `302`s to the metadata endpoint is the entire attack, and it defeats any check
that only looks at the original URL. Redirects are followed by hand for this reason.

Set `FORAGE_ALLOW_PRIVATE_ADDRESSES=1` only when there is no private network worth
reaching from the container.

**Known limitation:** the check resolves DNS, then the request resolves it again.
A name that returns a public address to the first lookup and a private one to the
second would slip through. Closing that requires pinning the connection to the
validated IP; if you are exposing forage to untrusted callers on a sensitive
network, put egress filtering in front of it rather than relying on this alone.

## What it handles

| Input | Result |
|---|---|
| HTML article, docs page, README | Markdown, with tables and optional links |
| PDF | Extracted text layer (no OCR) |
| `text/*` | Passed through, whitespace tidied |
| Anything else | `422` |

Measured against a browser-based extractor (Jina Reader) on the same pages:

| Page | forage | Jina |
|---|---|---|
| MDN reference | 5.3k chars | 6.3k |
| React docs (SPA) | 13.6k | 17.0k |
| Hacker News thread | 1.7k | 1.2k |
| arXiv PDF | 39.5k | — |
| JS-hydrated API reference | 5.8k, **missing request params** | 31.6k |
| Cloudflare-protected page | `502` | 195 chars (an interstitial) |

The honest summary: static extraction matches a headless browser on most pages and
loses badly on JS-hydrated documentation. Neither approach beats bot protection —
one just fails more clearly than the other.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

## License

Apache-2.0 OR MIT, at your option.
