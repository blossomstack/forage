"""The MCP surface, exercised through a real client over the mounted app.

These drive the mounted app over HTTP rather than poking the tool functions
directly: the failures worth catching here are transport-level — a session
manager whose lifespan never ran, a mount path that resolves to the wrong
place, host validation rejecting the deployment's own hostname — and none of
them show up when you call the Python function.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import import_app


@pytest.fixture
def env(monkeypatch, server):
    monkeypatch.setenv("FORAGE_ALLOW_PRIVATE_ADDRESSES", "1")
    monkeypatch.setenv("FORAGE_SEARCH_URL", server)
    monkeypatch.setenv("FORAGE_MCP_ALLOWED_HOSTS", "*")


@pytest.fixture
def client(env):
    with TestClient(import_app()) as c:
        yield c


def test_mcp_is_mounted_with_a_lifespan(client):
    """A mounted Starlette sub-app does not get its lifespan run automatically.

    Without `session_manager.run()` in the parent lifespan the route still
    exists and answers, so a smoke test that only checks for a non-404 passes
    against a completely broken transport. Initialising a session is what
    fails.
    """
    response = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200
    assert "forage" in response.text


def test_bare_mcp_path_redirects_to_the_slash(client):
    response = client.post("/mcp", json={}, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].endswith("/mcp/")


def test_rest_routes_still_work_beside_the_mount(client, server):
    assert client.get("/health").json()["ok"] is True
    assert client.get("/extract", params={"url": f"{server}/article"}).status_code == 200


def test_health_reports_search_is_configured(client):
    assert client.get("/health").json()["search"] is True


def test_search_tool_absent_without_a_backend(monkeypatch, server):
    monkeypatch.delenv("FORAGE_SEARCH_URL", raising=False)
    monkeypatch.setenv("FORAGE_ALLOW_PRIVATE_ADDRESSES", "1")
    app = import_app()
    with TestClient(app) as c:
        assert c.get("/health").json()["search"] is False
    from forage.app import mcp_server

    names = {tool.name for tool in mcp_server._tool_manager.list_tools()}
    assert "fetch" in names
    assert "search" not in names


def test_host_validation_rejects_an_unknown_host(monkeypatch, server):
    """The SDK's DNS-rebinding protection is on by default and answers 421.

    That is exactly what a deployment behind a reverse proxy hits, and it looks
    like a broken route rather than a setting.
    """
    monkeypatch.setenv("FORAGE_MCP_ALLOWED_HOSTS", "forage.example.com")
    monkeypatch.setenv("FORAGE_ALLOW_PRIVATE_ADDRESSES", "1")
    with TestClient(import_app()) as c:
        rejected = c.post("/mcp/", json={}, headers={"Host": "somewhere.else"})
        assert rejected.status_code == 421

        allowed = c.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            },
            headers={"Host": "forage.example.com", "Accept": "application/json, text/event-stream"},
        )
        assert allowed.status_code == 200


def test_tool_failures_reach_the_model(client, server):
    """Tool errors must carry their own text, not a masked crash message.

    The SDK only forwards the message of a `ToolError`; every other exception is
    treated as a crash and replaced with "Error executing tool fetch". Raising a
    bare ValueError therefore leaves a model unable to tell "needs JavaScript,
    try another result" from "blocked by policy" from "404" — which is the whole
    reason those are distinguished.
    """
    session = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    sid = session.headers["mcp-session-id"]
    headers = {
        "Accept": "application/json, text/event-stream",
        "mcp-session-id": sid,
        "MCP-Protocol-Version": "2025-06-18",
    }
    client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
    )
    called = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "fetch", "arguments": {"url": f"{server}/missing"}},
        },
        headers=headers,
    )
    assert "returned HTTP 404" in called.text

    empty = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "fetch", "arguments": {"url": f"{server}/empty"}},
        },
        headers=headers,
    )
    # The message a model needs in order to escalate rather than retry.
    assert "may need JavaScript to render" in empty.text
