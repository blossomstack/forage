import httpx
import pytest

from forage.config import Settings
from forage.net import BlockedURL, TooLarge, check_url, fetch

GUARDED = Settings(allow_private_addresses=False)
OPEN = Settings(allow_private_addresses=True, max_bytes=100_000)


@pytest.fixture
def client():
    with httpx.Client(timeout=5.0) as c:
        yield c


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://192.168.1.1/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        # The cloud metadata endpoint — the reason this guard exists at all.
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
    ],
)
def test_private_addresses_are_blocked(url):
    with pytest.raises(BlockedURL):
        check_url(url, GUARDED)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x/", "ftp://x/"])
def test_non_http_schemes_are_blocked(url):
    with pytest.raises(BlockedURL):
        check_url(url, GUARDED)


def test_public_address_passes():
    check_url("https://example.com/", GUARDED)


def test_guard_can_be_disabled_for_local_use():
    check_url("http://127.0.0.1/", OPEN)


def test_redirect_is_followed(server, client):
    result = fetch(f"{server}/redirect-to-article", client, OPEN)
    assert result.status == 200
    assert b"The Heading" in result.body


def test_redirect_into_a_private_address_is_blocked(server, client):
    """The guard runs on every hop, not just the URL the caller handed us.

    A public URL that 302s to 169.254.169.254 is the entire attack, and it
    passes any check that only looks at the original URL.
    """
    guarded_but_local = Settings(allow_private_addresses=False)
    with pytest.raises(BlockedURL):
        fetch(f"{server}/redirect-to-metadata", client, guarded_but_local)


def test_redirect_loop_terminates(server, client):
    with pytest.raises(BlockedURL, match="redirects"):
        fetch(f"{server}/redirect-loop", client, OPEN)


def test_oversized_body_is_rejected(server, client):
    small = Settings(allow_private_addresses=True, max_bytes=1024)
    with pytest.raises(TooLarge):
        fetch(f"{server}/huge", client, small)


def test_upstream_status_is_reported_not_raised(server, client):
    result = fetch(f"{server}/missing", client, OPEN)
    assert result.status == 404
