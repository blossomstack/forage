import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import import_app


@pytest.fixture
def client(monkeypatch):
    # The guard would otherwise block the test server on 127.0.0.1.
    monkeypatch.setenv("FORAGE_ALLOW_PRIVATE_ADDRESSES", "1")
    with TestClient(import_app()) as c:
        yield c


def test_health_exercises_the_extractor(client):
    body = client.get("/health").json()
    assert body["ok"] is True


def test_extract_returns_markdown(client, server):
    response = client.get("/extract", params={"url": f"{server}/article"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "actual point of the page" in response.text
    assert "About" not in response.text


def test_json_format_carries_metadata(client, server):
    response = client.get("/extract", params={"url": f"{server}/article", "format": "json"})
    body = json.loads(response.text)
    assert body["kind"] == "html"
    assert body["metadata"]["title"] == "The Heading"
    assert body["chars"] == len(body["markdown"])


def test_upstream_404_is_not_a_500(client, server):
    """A missing page and a broken extractor must not look the same.

    The obvious implementation calls raise_for_status() and turns every
    upstream error into an opaque 500, which leaves the caller unable to tell
    "this page is gone, try another" from "this service is down".
    """
    assert client.get("/extract", params={"url": f"{server}/missing"}).status_code == 404


def test_page_with_no_content_is_422(client, server):
    assert client.get("/extract", params={"url": f"{server}/empty"}).status_code == 422


def test_unsupported_type_is_422(client, server):
    assert client.get("/extract", params={"url": f"{server}/binary"}).status_code == 422


def test_pdf_is_extracted_over_http(client, server):
    response = client.get("/extract", params={"url": f"{server}/pdf"})
    assert response.status_code == 200
    assert "forage read this PDF" in response.text


def test_blocked_url_is_403(monkeypatch):
    monkeypatch.delenv("FORAGE_ALLOW_PRIVATE_ADDRESSES", raising=False)
    with TestClient(import_app()) as c:
        assert c.get("/extract", params={"url": "http://169.254.169.254/"}).status_code == 403
        assert c.get("/extract", params={"url": "file:///etc/passwd"}).status_code == 403
