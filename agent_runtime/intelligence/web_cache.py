from __future__ import annotations

"""Local source-snapshot cache for AgentLab web intelligence.

Every fetched page is written to disk as a JSON file keyed by the
SHA-256 of the normalised URL.  Subsequent look-ups for the same URL
return the cached copy without re-fetching, which keeps mock-mode and
offline test runs fully deterministic.
"""

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class CachedSource:
    """A single cached web resource."""

    url: str
    content_hash: str
    content_type: str
    body: str
    cached_at: str = ""
    fetch_status: int = 200

    def __post_init__(self) -> None:
        if not self.cached_at:
            self.cached_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def cache_key_for_url(url: str) -> str:
    """Return a stable SHA-256 hex digest for *url*.

    The URL is lower-cased and stripped before hashing so that trivial
    variations (trailing slash, case) produce the same key.
    """
    normalized = url.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _cache_file_path(content_hash: str, cache_dir: Path) -> Path:
    """Return the filesystem path for a given content hash."""
    return cache_dir / f"{content_hash}.json"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_to_cache(source: CachedSource, cache_dir: Path) -> Path:
    """Persist *source* as a JSON file inside *cache_dir*.

    The file is named ``<content_hash>.json``.  Returns the path that
    was written.

    Creates *cache_dir* if it does not already exist.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = _cache_file_path(source.content_hash, cache_dir)
    payload = asdict(source)
    dest.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return dest


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def load_from_cache(url: str, cache_dir: Path) -> CachedSource | None:
    """Look up a cached source by *url*.

    Returns ``None`` when no cache entry exists or the file is
    corrupt.  Never raises on missing files.
    """
    if not cache_dir.is_dir():
        return None

    key = cache_key_for_url(url)

    # We store files by content_hash, not URL hash, so we need to scan
    # the directory for a matching ``url`` field.  For small caches
    # this is fine; a production implementation would keep a separate
    # URL->hash index file.
    try:
        for entry in cache_dir.iterdir():
            if not entry.suffix == ".json":
                continue
            try:
                raw = json.loads(entry.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            entry_url = raw.get("url", "")
            if cache_key_for_url(entry_url) == key:
                return CachedSource(
                    url=raw.get("url", ""),
                    content_hash=raw.get("content_hash", ""),
                    content_type=raw.get("content_type", ""),
                    body=raw.get("body", ""),
                    cached_at=raw.get("cached_at", ""),
                    fetch_status=raw.get("fetch_status", 200),
                )
    except OSError:
        return None

    return None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def clear_cache(cache_dir: Path) -> int:
    """Delete every JSON file in *cache_dir*.  Returns the count removed."""
    if not cache_dir.is_dir():
        return 0
    count = 0
    for entry in cache_dir.iterdir():
        if entry.suffix == ".json" and entry.is_file():
            try:
                entry.unlink()
                count += 1
            except OSError:
                pass
    return count


def list_cached_urls(cache_dir: Path) -> list[str]:
    """Return a sorted list of all URLs currently held in *cache_dir*."""
    urls: list[str] = []
    if not cache_dir.is_dir():
        return urls
    for entry in cache_dir.iterdir():
        if entry.suffix != ".json":
            continue
        try:
            raw = json.loads(entry.read_text(encoding="utf-8"))
            url = raw.get("url")
            if url:
                urls.append(url)
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(urls)
