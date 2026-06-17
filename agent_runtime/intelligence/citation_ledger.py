from __future__ import annotations

"""Citation provenance ledger for AgentLab web intelligence.

The ledger is an append-only log of every source that was fetched and
used during a research run.  It persists to disk as JSONL (one JSON
object per line) so that downstream tools can audit provenance without
loading the entire file into memory.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class CitationEntry:
    """A single provenance record for one fetched source."""

    url: str
    fetched_at: str
    fetch_status: str          # "ok", "cached", "error", "mock"
    content_hash: str
    extracted_text_hash: str
    title: str = ""

    @staticmethod
    def hash_text(text: str) -> str:
        """SHA-256 hex digest of *text*."""
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Ledger container
# ---------------------------------------------------------------------------

class CitationLedger:
    """Append-only, serialisable ledger of citation entries.

    The ledger is intentionally a thin wrapper around a plain list so
    that it can be round-tripped through JSONL without any ORM or
    schema migration.
    """

    def __init__(self, entries: list[CitationEntry] | None = None) -> None:
        self.entries: list[CitationEntry] = list(entries) if entries else []

    # -- mutation -----------------------------------------------------------

    def append(self, entry: CitationEntry) -> None:
        """Add a new entry to the end of the ledger."""
        self.entries.append(entry)

    def append_from_fetch(
        self,
        url: str,
        body: str,
        extracted_text: str,
        *,
        fetch_status: str = "ok",
        title: str = "",
    ) -> CitationEntry:
        """Convenience: build a ``CitationEntry`` and append it.

        Returns the newly created entry.
        """
        entry = CitationEntry(
            url=url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            fetch_status=fetch_status,
            content_hash=CitationEntry.hash_text(body),
            extracted_text_hash=CitationEntry.hash_text(extracted_text),
            title=title,
        )
        self.append(entry)
        return entry

    # -- serialisation ------------------------------------------------------

    def to_jsonl(self) -> str:
        """Serialise the ledger to a JSONL string (one object per line)."""
        lines: list[str] = []
        for entry in self.entries:
            lines.append(json.dumps(asdict(entry), ensure_ascii=False))
        return "\n".join(lines) + ("\n" if lines else "")

    @classmethod
    def from_jsonl(cls, text: str) -> CitationLedger:
        """Deserialise a JSONL string back into a ``CitationLedger``.

        Malformed lines are silently skipped.
        """
        entries: list[CitationEntry] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                entries.append(CitationEntry(
                    url=raw.get("url", ""),
                    fetched_at=raw.get("fetched_at", ""),
                    fetch_status=raw.get("fetch_status", ""),
                    content_hash=raw.get("content_hash", ""),
                    extracted_text_hash=raw.get("extracted_text_hash", ""),
                    title=raw.get("title", ""),
                ))
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
        return cls(entries)

    # -- introspection ------------------------------------------------------

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def urls(self) -> list[str]:
        """Return a list of all URLs in the ledger, in insertion order."""
        return [e.url for e in self.entries]


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def write_citation_ledger(ledger: CitationLedger, path: Path) -> None:
    """Write *ledger* to *path* as JSONL.

    Creates parent directories if they do not exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger.to_jsonl(), encoding="utf-8")


def load_citation_ledger(path: Path) -> CitationLedger:
    """Load a ``CitationLedger`` from a JSONL file at *path*.

    Returns an empty ledger when the file does not exist or is
    unreadable — never raises on missing files.
    """
    if not path.is_file():
        return CitationLedger()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return CitationLedger()
    return CitationLedger.from_jsonl(text)
