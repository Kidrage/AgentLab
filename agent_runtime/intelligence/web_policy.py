from __future__ import annotations

"""URL safety validation and web access policy for AgentLab intelligence.

This module is the safety layer. It blocks private networks, dangerous
schemes, and loopback addresses by default. Every outbound fetch must
pass through ``validate_url`` before a real HTTP request is issued.
"""

import ipaddress
import json
import socket
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urlunparse


# ---------------------------------------------------------------------------
# Dataclass for validation results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class URLValidation:
    """Result of validating a single URL against the active policy."""

    url: str
    allowed: bool
    reason: str
    normalized_url: str


# ---------------------------------------------------------------------------
# Dangerous schemes that must always be blocked
# ---------------------------------------------------------------------------

_BLOCKED_SCHEMES: set[str] = {
    "file",
    "ftp",
    "ssh",
    "data",
    "javascript",
    "telnet",
    "gopher",
}

_ALLOWED_SCHEMES: set[str] = {"http", "https"}


# ---------------------------------------------------------------------------
# Private / reserved IP ranges (RFC 1918, link-local, loopback, etc.)
# ---------------------------------------------------------------------------

_PRIVATE_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),     # link-local
    ipaddress.ip_network("0.0.0.0/8"),          # "this" network
    ipaddress.ip_network("100.64.0.0/10"),      # CGN shared
    ipaddress.ip_network("198.18.0.0/15"),      # benchmarking
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique-local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_private_ip(hostname: str) -> bool:
    """Return True when *hostname* resolves to a private / reserved address.

    The check first tries to parse *hostname* as a literal IP.  If that
    fails it performs a DNS lookup and tests every returned address.
    A resolution failure is treated as "private" (fail-closed).
    """
    # Try literal IP first
    try:
        addr = ipaddress.ip_address(hostname)
        return _address_is_private(addr)
    except ValueError:
        pass

    # DNS resolution
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # Fail-closed: if we cannot resolve, treat as private.
        return True

    if not infos:
        return True

    for info in infos:
        raw_addr = info[4][0]
        try:
            addr = ipaddress.ip_address(raw_addr)
        except ValueError:
            return True
        if _address_is_private(addr):
            return True

    return False


def _address_is_private(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Check a single IP address against the blocked ranges."""
    for network in _PRIVATE_NETWORKS:
        if addr in network:
            return True
    return False


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------

_DEFAULT_POLICY: dict = {
    "enabled": False,
    "mode": "mock_first",
    "obey_robots_txt": True,
    "rate_limit_per_minute": 10,
    "timeout_seconds": 10,
    "max_response_bytes": 524_288,   # 512 KB
    "allowed_schemes": ["http", "https"],
    "blocked_schemes": sorted(_BLOCKED_SCHEMES),
}


def load_web_policy(config_path: Path | None = None) -> dict:
    """Load a web-policy dict from *config_path* or return defaults.

    Supports a minimal JSON config file.  YAML support is deferred until
    a YAML parser is available in the dependency set.
    """
    if config_path is not None and config_path.is_file():
        try:
            raw = config_path.read_text(encoding="utf-8")
            user_policy = json.loads(raw)
            merged = {**_DEFAULT_POLICY, **user_policy}
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_POLICY)


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

def validate_url(
    url: str,
    policy: dict | None = None,
) -> URLValidation:
    """Validate *url* against the active policy and return a URLValidation.

    The function is deliberately strict: any URL that cannot be fully
    verified is rejected rather than allowed.
    """
    if policy is None:
        policy = _DEFAULT_POLICY

    if not url or not isinstance(url, str):
        return URLValidation(
            url=url or "",
            allowed=False,
            reason="Empty or non-string URL",
            normalized_url="",
        )

    # ---- Parse ----
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return URLValidation(
            url=url, allowed=False, reason="URL parse error", normalized_url=""
        )

    # ---- Scheme check ----
    scheme = (parsed.scheme or "").lower()
    if scheme in _BLOCKED_SCHEMES:
        return URLValidation(
            url=url,
            allowed=False,
            reason=f"Blocked scheme: {scheme}",
            normalized_url="",
        )
    if scheme not in _ALLOWED_SCHEMES:
        return URLValidation(
            url=url,
            allowed=False,
            reason=f"Disallowed scheme: {scheme or '(empty)'}",
            normalized_url="",
        )

    # ---- Hostname checks ----
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return URLValidation(
            url=url,
            allowed=False,
            reason="Missing hostname",
            normalized_url="",
        )

    # Block well-known loopback names
    if hostname in {"localhost", "localhost.localdomain", "ip6-localhost"}:
        return URLValidation(
            url=url,
            allowed=False,
            reason="Loopback hostname blocked",
            normalized_url="",
        )

    # Private / reserved IP check
    if is_private_ip(hostname):
        return URLValidation(
            url=url,
            allowed=False,
            reason=f"Private or reserved IP for hostname: {hostname}",
            normalized_url="",
        )

    # ---- Normalise ----
    normalized = urlunparse((
        scheme,
        parsed.netloc.lower(),
        parsed.path,
        parsed.params,
        parsed.query,
        "",  # drop fragment
    ))

    return URLValidation(
        url=url,
        allowed=True,
        reason="OK",
        normalized_url=normalized,
    )
