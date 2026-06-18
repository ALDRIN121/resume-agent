"""Loopback-origin guards for the single-user localhost web app.

The app ships no authentication because it is meant to run on the user's own
machine. The real browser threat is therefore cross-site: a malicious web page
(or a DNS-rebinding attack) driving the local API to write API keys, trigger
SSRF via the connection test, or read local data. These helpers reject any
state-changing request whose ``Host`` is not loopback or whose ``Origin`` is
cross-site, which neutralises both vectors without needing a shared token.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}


def _hostname_is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.lower().strip("[]")
    if host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _host_header_is_loopback(host_header: str | None) -> bool:
    """True when the ``Host`` header points at loopback (port stripped)."""
    if not host_header:
        return False
    # urlsplit needs a scheme-relative authority to parse "host:port".
    return _hostname_is_loopback(urlsplit(f"//{host_header}").hostname)


def origin_is_allowed(origin: str | None) -> bool:
    """A missing Origin (same-origin / curl) is fine; a present one must be loopback."""
    if origin is None:
        return True
    return _hostname_is_loopback(urlsplit(origin).hostname)


def request_is_loopback(host_header: str | None, origin: str | None) -> bool:
    """Guard predicate for mutating HTTP requests and WebSocket handshakes."""
    return _host_header_is_loopback(host_header) and origin_is_allowed(origin)
