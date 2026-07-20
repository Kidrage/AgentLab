"""Rebuildable SQLite catalog and per-namespace knowledge shards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable, Sequence

from agent_runtime.local_search.document import Document, SourceCategory
from agent_runtime.local_search.query import query_index
from agent_runtime.policies import assert_path_allowed

from .models import (
    AuthorityLevel,
    KnowledgeLifecycle,
    KnowledgeRecord,
    SourceRef,
    stable_digest,
    validate_namespace,
)


SCHEMA_VERSION = 1
ELIGIBLE_AUTHORITIES = (AuthorityLevel.CANONICAL.value, AuthorityLevel.ACCEPTED.value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SearchHit:
    record_id: str
    namespace: str
    project_id: str | None
    source: SourceRef
    excerpt: str
    line_start: int
    line_end: int
    authority: str
    lifecycle: str
    modality: str
    object_kind: str
    score: float
    metadata: dict
    backend: str


class KnowledgeStore:
    """Owns the derived knowledge index behind a small transactional API."""

    def __init__(
        self,
        agentlab_root: Path,
        runtime_path: str = ".agentlab_runtime/knowledge",
        keyword_backend: str = "auto",
    ) -> None:
        self.agentlab_root = Path(agentlab_root).resolve()
        self.root = assert_path_allowed(self.agentlab_root / runtime_path, self.agentlab_root)
        self.spaces_root = self.root / "spaces"
        self.spaces_root.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.root / "catalog.sqlite3"
        self.keyword_backend = keyword_backend
        self._initialize_catalog()

    def _catalog(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.catalog_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize_catalog(self) -> None:
        with self._catalog() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS spaces (
                    namespace TEXT PRIMARY KEY,
                    db_name TEXT NOT NULL UNIQUE,
                    schema_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    backend TEXT NOT NULL DEFAULT 'sqlite_fts5',
                    updated_at TEXT NOT NULL
                )
                """
            )

    def ensure_space(self, namespace: str) -> Path:
        namespace = validate_namespace(namespace)
        db_name = f"{stable_digest(namespace)[:24]}.sqlite3"
        now = _utc_now()
        with self._catalog() as catalog:
            catalog.execute(
                """
                INSERT INTO spaces(namespace, db_name, schema_version, revision, status, backend, updated_at)
                VALUES (?, ?, ?, 0, 'active', 'sqlite_fts5', ?)
                ON CONFLICT(namespace) DO NOTHING
                """,
                (namespace, db_name, SCHEMA_VERSION, now),
            )
        path = assert_path_allowed(self.spaces_root / db_name, self.root)
        backend = self._initialize_shard(path)
        with self._catalog() as catalog:
            catalog.execute(
                "UPDATE spaces SET backend = ?, schema_version = ? WHERE namespace = ?",
                (backend, SCHEMA_VERSION, namespace),
            )
        return path

    def _initialize_shard(self, path: Path) -> str:
        with self._shard(path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    record_id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    project_id TEXT,
                    source_path TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    lifecycle TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    object_kind TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    relations_json TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS records_source_idx ON records(source_path)")
            connection.execute("CREATE INDEX IF NOT EXISTS records_eligibility_idx ON records(authority, lifecycle)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS shard_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO shard_meta(key, value) VALUES ('schema_version', ?), ('revision', '0')",
                (str(SCHEMA_VERSION),),
            )
            if self.keyword_backend == "bm25":
                return "degraded_bm25"
            try:
                fts_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'records_fts'"
                ).fetchone() is not None
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS records_fts
                    USING fts5(content, source_path, content='records', content_rowid='rowid', tokenize='unicode61')
                    """
                )
                connection.executescript(
                    """
                    CREATE TRIGGER IF NOT EXISTS records_ai AFTER INSERT ON records BEGIN
                      INSERT INTO records_fts(rowid, content, source_path)
                      VALUES (new.rowid, new.content, new.source_path);
                    END;
                    CREATE TRIGGER IF NOT EXISTS records_ad AFTER DELETE ON records BEGIN
                      INSERT INTO records_fts(records_fts, rowid, content, source_path)
                      VALUES ('delete', old.rowid, old.content, old.source_path);
                    END;
                    CREATE TRIGGER IF NOT EXISTS records_au AFTER UPDATE ON records BEGIN
                      INSERT INTO records_fts(records_fts, rowid, content, source_path)
                      VALUES ('delete', old.rowid, old.content, old.source_path);
                      INSERT INTO records_fts(rowid, content, source_path)
                      VALUES (new.rowid, new.content, new.source_path);
                    END;
                    """
                )
                if not fts_exists:
                    connection.execute("INSERT INTO records_fts(records_fts) VALUES ('rebuild')")
                return "sqlite_fts5"
            except sqlite3.OperationalError:
                return "degraded_bm25"

    @staticmethod
    def _shard(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _space_row(self, namespace: str) -> sqlite3.Row:
        with self._catalog() as connection:
            row = connection.execute("SELECT * FROM spaces WHERE namespace = ?", (namespace,)).fetchone()
        if row is None:
            self.ensure_space(namespace)
            with self._catalog() as connection:
                row = connection.execute("SELECT * FROM spaces WHERE namespace = ?", (namespace,)).fetchone()
        assert row is not None
        return row

    def sync_records(
        self,
        namespace: str,
        records: Sequence[KnowledgeRecord],
        *,
        scope: str,
        tombstone_missing: bool = True,
    ) -> int:
        namespace = validate_namespace(namespace)
        if any(record.namespace != namespace for record in records):
            raise ValueError("all records must belong to the synchronized namespace")
        path = self.ensure_space(namespace)
        now = _utc_now()
        record_ids = {record.record_id for record in records}
        changed = False
        with self._shard(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for record in records:
                serialized = (
                    record.namespace,
                    record.project_id,
                    record.source.path,
                    record.source.content_hash,
                    record.source.kind,
                    record.content,
                    json.dumps(dict(record.metadata), ensure_ascii=False, sort_keys=True),
                    record.authority.value,
                    record.lifecycle.value,
                    record.modality.value,
                    record.object_kind,
                    record.version,
                    json.dumps(list(record.relations), ensure_ascii=False, sort_keys=True),
                    scope,
                )
                existing = connection.execute(
                    """
                    SELECT namespace, project_id, source_path, source_hash, source_kind, content,
                           metadata_json, authority, lifecycle, modality, object_kind, version,
                           relations_json, scope
                    FROM records WHERE record_id = ?
                    """,
                    (record.record_id,),
                ).fetchone()
                if existing is not None and tuple(existing) == serialized:
                    continue
                connection.execute(
                    """
                    INSERT INTO records(
                        record_id, namespace, project_id, source_path, source_hash, source_kind,
                        content, metadata_json, authority, lifecycle, modality, object_kind,
                        version, relations_json, scope, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_id) DO UPDATE SET
                        namespace=excluded.namespace, project_id=excluded.project_id,
                        source_path=excluded.source_path, source_hash=excluded.source_hash,
                        source_kind=excluded.source_kind, content=excluded.content,
                        metadata_json=excluded.metadata_json, authority=excluded.authority,
                        lifecycle=excluded.lifecycle, modality=excluded.modality,
                        object_kind=excluded.object_kind, version=excluded.version,
                        relations_json=excluded.relations_json, scope=excluded.scope,
                        updated_at=excluded.updated_at
                    """,
                    (record.record_id, *serialized, now),
                )
                changed = True

            if not tombstone_missing:
                cursor = None
            elif record_ids:
                placeholders = ",".join("?" for _ in record_ids)
                cursor = connection.execute(
                    f"""
                    UPDATE records SET lifecycle = ?, updated_at = ?
                    WHERE scope = ? AND lifecycle != ? AND record_id NOT IN ({placeholders})
                    """,
                    (
                        KnowledgeLifecycle.TOMBSTONED.value,
                        now,
                        scope,
                        KnowledgeLifecycle.TOMBSTONED.value,
                        *sorted(record_ids),
                    ),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE records SET lifecycle = ?, updated_at = ?
                    WHERE scope = ? AND lifecycle != ?
                    """,
                    (
                        KnowledgeLifecycle.TOMBSTONED.value,
                        now,
                        scope,
                        KnowledgeLifecycle.TOMBSTONED.value,
                    ),
                )
            changed = changed or (cursor is not None and cursor.rowcount > 0)
            current_revision = int(
                connection.execute("SELECT value FROM shard_meta WHERE key = 'revision'").fetchone()[0]
            )
            revision = current_revision + 1 if changed else current_revision
            if changed:
                connection.execute(
                    "UPDATE shard_meta SET value = ? WHERE key = 'revision'", (str(revision),)
                )
            connection.commit()
        with self._catalog() as catalog:
            if changed:
                catalog.execute(
                    "UPDATE spaces SET revision = ?, status = 'active', updated_at = ? WHERE namespace = ?",
                    (revision, now, namespace),
                )
            else:
                catalog.execute(
                    "UPDATE spaces SET status = 'active', updated_at = ? WHERE namespace = ?",
                    (now, namespace),
                )
        return revision

    def search(
        self,
        namespaces: Sequence[str],
        query: str,
        *,
        max_results: int,
        authorities: Sequence[str] = ELIGIBLE_AUTHORITIES,
        modalities: Sequence[str] = (),
        path_hints: Sequence[str] = (),
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for namespace in namespaces:
            row = self._space_row(validate_namespace(namespace))
            path = assert_path_allowed(self.spaces_root / row["db_name"], self.root)
            if row["backend"] == "sqlite_fts5":
                try:
                    hits.extend(
                        self._search_fts(
                            path,
                            query,
                            max_results,
                            authorities,
                            modalities=modalities,
                            path_hints=path_hints,
                        )
                    )
                    continue
                except sqlite3.OperationalError:
                    self._set_backend(namespace, "degraded_bm25")
            hits.extend(
                self._search_bm25(
                    path,
                    query,
                    max_results,
                    authorities,
                    modalities=modalities,
                    path_hints=path_hints,
                )
            )
        hits.sort(key=lambda item: (-item.score, item.namespace, item.source.path, item.record_id))
        return hits[:max_results]

    def _search_fts(
        self,
        path: Path,
        query: str,
        max_results: int,
        authorities: Sequence[str],
        *,
        modalities: Sequence[str],
        path_hints: Sequence[str],
    ) -> list[SearchHit]:
        tokens = [token for token in re.findall(r"[\w-]+", query, flags=re.UNICODE) if token]
        if not tokens:
            return []
        match_query = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        authority_placeholders = ",".join("?" for _ in authorities)
        conditions = [
            "records_fts MATCH ?",
            "records.lifecycle = ?",
            f"records.authority IN ({authority_placeholders})",
        ]
        parameters: list[object] = [match_query, KnowledgeLifecycle.ACTIVE.value, *authorities]
        if modalities:
            modality_placeholders = ",".join("?" for _ in modalities)
            conditions.append(f"records.modality IN ({modality_placeholders})")
            parameters.extend(modalities)
        if path_hints:
            conditions.append("(" + " OR ".join("records.source_path LIKE ?" for _ in path_hints) + ")")
            parameters.extend("%" + hint.replace("\\", "/") + "%" for hint in path_hints)
        sql = f"""
            SELECT records.*, bm25(records_fts) AS search_rank
            FROM records_fts JOIN records ON records.rowid = records_fts.rowid
            WHERE {' AND '.join(conditions)}
            ORDER BY search_rank ASC, records.record_id ASC
            LIMIT ?
        """
        parameters.append(max_results)
        with self._shard(path) as connection:
            rows = connection.execute(sql, parameters).fetchall()
        results = []
        for position, row in enumerate(rows, start=1):
            rank_value = float(row["search_rank"] or 0.0)
            score = (1.0 / position) + max(0.0, -rank_value)
            results.append(self._hit_from_row(row, query, score=score, backend="sqlite_fts5"))
        return results

    def _search_bm25(
        self,
        path: Path,
        query: str,
        max_results: int,
        authorities: Sequence[str],
        *,
        modalities: Sequence[str],
        path_hints: Sequence[str],
    ) -> list[SearchHit]:
        authority_placeholders = ",".join("?" for _ in authorities)
        with self._shard(path) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM records
                WHERE lifecycle = ? AND authority IN ({authority_placeholders})
                ORDER BY record_id
                """,
                (KnowledgeLifecycle.ACTIVE.value, *authorities),
            ).fetchall()
        normalized_hints = tuple(item.replace("\\", "/").lower() for item in path_hints)
        rows = [
            row
            for row in rows
            if (not modalities or row["modality"] in modalities)
            and (
                not normalized_hints
                or any(hint in row["source_path"].lower() for hint in normalized_hints)
            )
        ]
        documents = [
            Document(
                path=row["record_id"],
                source_category=SourceCategory.REPO_FILES,
                content_hash=row["source_hash"],
                text=row["content"],
                line_count=max(1, row["content"].count("\n") + 1),
                size_bytes=len(row["content"].encode("utf-8")),
                indexed_at=row["updated_at"],
            )
            for row in rows
        ]
        ranked = query_index(documents, query, max_results=max_results)
        rows_by_id = {row["record_id"]: row for row in rows}
        return [
            self._hit_from_row(rows_by_id[result.path], query, score=result.score, backend="degraded_bm25")
            for result in ranked
        ]

    @staticmethod
    def _hit_from_row(row: sqlite3.Row, query: str, *, score: float, backend: str) -> SearchHit:
        excerpt, line_start, line_end = _excerpt(row["content"], query)
        return SearchHit(
            record_id=row["record_id"],
            namespace=row["namespace"],
            project_id=row["project_id"],
            source=SourceRef(row["source_path"], row["source_hash"], row["source_kind"]),
            excerpt=excerpt,
            line_start=line_start,
            line_end=line_end,
            authority=row["authority"],
            lifecycle=row["lifecycle"],
            modality=row["modality"],
            object_kind=row["object_kind"],
            score=score,
            metadata=json.loads(row["metadata_json"] or "{}"),
            backend=backend,
        )

    def _set_backend(self, namespace: str, backend: str) -> None:
        with self._catalog() as connection:
            connection.execute(
                "UPDATE spaces SET backend = ?, status = 'stale', updated_at = ? WHERE namespace = ?",
                (backend, _utc_now(), namespace),
            )

    def mark_stale(self, namespace: str) -> None:
        with self._catalog() as connection:
            connection.execute(
                "UPDATE spaces SET status = 'stale', updated_at = ? WHERE namespace = ?",
                (_utc_now(), validate_namespace(namespace)),
            )

    def index_snapshot(self, namespaces: Iterable[str]) -> str:
        ordered = tuple(sorted(validate_namespace(item) for item in namespaces))
        if not ordered:
            return stable_digest([], prefix="idx_")
        placeholders = ",".join("?" for _ in ordered)
        with self._catalog() as connection:
            rows = connection.execute(
                f"""
                SELECT namespace, schema_version, revision, status, backend
                FROM spaces WHERE namespace IN ({placeholders}) ORDER BY namespace
                """,
                ordered,
            ).fetchall()
        values = [dict(row) for row in rows]
        return stable_digest(values, prefix="idx_")


def _excerpt(content: str, query: str) -> tuple[str, int, int]:
    lines = content.splitlines() or [""]
    lowered_tokens = [token.lower() for token in re.findall(r"[\w-]+", query, flags=re.UNICODE)]
    best_index = 0
    best_score = -1
    for index, line in enumerate(lines):
        lowered = line.lower()
        score = sum(1 for token in lowered_tokens if token in lowered)
        if score > best_score:
            best_index = index
            best_score = score
    start = max(0, best_index - 1)
    end = min(len(lines), best_index + 2)
    excerpt = "\n".join(lines[start:end])
    if len(excerpt) > 600:
        excerpt = excerpt[:597] + "..."
    return excerpt, start + 1, end
