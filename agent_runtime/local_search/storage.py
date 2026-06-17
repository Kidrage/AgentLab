"""JSONL persistence for the local search index.

Documents are stored as one JSON object per line.  The format is
human-readable and easy to diff or grep.
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

from .document import Document


def save_index(docs: list[Document], path: Path) -> None:
    """Write the document list to a JSONL file.

    Creates parent directories if they do not exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as fh:
        for doc in docs:
            line = json.dumps(doc.to_dict(), ensure_ascii=False)
            fh.write(line + "\n")


def load_index(path: Path) -> list[Document]:
    """Read a JSONL index file and return a list of Document objects.

    Returns an empty list (with a warning) if the file does not exist.
    """
    if not path.is_file():
        warnings.warn(f"load_index: index file not found: {path}")
        return []

    documents: list[Document] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                documents.append(Document.from_dict(data))
            except (json.JSONDecodeError, KeyError) as exc:
                warnings.warn(
                    f"load_index: skipping malformed line {lineno} in {path}: {exc}"
                )
    return documents


def index_status(path: Path) -> dict:
    """Return summary information about an index file.

    Keys: count, size_bytes, last_modified, exists.
    """
    if not path.is_file():
        return {
            "exists": False,
            "count": 0,
            "size_bytes": 0,
            "last_modified": None,
        }

    stat = path.stat()
    size = stat.st_size
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    # Count lines (each line = one document)
    count = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                count += 1

    return {
        "exists": True,
        "count": count,
        "size_bytes": size,
        "last_modified": mtime,
    }
