import pytest

from forage.extract import Unextractable, extract
from tests.conftest import ARTICLE, PDF


def test_html_keeps_content_and_drops_chrome():
    result = extract(ARTICLE, content_type="text/html", url="https://example.com/a")
    assert result.kind == "html"
    assert "actual point of the page" in result.markdown
    # The nav and footer are the whole reason to run an extractor rather than
    # a plain html-to-markdown converter.
    assert "Cookie banner" not in result.markdown
    assert "cookie banner" not in result.markdown.lower()
    assert "About" not in result.markdown


def test_html_metadata_is_populated():
    result = extract(ARTICLE, content_type="text/html", url="https://example.com/a")
    assert result.metadata["title"] == "The Heading"
    assert result.metadata["author"] == "A Person"


def test_links_can_be_dropped():
    with_links = extract(ARTICLE, content_type="text/html", url="https://e.com/a").markdown
    without = extract(
        ARTICLE, content_type="text/html", url="https://e.com/a", include_links=False
    ).markdown
    assert "https://example.com/ref" in with_links
    assert "https://example.com/ref" not in without
    assert "a link" in without


def test_tables_survive():
    result = extract(ARTICLE, content_type="text/html", url="https://example.com/a")
    assert "alpha" in result.markdown


def test_pdf_text_is_extracted():
    result = extract(PDF, content_type="application/pdf", url="https://example.com/x.pdf")
    assert result.kind == "pdf"
    assert "forage read this PDF" in result.markdown


def test_pdf_sniffed_without_content_type():
    result = extract(PDF, content_type="", url="https://example.com/x")
    assert result.kind == "pdf"


def test_plain_text_passes_through():
    result = extract(b"hello\n\n\n\nworld", content_type="text/plain", url="https://e.com/t")
    assert result.kind == "text"
    assert result.markdown == "hello\n\nworld"


def test_empty_page_is_unextractable():
    with pytest.raises(Unextractable):
        extract(b"<html><body></body></html>", content_type="text/html", url="https://e.com/")


def test_binary_is_rejected():
    with pytest.raises(Unextractable):
        extract(b"\x00\x01", content_type="application/octet-stream", url="https://e.com/")
