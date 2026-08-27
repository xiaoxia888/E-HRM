from __future__ import annotations

from urllib.parse import urlsplit


def is_allowed_host_url(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    """Matches a URL host against the configured CAPTCHA automation hosts."""
    hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
    return hostname in {item.lower().rstrip(".") for item in allowed_hosts}


def url_without_sensitive_query(url: str) -> str:
    """Returns a log-safe URL without CAPTCHA session/query data."""

    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return parsed.path or "<unknown>"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
