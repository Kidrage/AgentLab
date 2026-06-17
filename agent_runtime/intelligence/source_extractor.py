from __future__ import annotations

"""Content extraction from HTML, Markdown, and plain text.

Uses only the Python standard library (``re`` for tag stripping).  The
extractors are deliberately simple — they are meant to give downstream
rankers and brief-generators a clean text blob, not to reproduce the
fidelity of a full rendering engine.
"""

import hashlib
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExtractedContent:
    """Text extracted from a web resource, ready for ranking or briefing."""

    title: str
    body_text: str
    content_type: str
    word_count: int
    content_hash: str

    @staticmethod
    def compute_hash(text: str) -> str:
        """SHA-256 hex digest of *text*."""
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_TITLE_RE = re.compile(
    r"<title[^>]*>(.*?)</title>",
    re.DOTALL | re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")
_ENTITY_MAP: dict[str, str] = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
    "&nbsp;": " ",
}
_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|#39|apos|nbsp);")


def _decode_entities(text: str) -> str:
    """Replace a small set of common HTML entities with their characters."""
    return _ENTITY_RE.sub(lambda m: _ENTITY_MAP.get(m.group(0), m.group(0)), text)


def extract_from_html(html: str) -> ExtractedContent:
    """Strip tags from *html* and return clean text inside ``ExtractedContent``."""
    # Title
    title_match = _TITLE_RE.search(html)
    title = title_match.group(1).strip() if title_match else ""

    # Remove script / style blocks
    body = _SCRIPT_STYLE_RE.sub(" ", html)

    # Strip remaining tags
    body = _TAG_RE.sub(" ", body)

    # Decode common entities
    body = _decode_entities(body)

    # Collapse whitespace
    body = _WHITESPACE_RE.sub(" ", body).strip()

    words = body.split()
    return ExtractedContent(
        title=title,
        body_text=body,
        content_type="text/html",
        word_count=len(words),
        content_hash=ExtractedContent.compute_hash(body),
    )


# ---------------------------------------------------------------------------
# Markdown extraction
# ---------------------------------------------------------------------------

_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MD_ITALIC_RE = re.compile(r"\*(.+?)\*|_(.+?)_")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_MD_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_MD_BLOCKQUOTE_RE = re.compile(r"^>\s?", re.MULTILINE)
_MD_HR_RE = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)


def _extract_md_title(md: str) -> str:
    """Return the first Markdown heading as the document title."""
    for line in md.splitlines():
        stripped = line.strip()
        match = re.match(r"^#{1,6}\s+(.+)", stripped)
        if match:
            return match.group(1).strip()
    return ""


def extract_from_markdown(md: str) -> ExtractedContent:
    """Strip Markdown syntax and return clean text."""
    title = _extract_md_title(md)

    body = md

    # Remove fenced code blocks (keep the code text)
    body = _MD_CODE_BLOCK_RE.sub(" ", body)

    # Inline code -> just the code text
    body = _MD_INLINE_CODE_RE.sub(r"\1", body)

    # Images first (before links, since images contain link syntax)
    body = _MD_IMAGE_RE.sub(r"\1", body)

    # Links -> anchor text
    body = _MD_LINK_RE.sub(r"\1", body)

    # Bold / italic
    body = _MD_BOLD_RE.sub(r"\1\2", body)
    body = _MD_ITALIC_RE.sub(r"\1\2", body)

    # Blockquote markers
    body = _MD_BLOCKQUOTE_RE.sub("", body)

    # Heading markers
    body = _MD_HEADING_RE.sub("", body)

    # Horizontal rules
    body = _MD_HR_RE.sub("", body)

    # Collapse whitespace
    body = _WHITESPACE_RE.sub(" ", body).strip()

    words = body.split()
    return ExtractedContent(
        title=title,
        body_text=body,
        content_type="text/markdown",
        word_count=len(words),
        content_hash=ExtractedContent.compute_hash(body),
    )


# ---------------------------------------------------------------------------
# Plain text extraction (passthrough)
# ---------------------------------------------------------------------------

def extract_from_text(text: str) -> ExtractedContent:
    """Passthrough extractor for plain text — computes word count and hash."""
    cleaned = _WHITESPACE_RE.sub(" ", text).strip()
    words = cleaned.split()
    return ExtractedContent(
        title="",
        body_text=cleaned,
        content_type="text/plain",
        word_count=len(words),
        content_hash=ExtractedContent.compute_hash(cleaned),
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def extract_content(body: str, content_type: str) -> ExtractedContent:
    """Dispatch to the correct extractor based on *content_type*.

    Recognised types:
    - ``text/html`` or anything containing ``html``
    - ``text/markdown`` or ``text/x-markdown``
    - everything else falls through to plain-text extraction
    """
    ct = (content_type or "").lower()

    if "html" in ct:
        return extract_from_html(body)
    if "markdown" in ct or "x-markdown" in ct:
        return extract_from_markdown(body)
    return extract_from_text(body)
