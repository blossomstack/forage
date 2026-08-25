"""Turn a fetched body into Markdown."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import trafilatura

HTML_TYPES = {"text/html", "application/xhtml+xml", ""}
PDF_TYPES = {"application/pdf", "application/x-pdf"}


class Unextractable(Exception):
    """Nothing readable came out."""


@dataclass(slots=True)
class Extracted:
    markdown: str
    kind: str
    metadata: dict[str, str] = field(default_factory=dict)


def _decode(body: bytes, encoding: str | None) -> str:
    return body.decode(encoding or "utf-8", errors="replace")


def _tidy(text: str) -> str:
    # trafilatura leaves runs of blank lines where it drops nodes; they cost
    # tokens and carry nothing.
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _from_pdf(body: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(body))
    pages = (page.extract_text() or "" for page in reader.pages)
    return _tidy("\n\n".join(pages))


def _from_html(html: str, url: str, *, include_links: bool) -> tuple[str, dict[str, str]]:
    document = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=include_links,
        include_tables=True,
        include_formatting=True,
        with_metadata=False,
    )
    if not document:
        return "", {}

    metadata: dict[str, str] = {}
    meta = trafilatura.extract_metadata(html, default_url=url)
    if meta is not None:
        for key in ("title", "author", "date", "sitename", "description"):
            value = getattr(meta, key, None)
            if value:
                metadata[key] = str(value)
    return _tidy(document), metadata


def extract(
    body: bytes,
    *,
    content_type: str,
    url: str,
    encoding: str | None = None,
    include_links: bool = True,
) -> Extracted:
    if content_type in PDF_TYPES or (not content_type and body[:5] == b"%PDF-"):
        text = _from_pdf(body)
        if not text:
            raise Unextractable("no text layer in PDF")
        return Extracted(markdown=text, kind="pdf")

    if content_type in HTML_TYPES or content_type.endswith("+xml"):
        markdown, metadata = _from_html(_decode(body, encoding), url, include_links=include_links)
        if not markdown:
            raise Unextractable("no main content found")
        return Extracted(markdown=markdown, kind="html", metadata=metadata)

    if content_type.startswith("text/"):
        return Extracted(markdown=_tidy(_decode(body, encoding)), kind="text")

    raise Unextractable(f"unsupported content-type {content_type!r}")
