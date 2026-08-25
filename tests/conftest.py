import http.server
import sys
import threading

import pytest


def import_app():
    """Import `forage.app` fresh, honouring the current environment.

    Two reasons this cannot be a plain module-level import. The MCP server is
    built at import time, so the tool set is fixed by the environment as it was
    then. And the MCP session manager may only be run once per instance — a
    second TestClient over the same app object raises rather than starting — so
    each test needs its own.
    """
    for name in [n for n in sys.modules if n == "forage" or n.startswith("forage.")]:
        del sys.modules[name]
    from forage.app import app

    return app


ARTICLE = b"""<!doctype html><html><head><title>Test Article</title>
<meta name="author" content="A Person"></head><body>
<nav><a href="/">Home</a><a href="/about">About</a><a href="/contact">Contact</a></nav>
<article><h1>The Heading</h1>
<p>The first paragraph carries the actual point of the page and is long enough
that a content extractor will not mistake it for boilerplate noise.</p>
<p>A second paragraph with <a href="https://example.com/ref">a link</a> in it,
so link handling can be asserted either way.</p>
<table><tr><th>Key</th><th>Value</th></tr><tr><td>alpha</td><td>1</td></tr></table>
</article>
<footer>Copyright notice, share buttons, and a cookie banner.</footer></body></html>"""


def _minimal_pdf(text: str) -> bytes:
    """A valid one-page PDF, built here so the suite needs no PDF writer.

    Offsets and the xref table are computed rather than hardcoded — pypdf
    rejects a PDF whose xref does not line up, which is exactly what a
    hand-typed fixture gets wrong.
    """
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n%s\nendstream" % (len(stream), stream),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)


PDF = _minimal_pdf("forage read this PDF")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output readable
        pass

    def _send(self, status, body, content_type, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/article":
            self._send(200, ARTICLE, "text/html; charset=utf-8")
        elif self.path == "/plain":
            self._send(200, b"just some text", "text/plain; charset=utf-8")
        elif self.path == "/pdf":
            self._send(200, PDF, "application/pdf")
        elif self.path == "/binary":
            self._send(200, b"\x00\x01\x02", "application/octet-stream")
        elif self.path == "/empty":
            self._send(200, b"<html><body></body></html>", "text/html")
        elif self.path == "/missing":
            self._send(404, b"gone", "text/html")
        elif self.path == "/huge":
            self._send(200, b"x" * 200_000, "text/plain")
        elif self.path == "/redirect-to-article":
            self._send(302, b"", "text/html", {"Location": "/article"})
        elif self.path == "/redirect-to-metadata":
            self._send(
                302, b"", "text/html", {"Location": "http://169.254.169.254/latest/meta-data/"}
            )
        elif self.path == "/redirect-loop":
            self._send(302, b"", "text/html", {"Location": "/redirect-loop"})
        else:
            self._send(404, b"?", "text/plain")


@pytest.fixture(scope="session")
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
