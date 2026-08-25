"""Fetching, with the guard that matters when the URL comes from a model."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import Settings


class BlockedURL(Exception):
    """The URL points somewhere we refuse to fetch from."""


class TooLarge(Exception):
    """The response body exceeded the configured cap."""


@dataclass(slots=True)
class Fetched:
    url: str
    status: int
    content_type: str
    body: bytes
    encoding: str | None


def _check_address(host: str | None, settings: Settings) -> None:
    if not host:
        raise BlockedURL("no host")
    if settings.allow_private_addresses:
        return
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedURL(f"cannot resolve {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # is_global is False for private, loopback, link-local, reserved,
        # multicast and unspecified ranges in one check — including
        # 169.254.169.254, the cloud metadata endpoint.
        if not ip.is_global:
            raise BlockedURL(f"{host} resolves to non-public address {ip}")


def check_url(url: str, settings: Settings) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedURL(f"unsupported scheme {parsed.scheme!r}")
    _check_address(parsed.hostname, settings)


def fetch(url: str, client: httpx.Client, settings: Settings) -> Fetched:
    """GET `url`, re-checking the guard on every redirect hop.

    Redirects are followed by hand rather than by httpx. A URL that passes the
    guard and then 302s to http://169.254.169.254/ is the whole attack, and
    httpx's own redirect handling would never show us the intermediate hops.
    """
    current = url
    for _ in range(settings.max_redirects + 1):
        check_url(current, settings)
        with client.stream("GET", current, follow_redirects=False) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise BlockedURL("redirect without a location header")
                current = str(response.next_request.url)
                continue

            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > settings.max_bytes:
                    raise TooLarge(f"body exceeds {settings.max_bytes} bytes")

            return Fetched(
                url=str(response.url),
                status=response.status_code,
                content_type=response.headers.get("content-type", "").split(";")[0].strip().lower(),
                body=bytes(body),
                encoding=response.encoding,
            )

    raise BlockedURL(f"more than {settings.max_redirects} redirects")
