"""Artifact Producer task contracts and capability routing."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path, PureWindowsPath
import re
import stat
from typing import Any

import yaml


ARTIFACT_PRODUCER_ROLE = "ArtifactProducer"
MAX_ARTIFACT_INPUT_BYTES = 512 * 1024 * 1024


class ArtifactInputContractError(ValueError):
    """Raised when an ArtifactTask input binding cannot be trusted.

    The rendered message contains only a stable reason code and row/field
    coordinates.  In particular, it never includes a host-absolute path that
    could leak into a run receipt or provider packet.
    """

    def __init__(
        self,
        code: str,
        *,
        input_index: int | None = None,
        field: str | None = None,
    ) -> None:
        self.code = str(code)
        self.input_index = input_index
        self.field = field
        coordinates = []
        if input_index is not None:
            coordinates.append(f"input_index={input_index}")
        if field:
            coordinates.append(f"field={field}")
        suffix = f" ({', '.join(coordinates)})" if coordinates else ""
        super().__init__(f"{self.code}{suffix}")

    def as_receipt_issue(self) -> dict[str, Any]:
        issue: dict[str, Any] = {"code": self.code}
        if self.input_index is not None:
            issue["input_index"] = self.input_index
        if self.field:
            issue["field"] = self.field
        return issue

ARTIFACT_TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "image": (
        "image",
        "picture",
        "photo",
        "png",
        "jpg",
        "jpeg",
        "poster",
        "generate image",
        "生成图片",
        "图片",
        "图像",
        "海报",
        "插画",
        "配图",
    ),
    "video": ("video", "mp4", "movie", "视频", "影片", "短片"),
    "audio": ("audio", "voice", "speech", "mp3", "wav", "音频", "语音", "配音"),
    "spreadsheet": ("spreadsheet", "xlsx", "excel", "csv", "sheet", "表格", "电子表格"),
    "presentation": ("presentation", "slides", "slide deck", "ppt", "pptx", "幻灯片", "演示文稿"),
    "text": (
        "article",
        "report",
        "document",
        "markdown",
        "memo",
        "prd",
        "write a",
        "draft",
        "文本",
        "文档",
        "报告",
        "文章",
        "方案",
        "交接",
    ),
}

DEFAULT_FORMAT_BY_TYPE = {
    "audio": "wav",
    "image": "png",
    "mixed": "directory",
    "presentation": "pptx",
    "spreadsheet": "xlsx",
    "text": "markdown",
    "video": "mp4",
}

DEFAULT_CAPABILITY_BY_TYPE = {
    "audio": ["generate_audio", "write_artifact_file"],
    "image": ["generate_image", "write_artifact_file"],
    "mixed": ["produce_mixed_artifacts", "write_artifact_file", "validate_artifact_contract"],
    "presentation": ["create_presentation", "write_artifact_file"],
    "spreadsheet": ["create_spreadsheet", "write_artifact_file"],
    "text": ["write_text_artifact", "write_artifact_file"],
    "video": ["generate_video", "write_artifact_file"],
}

OUTPUT_FORMAT_HINTS: dict[str, tuple[str, ...]] = {
    "docx": ("docx",),
    "xlsx": ("xlsx", "excel workbook"),
    "csv": ("csv",),
    "pptx": ("pptx", "powerpoint"),
    "pdf": ("pdf",),
    "png": ("png",),
    "jpg": ("jpg", "jpeg"),
    "webp": ("webp",),
    "mp4": ("mp4",),
    "mov": ("mov",),
    "wav": ("wav",),
    "mp3": ("mp3",),
    "markdown": ("markdown", ".md"),
    "txt": ("plain text", ".txt"),
}

_OUTPUT_FORMATS_BY_TYPE = {
    "text": {"markdown", "txt", "docx"},
    "image": {"png", "jpg", "webp"},
    "video": {"mp4", "mov"},
    "audio": {"wav", "mp3"},
    "spreadsheet": {"xlsx", "csv"},
    "presentation": {"pptx", "pdf"},
    "mixed": {"directory"},
}

_STRONG_TEXT_DELIVERABLE_HINTS = (
    "article",
    "document",
    "markdown",
    "memo",
    "prd",
    "文章",
    "文档",
)


@dataclass(frozen=True)
class ArtifactRoute:
    provider_id: str
    worker: str
    priority: int
    fallback: bool
    reason: str


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or default
    except Exception:
        return default


def _load_policy(root: Path) -> dict[str, Any]:
    return _read_yaml(Path(root) / "config" / "artifact_task_policy.yml", {}) or {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_relative_parts(
    raw_value: Any,
    *,
    input_index: int,
    field: str,
) -> tuple[str, ...]:
    """Return a portable, traversal-free relative path as exact components."""

    if not isinstance(raw_value, str) or not raw_value:
        raise ArtifactInputContractError(
            "artifact_input_path_invalid",
            input_index=input_index,
            field=field,
        )
    if re.search(r"[\x00-\x1f\x7f]", raw_value) or "\\" in raw_value:
        raise ArtifactInputContractError(
            "artifact_input_path_invalid",
            input_index=input_index,
            field=field,
        )
    windows_path = PureWindowsPath(raw_value)
    parts = tuple(raw_value.split("/"))
    if (
        raw_value.startswith("/")
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ArtifactInputContractError(
            "artifact_input_path_invalid",
            input_index=input_index,
            field=field,
        )
    return parts


@contextmanager
def _open_root_relative_regular_file(
    root: Path,
    parts: tuple[str, ...],
    *,
    input_index: int,
):
    """Open a root-relative file without ever following a symlink segment."""

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    root_fd = -1
    opened_directories: list[int] = []
    file_fd = -1
    try:
        root_fd = os.open(Path(root).resolve(strict=True), directory_flags)
        current_fd = root_fd
        for component in parts[:-1]:
            try:
                component_stat = os.stat(
                    component,
                    dir_fd=current_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise ArtifactInputContractError(
                    "artifact_input_path_unreadable",
                    input_index=input_index,
                    field="source_path",
                ) from exc
            if stat.S_ISLNK(component_stat.st_mode):
                raise ArtifactInputContractError(
                    "artifact_input_symlink_not_allowed",
                    input_index=input_index,
                    field="source_path",
                )
            if not stat.S_ISDIR(component_stat.st_mode):
                raise ArtifactInputContractError(
                    "artifact_input_parent_not_directory",
                    input_index=input_index,
                    field="source_path",
                )
            try:
                next_fd = os.open(
                    component,
                    directory_flags | no_follow,
                    dir_fd=current_fd,
                )
            except OSError as exc:
                raise ArtifactInputContractError(
                    "artifact_input_path_unreadable",
                    input_index=input_index,
                    field="source_path",
                ) from exc
            opened_directories.append(next_fd)
            current_fd = next_fd

        try:
            leaf_stat = os.stat(
                parts[-1],
                dir_fd=current_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ArtifactInputContractError(
                "artifact_input_path_unreadable",
                input_index=input_index,
                field="source_path",
            ) from exc
        if stat.S_ISLNK(leaf_stat.st_mode):
            raise ArtifactInputContractError(
                "artifact_input_symlink_not_allowed",
                input_index=input_index,
                field="source_path",
            )
        if not stat.S_ISREG(leaf_stat.st_mode):
            raise ArtifactInputContractError(
                "artifact_input_not_regular_file",
                input_index=input_index,
                field="source_path",
            )
        try:
            file_fd = os.open(
                parts[-1],
                os.O_RDONLY | no_follow | getattr(os, "O_NONBLOCK", 0),
                dir_fd=current_fd,
            )
        except OSError as exc:
            raise ArtifactInputContractError(
                "artifact_input_path_unreadable",
                input_index=input_index,
                field="source_path",
            ) from exc
        opened_stat = os.fstat(file_fd)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or (opened_stat.st_dev, opened_stat.st_ino)
            != (leaf_stat.st_dev, leaf_stat.st_ino)
        ):
            raise ArtifactInputContractError(
                "artifact_input_changed_during_open",
                input_index=input_index,
                field="source_path",
            )
        yield file_fd
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        for descriptor in reversed(opened_directories):
            os.close(descriptor)
        if root_fd >= 0:
            os.close(root_fd)


def _hash_open_file_descriptor(
    file_fd: int,
    *,
    max_bytes: int | None = None,
) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_count = 0
    os.lseek(file_fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(file_fd, 1024 * 1024)
        if not chunk:
            break
        byte_count += len(chunk)
        if max_bytes is not None and byte_count > max_bytes:
            raise OverflowError("opened file exceeded its declared byte bound")
        digest.update(chunk)
    os.lseek(file_fd, 0, os.SEEK_SET)
    return digest.hexdigest(), byte_count


def _stable_file_identity(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(file_stat.st_dev),
        int(file_stat.st_ino),
        int(file_stat.st_size),
        int(file_stat.st_mtime_ns),
        int(file_stat.st_ctime_ns),
    )


def validate_artifact_task_inputs(
    root: Path,
    artifact_task: dict[str, Any],
) -> list[dict[str, Any]]:
    """Revalidate every explicit ArtifactTask input against current bytes.

    Validation is independent from contract generation.  Each path is opened
    component-by-component relative to the trusted AgentLab root using
    ``O_NOFOLLOW``.  Hashing occurs on the opened descriptor, with before/after
    ``fstat`` identity checks so mutation during validation fails closed.

    Returned rows contain one private ``_source_path`` value for in-process use.
    Callers must strip private keys before writing packets or receipts.
    """

    if not isinstance(artifact_task, dict):
        raise ArtifactInputContractError("artifact_task_contract_invalid")
    if "assigned_inputs" not in artifact_task:
        return []
    assigned_inputs = artifact_task.get("assigned_inputs")
    if not isinstance(assigned_inputs, list):
        raise ArtifactInputContractError(
            "artifact_input_rows_invalid",
            field="assigned_inputs",
        )

    resolved_root = Path(root).expanduser().resolve(strict=True)
    validated: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    seen_staged: set[str] = set()
    seen_files: set[tuple[int, int]] = set()
    total_bytes = 0
    for input_index, item in enumerate(assigned_inputs, start=1):
        if not isinstance(item, dict):
            raise ArtifactInputContractError(
                "artifact_input_row_invalid",
                input_index=input_index,
            )
        source_parts = _strict_relative_parts(
            item.get("source_path"),
            input_index=input_index,
            field="source_path",
        )
        staged_parts = _strict_relative_parts(
            item.get("staged_path"),
            input_index=input_index,
            field="staged_path",
        )
        source_path = "/".join(source_parts)
        staged_path = "/".join(staged_parts)
        expected_staged = f"artifact_inputs/{input_index:02d}_{source_parts[-1]}"
        if len(staged_parts) != 2 or staged_path != expected_staged:
            raise ArtifactInputContractError(
                "artifact_input_staged_path_invalid",
                input_index=input_index,
                field="staged_path",
            )
        if source_path in seen_sources:
            raise ArtifactInputContractError(
                "artifact_input_duplicate_source",
                input_index=input_index,
                field="source_path",
            )
        if staged_path in seen_staged:
            raise ArtifactInputContractError(
                "artifact_input_duplicate_staged_path",
                input_index=input_index,
                field="staged_path",
            )
        expected_hash = item.get("sha256")
        if (
            not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
        ):
            raise ArtifactInputContractError(
                "artifact_input_hash_binding_invalid",
                input_index=input_index,
                field="sha256",
            )
        expected_size = item.get("byte_count")
        if type(expected_size) is not int or expected_size < 0:
            raise ArtifactInputContractError(
                "artifact_input_size_binding_invalid",
                input_index=input_index,
                field="byte_count",
            )
        if item.get("read_only") is not True:
            raise ArtifactInputContractError(
                "artifact_input_read_only_binding_invalid",
                input_index=input_index,
                field="read_only",
            )
        total_bytes += expected_size
        if total_bytes > MAX_ARTIFACT_INPUT_BYTES:
            raise ArtifactInputContractError(
                "artifact_input_total_size_limit_exceeded",
                input_index=input_index,
                field="byte_count",
            )

        with _open_root_relative_regular_file(
            resolved_root,
            source_parts,
            input_index=input_index,
        ) as file_fd:
            before = os.fstat(file_fd)
            if before.st_size != expected_size:
                raise ArtifactInputContractError(
                    "artifact_input_size_mismatch",
                    input_index=input_index,
                    field="byte_count",
                )
            try:
                observed_hash, observed_size = _hash_open_file_descriptor(
                    file_fd,
                    max_bytes=expected_size,
                )
            except OverflowError as exc:
                raise ArtifactInputContractError(
                    "artifact_input_size_mismatch",
                    input_index=input_index,
                    field="byte_count",
                ) from exc
            after = os.fstat(file_fd)
        if _stable_file_identity(before) != _stable_file_identity(after):
            raise ArtifactInputContractError(
                "artifact_input_changed_while_hashing",
                input_index=input_index,
                field="source_path",
            )
        file_identity = (int(after.st_dev), int(after.st_ino))
        if file_identity in seen_files:
            raise ArtifactInputContractError(
                "artifact_input_duplicate_file",
                input_index=input_index,
                field="source_path",
            )
        if observed_size != expected_size:
            raise ArtifactInputContractError(
                "artifact_input_size_mismatch",
                input_index=input_index,
                field="byte_count",
            )
        if observed_hash != expected_hash:
            raise ArtifactInputContractError(
                "artifact_input_hash_mismatch",
                input_index=input_index,
                field="sha256",
            )
        seen_sources.add(source_path)
        seen_staged.add(staged_path)
        seen_files.add(file_identity)
        validated.append(
            {
                "source_path": source_path,
                "staged_path": staged_path,
                "sha256": expected_hash,
                "byte_count": expected_size,
                "read_only": True,
                "_source_path": resolved_root.joinpath(*source_parts),
            }
        )
    return validated


def stage_artifact_task_inputs(
    root: Path,
    artifact_task: dict[str, Any],
    workspace: Path,
) -> list[dict[str, Any]]:
    """Copy validated inputs into an isolated workspace as immutable files.

    Sources are reopened securely and streamed from the verified descriptor.
    The source identity is checked before and after the copy, and the staged
    bytes are compared with the contract hash and size before mode ``0400`` is
    applied.  Only deterministic ``artifact_inputs/<index>_<name>`` paths can
    be created.
    """

    validated = validate_artifact_task_inputs(root, artifact_task)
    if not validated:
        return []
    resolved_root = Path(root).expanduser().resolve(strict=True)
    resolved_workspace = Path(workspace).resolve(strict=True)
    input_directory = resolved_workspace / "artifact_inputs"
    try:
        input_directory.mkdir(mode=0o700, exist_ok=False)
    except OSError as exc:
        raise ArtifactInputContractError(
            "artifact_input_staging_directory_invalid",
            field="staged_path",
        ) from exc

    staged_rows: list[dict[str, Any]] = []
    try:
        for input_index, item in enumerate(validated, start=1):
            source_parts = tuple(str(item["source_path"]).split("/"))
            destination = resolved_workspace.joinpath(
                *str(item["staged_path"]).split("/")
            )
            try:
                destination.relative_to(resolved_workspace)
            except ValueError as exc:  # pragma: no cover - parser already rejects
                raise ArtifactInputContractError(
                    "artifact_input_staged_path_escape",
                    input_index=input_index,
                    field="staged_path",
                ) from exc
            digest = hashlib.sha256()
            copied_bytes = 0
            with _open_root_relative_regular_file(
                resolved_root,
                source_parts,
                input_index=input_index,
            ) as source_fd:
                before = os.fstat(source_fd)
                destination_flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                try:
                    destination_fd = os.open(destination, destination_flags, 0o600)
                except OSError as exc:
                    raise ArtifactInputContractError(
                        "artifact_input_staged_path_unwritable",
                        input_index=input_index,
                        field="staged_path",
                    ) from exc
                try:
                    while True:
                        chunk = os.read(source_fd, 1024 * 1024)
                        if not chunk:
                            break
                        if copied_bytes + len(chunk) > item["byte_count"]:
                            raise ArtifactInputContractError(
                                "artifact_input_staged_integrity_mismatch",
                                input_index=input_index,
                                field="staged_path",
                            )
                        digest.update(chunk)
                        copied_bytes += len(chunk)
                        view = memoryview(chunk)
                        while view:
                            written = os.write(destination_fd, view)
                            view = view[written:]
                    os.fsync(destination_fd)
                    os.fchmod(destination_fd, 0o400)
                    staged_stat = os.fstat(destination_fd)
                finally:
                    os.close(destination_fd)
                after = os.fstat(source_fd)

            if _stable_file_identity(before) != _stable_file_identity(after):
                raise ArtifactInputContractError(
                    "artifact_input_changed_while_staging",
                    input_index=input_index,
                    field="source_path",
                )
            if (
                copied_bytes != item["byte_count"]
                or digest.hexdigest() != item["sha256"]
                or staged_stat.st_size != item["byte_count"]
                or stat.S_IMODE(staged_stat.st_mode) != 0o400
            ):
                raise ArtifactInputContractError(
                    "artifact_input_staged_integrity_mismatch",
                    input_index=input_index,
                    field="staged_path",
                )
            staged_rows.append(
                {
                    key: value
                    for key, value in item.items()
                    if not str(key).startswith("_")
                }
            )
        input_directory.chmod(0o500)
    except Exception:
        # The caller owns a disposable isolated workspace.  Leave no writable
        # staged input behind while it prepares to clean that workspace.
        try:
            input_directory.chmod(0o500)
        except OSError:
            pass
        raise
    return staged_rows


def verify_staged_artifact_task_inputs(
    workspace: Path,
    validated_inputs: list[dict[str, Any]],
) -> None:
    """Verify that a CLI provider did not alter its read-only staged inputs."""

    if not validated_inputs:
        return
    resolved_workspace = Path(workspace).resolve(strict=True)
    input_directory = resolved_workspace / "artifact_inputs"
    try:
        directory_stat = input_directory.lstat()
    except OSError as exc:
        raise ArtifactInputContractError(
            "artifact_input_staging_directory_missing",
            field="staged_path",
        ) from exc
    if (
        stat.S_ISLNK(directory_stat.st_mode)
        or not stat.S_ISDIR(directory_stat.st_mode)
        or stat.S_IMODE(directory_stat.st_mode) != 0o500
    ):
        raise ArtifactInputContractError(
            "artifact_input_staging_directory_mutated",
            field="staged_path",
        )

    expected_names = {
        str(item["staged_path"]).split("/", 1)[1]
        for item in validated_inputs
    }
    try:
        with os.scandir(input_directory) as entries:
            observed_names = {entry.name for entry in entries}
    except OSError as exc:
        raise ArtifactInputContractError(
            "artifact_input_staging_directory_unreadable",
            field="staged_path",
        ) from exc
    if observed_names != expected_names:
        raise ArtifactInputContractError(
            "artifact_input_staging_set_mutated",
            field="staged_path",
        )

    for input_index, item in enumerate(validated_inputs, start=1):
        staged_parts = _strict_relative_parts(
            item.get("staged_path"),
            input_index=input_index,
            field="staged_path",
        )
        expected_staged = (
            f"artifact_inputs/{input_index:02d}_"
            f"{str(item.get('source_path') or '').split('/')[-1]}"
        )
        if "/".join(staged_parts) != expected_staged:
            raise ArtifactInputContractError(
                "artifact_input_staged_path_invalid",
                input_index=input_index,
                field="staged_path",
            )
        with _open_root_relative_regular_file(
            resolved_workspace,
            staged_parts,
            input_index=input_index,
        ) as staged_fd:
            before = os.fstat(staged_fd)
            if stat.S_IMODE(before.st_mode) != 0o400:
                raise ArtifactInputContractError(
                    "artifact_input_staged_mode_mutated",
                    input_index=input_index,
                    field="staged_path",
                )
            expected_size = item.get("byte_count")
            if type(expected_size) is not int or before.st_size != expected_size:
                raise ArtifactInputContractError(
                    "artifact_input_staged_integrity_mismatch",
                    input_index=input_index,
                    field="staged_path",
                )
            try:
                staged_hash, staged_size = _hash_open_file_descriptor(
                    staged_fd,
                    max_bytes=expected_size,
                )
            except OverflowError as exc:
                raise ArtifactInputContractError(
                    "artifact_input_staged_integrity_mismatch",
                    input_index=input_index,
                    field="staged_path",
                ) from exc
            after = os.fstat(staged_fd)
        if (
            _stable_file_identity(before) != _stable_file_identity(after)
            or staged_size != expected_size
            or staged_hash != item.get("sha256")
        ):
            raise ArtifactInputContractError(
                "artifact_input_staged_integrity_mismatch",
                input_index=input_index,
                field="staged_path",
            )


def _assigned_artifact_inputs(
    root: Path,
    assigned_input_paths: Iterable[str | Path] | None,
) -> list[dict[str, Any]]:
    """Bind explicit root-contained files to deterministic staging paths."""

    resolved_root = Path(root).expanduser().resolve(strict=False)
    rows: list[dict[str, Any]] = []
    for index, raw_path in enumerate(assigned_input_paths or (), start=1):
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = resolved_root / candidate
        # ``abspath`` normalizes dot segments without following symlinks. This
        # lets the contract reject both lexical escapes and every symlink in an
        # otherwise in-root path before hashing the source.
        lexical = Path(os.path.abspath(candidate))
        try:
            relative_lexical = lexical.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(
                f"artifact input is outside AgentLab root: {raw_path}"
            ) from exc

        current = resolved_root
        for part in relative_lexical.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(
                    f"artifact input cannot use a symbolic link: {raw_path}"
                )

        source = lexical.resolve(strict=False)
        try:
            source_path = source.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise ValueError(
                f"artifact input is outside AgentLab root: {raw_path}"
            ) from exc
        if not source.is_file():
            raise ValueError(f"artifact input must be a regular file: {raw_path}")

        before = source.stat()
        source_hash = _sha256_file(source)
        after = source.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise ValueError(f"artifact input changed while hashing: {source_path}")
        rows.append(
            {
                "source_path": source_path,
                "staged_path": (
                    Path("artifact_inputs") / f"{index:02d}_{source.name}"
                ).as_posix(),
                "sha256": source_hash,
                "byte_count": after.st_size,
                "read_only": True,
            }
        )
    return rows


def infer_artifact_components(task_text: str) -> list[str]:
    """Infer distinct requested deliverable types without weak text collisions."""

    lowered = str(task_text or "").lower()
    matched: list[str] = []
    for artifact_type, hints in ARTIFACT_TYPE_HINTS.items():
        if any(hint.lower() in lowered for hint in hints):
            matched.append(artifact_type)
    specific = [item for item in matched if item != "text"]
    if specific:
        strong_text = any(hint in lowered for hint in _STRONG_TEXT_DELIVERABLE_HINTS) or bool(
            re.search(r"\b(?:write|draft|create)\s+(?:a\s+|an\s+|the\s+)?report\b", lowered)
            or re.search(r"(?:写|撰写|起草|生成)(?:一份|一个|篇)?[^，。；,;]{0,8}报告", lowered)
        )
        return list(dict.fromkeys([*(['text'] if strong_text else []), *specific]))
    return ["text"] if "text" in matched else []


def infer_artifact_type(task_text: str) -> str | None:
    """Infer one artifact type, or ``mixed`` for genuinely distinct outputs."""

    matched = infer_artifact_components(task_text)
    if len(matched) > 1:
        return "mixed"
    return matched[0] if matched else None


def infer_output_format(task_text: str, artifact_type: str) -> str:
    """Resolve an explicit supported format before falling back by type."""

    lowered = str(task_text or "").lower()
    allowed = _OUTPUT_FORMATS_BY_TYPE.get(artifact_type, set())
    for output_format, hints in OUTPUT_FORMAT_HINTS.items():
        if allowed and output_format not in allowed:
            continue
        if any(
            re.search(rf"(?<![a-z0-9]){re.escape(hint.lstrip('.'))}(?![a-z0-9])", lowered)
            for hint in hints
        ):
            return output_format
    return DEFAULT_FORMAT_BY_TYPE.get(artifact_type, "artifact")


def capabilities_for_artifact_type(root: Path, artifact_type: str) -> list[str]:
    policy = _load_policy(root)
    configured = ((policy.get("artifact_types") or {}).get(artifact_type) or {}).get("required_capabilities")
    return list(configured or DEFAULT_CAPABILITY_BY_TYPE.get(artifact_type, []))


def route_artifact_provider(
    root: Path,
    artifact_type: str,
    *,
    required_capabilities: list[str] | None = None,
    preferred_provider: str | None = None,
    provider_type: str | None = None,
    output_format: str | None = None,
) -> dict[str, Any]:
    """Select the highest priority provider that can produce an artifact type."""
    policy = _load_policy(root)
    providers = policy.get("providers") or {}
    required = set(required_capabilities or capabilities_for_artifact_type(root, artifact_type))
    candidates: list[ArtifactRoute] = []

    for provider_id, cfg in providers.items():
        if preferred_provider and provider_id != preferred_provider:
            continue
        if (
            str(cfg.get("status") or "active") in {"quarantined", "disabled"}
            or cfg.get("automatic_use") is False
        ):
            continue
        if provider_type and str(cfg.get("provider_type") or "") != provider_type:
            continue
        handles = set(cfg.get("handles") or [])
        capabilities = set(cfg.get("capabilities") or [])
        output_formats = set(cfg.get("output_formats") or [])
        if artifact_type not in handles and "mixed" not in handles:
            continue
        if output_format and output_formats and output_format not in output_formats:
            continue
        if not required.issubset(capabilities):
            continue
        priority = int(cfg.get("priority", 0))
        candidates.append(ArtifactRoute(
            provider_id=provider_id,
            worker=str(cfg.get("worker", "")),
            priority=priority,
            fallback=bool(cfg.get("fallback", False)),
            reason=f"{provider_id} handles {artifact_type} with required capabilities",
        ))

    candidates.sort(key=lambda item: item.priority, reverse=True)
    selected = candidates[0] if candidates else None
    return {
        "artifact_type": artifact_type,
        "output_format": output_format,
        "provider_type": provider_type,
        "required_capabilities": sorted(required),
        "selected": asdict(selected) if selected else None,
        "candidates": [asdict(item) for item in candidates],
        "status": "routed" if selected else "capability_mismatch",
    }


def build_artifact_task_contract(
    root: Path,
    task_text: str,
    *,
    artifact_type: str | None = None,
    output_path: str | None = None,
    project: str = "AgentLab",
    task_id: str = "task_0001",
    preferred_provider: str | None = None,
    assigned_input_paths: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    assigned_inputs = _assigned_artifact_inputs(root, assigned_input_paths)
    components = infer_artifact_components(task_text)
    resolved_type = artifact_type or (
        "mixed" if len(components) > 1 else (components[0] if components else "text")
    )
    output_format = infer_output_format(task_text, resolved_type)
    path = output_path or f"projects/{project}/runs/{task_id}/outputs/{resolved_type}.{output_format}"
    required_capabilities = capabilities_for_artifact_type(root, resolved_type)
    if resolved_type == "mixed" and components:
        required_capabilities = list(
            dict.fromkeys(
                [
                    *required_capabilities,
                    *[
                        capability
                        for component in components
                        for capability in capabilities_for_artifact_type(root, component)
                    ],
                ]
            )
        )
    route = route_artifact_provider(
        root,
        resolved_type,
        required_capabilities=required_capabilities,
        preferred_provider=preferred_provider,
        output_format=output_format,
    )
    return {
        "packet_type": "agentlab_artifact_task",
        "schema_version": 1,
        "role": ARTIFACT_PRODUCER_ROLE,
        "project": project,
        "task_id": task_id,
        "intent": "create",
        "artifact_type": resolved_type,
        "artifact_components": components if resolved_type == "mixed" else [resolved_type],
        "required_capabilities": required_capabilities,
        "output": {
            "path": path,
            "format": output_format,
        },
        "requirements": [
            {"kind": "user_request", "text": task_text},
        ],
        "assigned_inputs": assigned_inputs,
        "validation": {
            "mode": "file_exists",
            "required_paths": [path],
        },
        "routing": route,
        "fallback": {
            "allowed": True,
            "status_on_missing_capability": "capability_mismatch",
        },
    }


def load_artifact_task_for_run(root: Path, project: str, task_id: str) -> dict[str, Any] | None:
    path = Path(root) / "projects" / project / "runs" / task_id / "artifact_task.yml"
    data = _read_yaml(path)
    return data if isinstance(data, dict) else None


def run_artifact_task_doctor(root: Path) -> dict[str, Any]:
    from agent_runtime.protocols.enforcement import check_role_binding

    root = Path(root)
    policy = _load_policy(root)
    checks: list[dict[str, str]] = []

    def check(ok: bool, check_id: str, message: str) -> None:
        checks.append({
            "id": check_id,
            "status": "pass" if ok else "fail",
            "severity": "fail",
            "message": message,
        })

    check(bool(policy), "artifact_task_policy_present", "config/artifact_task_policy.yml is present")
    check((root / "docs" / "ARTIFACT_PRODUCER_PROTOCOL.md").exists(), "artifact_protocol_doc_present", "Artifact Producer protocol doc exists")

    artifact_types = policy.get("artifact_types") or {}
    for required in ("text", "image", "video", "audio", "spreadsheet", "presentation", "mixed"):
        cfg = artifact_types.get(required) or {}
        check(bool(cfg.get("required_capabilities")), "artifact_type_capabilities_present", f"{required} has required capabilities")

    providers = policy.get("providers") or {}
    for provider_id in ("grok_media", "qwen_cli", "qwen_37max_api"):
        cfg = providers.get(provider_id) or {}
        check(bool(cfg), "artifact_provider_present", f"{provider_id} provider is configured")
        check(bool(cfg.get("worker")), "artifact_provider_worker_present", f"{provider_id} has a worker binding")
        if cfg.get("worker"):
            allowed, reason = check_role_binding(root, str(cfg["worker"]), ARTIFACT_PRODUCER_ROLE)
            check(allowed, "artifact_provider_worker_bound", f"{provider_id}/{cfg['worker']}: {reason}")

    sample = build_artifact_task_contract(root, "Generate a spreadsheet.xlsx", artifact_type="spreadsheet")
    check(sample["routing"]["status"] == "routed", "artifact_router_routes_sample", "artifact router can route a supported spreadsheet task")
    unsupported_mixed = build_artifact_task_contract(
        root,
        "Generate an image and spreadsheet bundle.",
        artifact_type="mixed",
    )
    check(
        unsupported_mixed["routing"]["status"] == "capability_mismatch",
        "cross_provider_mixed_blocks",
        "cross-provider mixed artifacts block until a composite adapter exists",
    )
    check(sample["packet_type"] == "agentlab_artifact_task", "artifact_task_contract_generates", "artifact task contract generation works")

    failed = [item for item in checks if item["status"] != "pass" and item["severity"] == "fail"]
    return {
        "doctor": "artifact_task_doctor",
        "status": "pass" if not failed else "fail",
        "summary": {"checks": len(checks), "failed": len(failed)},
        "checks": checks,
    }
