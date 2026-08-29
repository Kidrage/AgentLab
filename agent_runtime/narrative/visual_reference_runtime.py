"""Governed ingestion seam for Codex-managed narrative identity images."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterator, Mapping
import uuid
import warnings

from PIL import Image, UnidentifiedImageError
import yaml

from agent_runtime.narrative.visual_detail_cards import (
    require_current_visual_detail_card_pack,
    resolve_visual_stage_contracts,
    validate_managed_imagegen_attestation,
    validate_visual_pack_runtime_provenance,
    visual_reference_task_id,
)
from agent_runtime.production_protocols import (
    ProductionProtocolRunner,
    compile_production_protocol,
)
from agent_runtime.task_runtime_v2 import InvalidTransition, TaskRuntime


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _nonempty(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"managed imagegen {field} is required")
    return normalized


def _safe_id(value: Any, *, field: str) -> str:
    normalized = _nonempty(value, field=field)
    if not _SAFE_ID.fullmatch(normalized) or ".." in normalized:
        raise ValueError(f"managed imagegen {field} is not a safe identifier")
    return normalized


def _image_media_type(content: bytes) -> tuple[str, str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as candidate:
                image_format = str(candidate.format or "").upper()
                width, height = candidate.size
                frames = int(getattr(candidate, "n_frames", 1))
                candidate.verify()
            with Image.open(BytesIO(content)) as decoded:
                decoded.load()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        raise ValueError("managed imagegen result is not a decodable image") from exc
    formats = {
        "PNG": ("image/png", ".png"),
        "JPEG": ("image/jpeg", ".jpg"),
        "WEBP": ("image/webp", ".webp"),
    }
    if (
        image_format not in formats
        or width < 1
        or height < 1
        or width > 16384
        or height > 16384
        or width * height > 100_000_000
        or frames != 1
    ):
        raise ValueError(
            "managed imagegen result must be one bounded PNG, JPEG, or WebP"
        )
    return formats[image_format]


def _assert_no_symlink_ancestry(path: Path, boundary: Path) -> None:
    boundary_root = boundary.resolve(strict=True)
    lexical = Path(os.path.abspath(path))
    try:
        relative = lexical.relative_to(boundary_root)
    except ValueError as exc:
        raise ValueError("managed imagegen output escaped its Task") from exc
    cursor = boundary_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise ValueError("managed imagegen output ancestry contains a symlink")


def _open_task_subdirectory(
    agentlab_root: Path,
    task_root: Path,
    parts: tuple[str, ...],
) -> int:
    try:
        relative = task_root.relative_to(agentlab_root)
    except ValueError as exc:
        raise ValueError("managed imagegen Task escaped AgentLab") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(agentlab_root, flags)
    try:
        for part in (*relative.parts, *parts):
            if not _SAFE_ID.fullmatch(part) or ".." in part:
                raise ValueError("managed imagegen Task path component is invalid")
            try:
                os.mkdir(part, 0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise ValueError(
            "managed imagegen output ancestry contains a symlink or invalid directory"
        ) from exc
    except BaseException:
        os.close(descriptor)
        raise


def _read_regular_file_at(directory_fd: int, leaf: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(leaf, flags, dir_fd=directory_fd)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise InvalidTransition("managed imagegen evidence is not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _atomic_write_or_verify_at(directory_fd: int, leaf: str, content: bytes) -> None:
    if Path(leaf).name != leaf or not leaf:
        raise ValueError("managed imagegen evidence leaf is invalid")
    try:
        observed = _read_regular_file_at(directory_fd, leaf)
    except FileNotFoundError:
        observed = None
    if observed is not None:
        if observed != content:
            raise InvalidTransition("managed imagegen evidence drifted")
        return
    temporary = f".{leaf}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary,
                leaf,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            if _read_regular_file_at(directory_fd, leaf) != content:
                raise InvalidTransition("managed imagegen evidence drifted")
    finally:
        os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _atomic_replace_at(directory_fd: int, leaf: str, content: bytes) -> None:
    if Path(leaf).name != leaf or not leaf:
        raise ValueError("managed imagegen projection leaf is invalid")
    temporary = f".{leaf}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(
            temporary,
            leaf,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    finally:
        os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _write_task_file(
    task_descriptor: int,
    directory_parts: tuple[str, ...],
    leaf: str,
    content: bytes,
) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.dup(task_descriptor)
    try:
        try:
            for part in directory_parts:
                if not _SAFE_ID.fullmatch(part) or ".." in part:
                    raise ValueError("managed imagegen Task path component is invalid")
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            _atomic_write_or_verify_at(descriptor, leaf, content)
        except OSError as exc:
            raise ValueError(
                "managed imagegen output ancestry contains a symlink or invalid directory"
            ) from exc
    finally:
        os.close(descriptor)


def _yaml_bytes(document: Mapping[str, Any]) -> bytes:
    return yaml.safe_dump(
        dict(document),
        sort_keys=False,
        allow_unicode=True,
    ).encode("utf-8")


class _AnchoredTaskRuntime(TaskRuntime):
    """TaskRuntime view whose governed Task always resolves through one open FD."""

    def __init__(
        self,
        agentlab_root: Path,
        *,
        project: str,
        task_id: str,
        task_descriptor: int,
        expected_task_root: Path,
    ) -> None:
        super().__init__(agentlab_root, project=project)
        self._anchored_task_id = task_id
        self._task_descriptor = task_descriptor
        self._expected_task_root = Path(os.path.abspath(expected_task_root))
        flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        tasks_descriptor = os.open("..", flags, dir_fd=task_descriptor)
        try:
            self._runtime_descriptor = os.open(
                "..",
                flags,
                dir_fd=tasks_descriptor,
            )
        finally:
            os.close(tasks_descriptor)
        self._expected_runtime_root = self._expected_task_root.parent.parent

    @staticmethod
    def _descriptor_path(descriptor: int) -> Path:
        if descriptor < 0:
            raise InvalidTransition("anchored visual TaskRuntime is closed")
        if sys.platform == "darwin":
            raw_path = fcntl.fcntl(
                descriptor,
                50,
                b"\0" * 1024,
            )
            current = Path(os.fsdecode(raw_path.split(b"\0", 1)[0]))
        else:
            current = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        return Path(os.path.abspath(current))

    def _current_task_root(self) -> Path:
        current = self._descriptor_path(self._task_descriptor)
        if current != self._expected_task_root:
            raise InvalidTransition("anchored visual Task inode moved or was replaced")
        return current

    def _current_runtime_root(self) -> Path:
        current = self._descriptor_path(self._runtime_descriptor)
        if current != self._expected_runtime_root:
            raise InvalidTransition(
                "anchored visual Runtime inode moved or was replaced"
            )
        return current

    def _task_dir(self, task_id: str) -> Path:
        normalized = _safe_id(task_id, field="task_id")
        if normalized == self._anchored_task_id:
            return self._current_task_root()
        return super()._task_dir(normalized)

    @contextmanager
    def _ledger_lock(self, task_id: str) -> Iterator[None]:
        if _safe_id(task_id, field="task_id") != self._anchored_task_id:
            with super()._ledger_lock(task_id):
                yield
            return
        self._current_task_root()
        self._current_runtime_root()
        directory_flags = os.O_RDONLY | os.O_DIRECTORY
        file_flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
            file_flags |= os.O_NOFOLLOW
        try:
            os.mkdir(".locks", 0o700, dir_fd=self._runtime_descriptor)
        except FileExistsError:
            pass
        locks_descriptor = os.open(
            ".locks",
            directory_flags,
            dir_fd=self._runtime_descriptor,
        )
        try:
            lock_descriptor = os.open(
                f"{self._anchored_task_id}.lock",
                file_flags,
                0o600,
                dir_fd=locks_descriptor,
            )
        finally:
            os.close(locks_descriptor)
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)

    @contextmanager
    def _admission_lock(self) -> Iterator[None]:
        self._current_task_root()
        self._current_runtime_root()
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(
            ".admission.lock",
            flags,
            0o600,
            dir_fd=self._runtime_descriptor,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _read_ledger_text(self, task_id: str) -> str | None:
        if _safe_id(task_id, field="task_id") != self._anchored_task_id:
            return super()._read_ledger_text(task_id)
        self._current_task_root()
        try:
            content = _read_regular_file_at(self._task_descriptor, "events.jsonl")
        except FileNotFoundError:
            return None
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidTransition("anchored visual Task ledger is not UTF-8") from exc

    def _append_ledger_line(self, task_id: str, line: str) -> None:
        if _safe_id(task_id, field="task_id") != self._anchored_task_id:
            super()._append_ledger_line(task_id, line)
            return
        self._current_task_root()
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(
            "events.jsonl",
            flags,
            0o600,
            dir_fd=self._task_descriptor,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise InvalidTransition("anchored visual Task ledger is not regular")
            payload = line.encode("utf-8")
            offset = 0
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _materialize_task_projections(
        self, task_id: str, projection: dict[str, Any]
    ) -> None:
        if _safe_id(task_id, field="task_id") != self._anchored_task_id:
            super()._materialize_task_projections(task_id, projection)
            return
        self._current_task_root()
        counts: dict[str, int] = {}
        for work_item in projection["work_items"].values():
            status = work_item["status"]
            counts[status] = counts.get(status, 0) + 1
        documents = {
            "task.yml": projection,
            "jobs.yml": projection["jobs"],
            "work_items.yml": projection["work_items"],
            "attempts.yml": projection["attempts"],
            "artifact_index.yml": projection["artifacts"],
            "evidence.yml": projection["evidence_bindings"],
            "trace_records.yml": projection["trace_records"],
            "progress.yml": {
                "task_id": projection["task"]["task_id"],
                "task_status": projection["task"]["status"],
                "work_item_counts": counts,
                "attempt_count": len(projection["attempts"]),
                "last_event_sequence": projection["last_event_sequence"],
            },
            "handoff.yml": {
                "task_id": projection["task"]["task_id"],
                "user_goal": projection["task"]["user_goal"],
                "status": projection["task"]["status"],
                "selected_artifact_version": projection["selected_artifact_version"],
                "input_tier": (
                    projection["task"].get("input_classification") or {}
                ).get("tier"),
                "last_event_hash": projection["last_event_hash"],
            },
        }
        for leaf, document in documents.items():
            flags = os.O_RDONLY | os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                os.mkdir("projections", 0o700, dir_fd=self._task_descriptor)
            except FileExistsError:
                pass
            projection_descriptor = os.open(
                "projections",
                flags,
                dir_fd=self._task_descriptor,
            )
            try:
                _atomic_replace_at(
                    projection_descriptor,
                    leaf,
                    _yaml_bytes(document),
                )
            finally:
                os.close(projection_descriptor)

    def _read_task_file(self, parts: tuple[str, ...]) -> bytes:
        if not parts:
            raise ValueError("managed imagegen evidence path is empty")
        flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.dup(self._task_descriptor)
        try:
            for part in parts[:-1]:
                if not _SAFE_ID.fullmatch(part) or ".." in part:
                    raise InvalidTransition("managed imagegen evidence path is invalid")
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return _read_regular_file_at(descriptor, parts[-1])
        except OSError as exc:
            raise InvalidTransition(
                "managed imagegen evidence path is unavailable"
            ) from exc
        finally:
            os.close(descriptor)

    def _validate_attempt_execution_receipt(
        self,
        *,
        task_id: str,
        attempt: dict[str, Any],
        outcome: dict[str, Any],
    ) -> None:
        if _safe_id(task_id, field="task_id") != self._anchored_task_id:
            super()._validate_attempt_execution_receipt(
                task_id=task_id,
                attempt=attempt,
                outcome=outcome,
            )
            return
        attempt_id = _safe_id(attempt.get("attempt_id"), field="attempt_id")
        receipt_parts = (
            "attempt_logs",
            attempt_id,
            "attempt_receipt.yml",
        )
        receipt_bytes = self._read_task_file(receipt_parts)
        try:
            receipt = yaml.safe_load(receipt_bytes.decode("utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise InvalidTransition(
                "managed imagegen Attempt receipt is invalid"
            ) from exc
        contract = attempt.get("execution_contract") or {}
        expected_receipt = {
            "schema_version": "task-runtime-role-attempt-receipt/v1",
            "project": self.project,
            "task_id": task_id,
            "work_item_id": attempt.get("work_item_id"),
            "attempt_id": attempt_id,
            "role": contract.get("role"),
            "worker": attempt.get("worker"),
            "provider": attempt.get("provider"),
            "status": "pass",
        }
        receipt_relative = "/".join(receipt_parts)
        if (
            outcome.get("execution_origin") != "role_attempt_executor"
            or outcome.get("receipt_path") != receipt_relative
            or outcome.get("receipt_sha256")
            != hashlib.sha256(receipt_bytes).hexdigest()
            or not isinstance(receipt, dict)
            or any(
                receipt.get(field) != value for field, value in expected_receipt.items()
            )
            or receipt.get("sealed_sources") != []
        ):
            raise InvalidTransition("managed imagegen Attempt receipt binding drifted")
        output_bytes = self._read_task_file(("attempt_logs", attempt_id, "output.md"))
        output_sha256 = hashlib.sha256(output_bytes).hexdigest()
        if (
            receipt.get("output_path") != f"attempt_logs/{attempt_id}/output.md"
            or receipt.get("output_sha256") != output_sha256
            or outcome.get("output_sha256") != output_sha256
        ):
            raise InvalidTransition("managed imagegen Attempt output drifted")
        model_bytes = self._read_task_file(
            ("attempt_logs", attempt_id, "model_execution_receipt.yml")
        )
        try:
            model = yaml.safe_load(model_bytes.decode("utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise InvalidTransition(
                "managed imagegen model receipt is invalid"
            ) from exc
        model_execution = receipt.get("model_execution") or {}
        expected_model = {
            "cli_agent": attempt.get("worker"),
            "model_key": contract.get("model_key"),
            "model_id": contract.get("model_id"),
            "runtime_provider": contract.get("runtime_provider"),
            "executor_provider": "agentlab-cli-executor",
        }
        if (
            model_execution.get("path")
            != f"attempt_logs/{attempt_id}/model_execution_receipt.yml"
            or model_execution.get("sha256") != hashlib.sha256(model_bytes).hexdigest()
            or any(
                model_execution.get(field) != value
                for field, value in expected_model.items()
            )
            or model.get("status") != "pass"
            or model.get("worker") != attempt.get("worker")
            or model.get("invocation_contract") != contract.get("invocation_contract")
            or model.get("selected_provider") != contract.get("runtime_provider")
            or model.get("selected_model_id") != contract.get("model_id")
            or model.get("profile_binding_verified") is not True
            or model.get("command_binding_verified") is not True
            or model.get("provider_model_binding_verified") is not True
            or model.get("provider_process_started") is not True
            or model.get("fallback_detected") is not False
            or model.get("exit_code") != 0
            or model.get("issues") not in (None, [])
            or model.get("execution_surface") != "codex_managed_imagegen"
            or model.get("managed_tool") != "image_gen.imagegen"
        ):
            raise InvalidTransition("managed imagegen model binding drifted")

    def record_attempt_output_validation(
        self,
        task_id: str,
        *,
        attempt_id: str,
        status: str,
        validation_receipt_path: Path,
        issues: list[str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if _safe_id(task_id, field="task_id") != self._anchored_task_id:
            return super().record_attempt_output_validation(
                task_id,
                attempt_id=attempt_id,
                status=status,
                validation_receipt_path=validation_receipt_path,
                issues=issues,
                idempotency_key=idempotency_key,
            )
        attempt_id = _safe_id(attempt_id, field="attempt_id")
        normalized_status = str(status or "").strip().lower()
        normalized_issues = sorted(set(str(item) for item in issues))
        if normalized_status not in {"pass", "fail"}:
            raise ValueError("output validation status must be pass or fail")
        if (normalized_status == "pass" and normalized_issues) or (
            normalized_status == "fail" and not normalized_issues
        ):
            raise ValueError("output validation status and issues disagree")
        expected_path = (
            self._expected_task_root
            / "attempt_logs"
            / attempt_id
            / "artifact_validation.yml"
        )
        if Path(os.path.abspath(validation_receipt_path)) != expected_path:
            raise ValueError("output validation receipt escaped the Attempt")
        receipt_bytes = self._read_task_file(
            ("attempt_logs", attempt_id, "artifact_validation.yml")
        )
        try:
            receipt = yaml.safe_load(receipt_bytes.decode("utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError("output validation receipt is invalid") from exc
        payload = {
            "status": normalized_status,
            "issues": normalized_issues,
            "receipt_path": (f"attempt_logs/{attempt_id}/artifact_validation.yml"),
            "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "output_sha256": str(receipt.get("output_sha256") or ""),
        }

        def validate(projection: dict[str, Any]) -> None:
            attempt = projection["attempts"].get(attempt_id)
            if attempt is None or attempt.get("status") != "succeeded":
                raise InvalidTransition(
                    "output validation requires a succeeded Attempt"
                )
            if attempt.get("output_validation") is not None:
                raise InvalidTransition("Attempt output is already validated")
            if payload["output_sha256"] != (attempt.get("outcome") or {}).get(
                "output_sha256"
            ):
                raise InvalidTransition(
                    "output validation is not bound to the Attempt output"
                )
            if any(
                (
                    receipt.get("schema_version") != "protocol-artifact-validation/v1",
                    receipt.get("status") != normalized_status,
                    receipt.get("task_id") != task_id,
                    receipt.get("attempt_id") != attempt_id,
                    sorted(set(str(item) for item in receipt.get("issues") or []))
                    != normalized_issues,
                )
            ):
                raise InvalidTransition(
                    "output validation receipt does not match its ledger event"
                )

        self._append_event(
            task_id=task_id,
            event_type="ATTEMPT_OUTPUT_VALIDATED",
            entity_type="attempt",
            entity_id=attempt_id,
            idempotency_key=idempotency_key,
            payload=payload,
            validate_projection=validate,
        )
        return self.rebuild_task(task_id)

    def record_artifact_version(
        self,
        task_id: str,
        *,
        artifact_id: str,
        version_id: str,
        attempt_id: str,
        path: Path,
        media_type: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if _safe_id(task_id, field="task_id") != self._anchored_task_id:
            return super().record_artifact_version(
                task_id,
                artifact_id=artifact_id,
                version_id=version_id,
                attempt_id=attempt_id,
                path=path,
                media_type=media_type,
                idempotency_key=idempotency_key,
            )
        artifact_id = _safe_id(artifact_id, field="artifact_id")
        version_id = _safe_id(version_id, field="version_id")
        attempt_id = _safe_id(attempt_id, field="attempt_id")
        normalized_media_type = _nonempty(media_type, field="media_type")
        source = Path(os.path.abspath(path))
        expected_parent = self._expected_task_root / "artifacts" / "staging"
        if source.parent != expected_parent or not source.suffix:
            raise ValueError("artifact source escaped managed imagegen staging")
        source_parts = ("artifacts", "staging", source.name)
        content = self._read_task_file(source_parts)
        content_sha256 = hashlib.sha256(content).hexdigest()
        destination_parts = (
            "artifacts",
            "versions",
            version_id,
            f"payload{source.suffix}",
        )
        payload = {
            "artifact_id": artifact_id,
            "attempt_id": attempt_id,
            "source_path": "/".join(source_parts),
            "path": "/".join(destination_parts),
            "media_type": normalized_media_type,
            "size_bytes": len(content),
            "sha256": content_sha256,
        }

        def validate(projection: dict[str, Any]) -> None:
            attempt = projection["attempts"].get(attempt_id)
            if attempt is None or attempt.get("status") != "succeeded":
                raise InvalidTransition(
                    "artifacts require a succeeded producer Attempt"
                )
            if (
                isinstance(projection["task"].get("compiled_protocol"), dict)
                and (attempt.get("output_validation") or {}).get("status") != "pass"
            ):
                raise InvalidTransition(
                    "protocol artifacts require passed output validation"
                )
            if version_id in projection["artifacts"]:
                raise InvalidTransition("artifact version already exists")
            current = self._read_task_file(source_parts)
            if hashlib.sha256(current).hexdigest() != content_sha256:
                raise InvalidTransition(
                    "artifact source changed while recording its version"
                )
            _write_task_file(
                self._task_descriptor,
                destination_parts[:-1],
                destination_parts[-1],
                current,
            )

        self._append_event(
            task_id=task_id,
            event_type="ARTIFACT_VERSION_RECORDED",
            entity_type="artifact_version",
            entity_id=version_id,
            idempotency_key=idempotency_key,
            payload=payload,
            validate_projection=validate,
        )
        return self.rebuild_task(task_id)

    def close(self) -> None:
        if self._task_descriptor >= 0:
            os.close(self._task_descriptor)
            self._task_descriptor = -1
        if self._runtime_descriptor >= 0:
            os.close(self._runtime_descriptor)
            self._runtime_descriptor = -1

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass


def ingest_managed_visual_identity_reference(
    agentlab_root: Path,
    *,
    pack: Mapping[str, Any],
    pack_path: Path,
    card_id: str,
    image_path: Path,
    attestation_path: Path,
) -> dict[str, Any]:
    """Import one signed Codex image result through a real Runtime-v2 Attempt."""

    root = Path(agentlab_root).resolve(strict=True)
    require_current_visual_detail_card_pack(pack, operation="managed imagegen ingest")
    provenance = validate_visual_pack_runtime_provenance(root, pack, pack_path)
    card = next(
        (
            item
            for item in pack.get("cards") or []
            if isinstance(item, Mapping) and item.get("card_id") == card_id
        ),
        None,
    )
    if card is None:
        raise ValueError(f"unknown visual card: {card_id}")
    raw_image = Path(image_path)
    if raw_image.is_symlink():
        raise ValueError("managed imagegen result may not be a symlink")
    image = raw_image.resolve(strict=True)
    if not image.is_file():
        raise ValueError("managed imagegen result must be a regular file")
    image_bytes = image.read_bytes()
    media_type, suffix = _image_media_type(image_bytes)
    image_sha256 = hashlib.sha256(image_bytes).hexdigest()

    raw_attestation = Path(attestation_path)
    if raw_attestation.is_symlink():
        raise ValueError("managed imagegen attestation may not be a symlink")
    try:
        attestation = (
            yaml.safe_load(
                raw_attestation.resolve(strict=True).read_text(encoding="utf-8")
            )
            or {}
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("managed imagegen attestation is unreadable") from exc
    signed_payload = (
        attestation.get("signed_payload") if isinstance(attestation, Mapping) else None
    )
    if not isinstance(signed_payload, Mapping):
        raise ValueError("managed imagegen signed payload is missing")

    project = _safe_id(pack.get("project"), field="project")
    reference_task_id = visual_reference_task_id(pack, card_id)
    attempt_id = "attempt-generation-001"
    version_id = _safe_id(
        signed_payload.get("artifact_version_id"),
        field="artifact_version_id",
    )
    expected_payload = {
        "schema_version": "narrative-visual-managed-imagegen-attestation-payload/v1",
        "action": "attest_codex_managed_imagegen_result",
        "tool": "image_gen.imagegen",
        "project": project,
        "task_id": reference_task_id,
        "attempt_id": attempt_id,
        "artifact_version_id": version_id,
        "card_id": card_id,
        "prompt_sha256": card["identity_reference"]["prompt_sha256"],
        "asset_sha256": image_sha256,
        "session_id": _nonempty(signed_payload.get("session_id"), field="session_id"),
        "selected_provider": _safe_id(
            signed_payload.get("selected_provider"),
            field="selected_provider",
        ),
        "selected_model_id": _nonempty(
            signed_payload.get("selected_model_id"),
            field="selected_model_id",
        ),
        "tool_result_id": _safe_id(
            signed_payload.get("tool_result_id"),
            field="tool_result_id",
        ),
    }
    validate_managed_imagegen_attestation(
        root,
        attestation,
        expected_payload=expected_payload,
    )

    generation_profile = resolve_visual_stage_contracts(root)["generation"]
    task_facts = {
        "kind": "visual_identity_reference_build",
        "scope": "single_asset",
        "target_count": 1,
        "canon_impact": "none",
        "risk_flags": [],
        "project": project,
        "source_visual_task_id": str(pack["task_id"]),
        "source_visual_pack_version_id": provenance["visual_pack_version_id"],
        "source_visual_pack_sha256": str(pack["pack_sha256"]),
        "card_id": card_id,
        "identity_reference_prompt_sha256": str(
            card["identity_reference"]["prompt_sha256"]
        ),
    }
    compile_production_protocol(
        root,
        protocol_ref="narrative.visual.reference.v1",
        task_facts=task_facts,
    )
    base_runtime = TaskRuntime(root, project=project)
    lexical_task_root = base_runtime._task_dir(reference_task_id)
    _assert_no_symlink_ancestry(lexical_task_root, root)
    task_descriptor = _open_task_subdirectory(root, lexical_task_root, ())
    runtime = _AnchoredTaskRuntime(
        root,
        project=project,
        task_id=reference_task_id,
        task_descriptor=task_descriptor,
        expected_task_root=lexical_task_root,
    )
    task_root = runtime._task_dir(reference_task_id)
    if runtime._read_ledger_text(reference_task_id) is None:
        runtime.create_task(
            task_id=reference_task_id,
            title=f"Generate and review identity reference for {card_id}",
            user_goal="Bind one managed identity image to independent review evidence.",
            protocol_ref="narrative.visual.reference.v1",
            input_profile=task_facts,
            idempotency_key="create-visual-reference-task",
        )
    projection = ProductionProtocolRunner(
        root,
        project=project,
        runtime=runtime,
    ).prepare(reference_task_id)
    if projection["task"].get("input_profile") != task_facts:
        raise InvalidTransition("visual reference Task facts drifted")
    was_complete = (
        version_id in projection["artifacts"]
        and "managed_imagegen_attested" in projection["protocol_gates"]
        and projection["work_items"]["generation"]["status"] == "accepted"
    )

    if projection["task"]["status"] == "created":
        projection = runtime.transition_task(
            reference_task_id,
            status="ready",
            idempotency_key="visual-reference-ready",
        )
    if projection["task"]["status"] == "ready":
        projection = runtime.transition_task(
            reference_task_id,
            status="running",
            idempotency_key="visual-reference-running",
        )
    if projection["work_items"]["generation"]["status"] == "ready":
        projection = runtime.transition_work_item(
            reference_task_id,
            work_item_id="generation",
            status="running",
            idempotency_key="visual-generation-running",
        )

    classification = projection["task"]["input_classification"]
    execution_contract = {
        "role": "ArtifactProducer",
        "executor_type": "cli_agent",
        "invocation_contract": generation_profile["invocation_contract"],
        "model_key": generation_profile["model_key"],
        "model_id": expected_payload["selected_model_id"],
        "runtime_provider": expected_payload["selected_provider"],
        "agent_model_profile": projection["work_items"]["generation"][
            "agent_model_profile"
        ],
        "input_tier": classification["tier"],
        "route": classification["route"],
        "managed_tool": "image_gen.imagegen",
    }
    attempt = projection["attempts"].get(attempt_id)
    if attempt is None:
        projection = runtime.schedule_attempt(
            reference_task_id,
            work_item_id="generation",
            attempt_id=attempt_id,
            worker=generation_profile["worker"],
            provider=expected_payload["selected_provider"],
            execution_contract=execution_contract,
            idempotency_key="schedule-managed-visual-generation",
        )
        attempt = projection["attempts"][attempt_id]
    if (
        attempt.get("work_item_id") != "generation"
        or attempt.get("worker") != generation_profile["worker"]
        or attempt.get("provider") != expected_payload["selected_provider"]
        or attempt.get("execution_contract") != execution_contract
    ):
        raise InvalidTransition("managed imagegen Attempt binding drifted")
    if attempt["status"] == "scheduled":
        projection = runtime.transition_attempt(
            reference_task_id,
            attempt_id=attempt_id,
            status="running",
            idempotency_key="run-managed-visual-generation",
        )
        attempt = projection["attempts"][attempt_id]
    if attempt["status"] not in {"running", "succeeded"}:
        raise InvalidTransition("managed imagegen Attempt is not recoverable")

    attempt_root = task_root / "attempt_logs" / attempt_id
    output = attempt_root / "output.md"
    output_content = (
        f"visual_identity_reference: {version_id}\nasset_sha256: {image_sha256}\n"
    )
    _write_task_file(
        task_descriptor,
        ("attempt_logs", attempt_id),
        "output.md",
        output_content.encode("utf-8"),
    )
    model_receipt = attempt_root / "model_execution_receipt.yml"
    model_document = {
        "status": "pass",
        "role": "ArtifactProducer",
        "worker": generation_profile["worker"],
        "invocation_contract": generation_profile["invocation_contract"],
        "selected_provider": expected_payload["selected_provider"],
        "selected_model_key": generation_profile["model_key"],
        "selected_model_id": expected_payload["selected_model_id"],
        "session_id": expected_payload["session_id"],
        "profile_binding_verified": True,
        "command_binding_verified": True,
        "provider_model_binding_verified": True,
        "provider_process_started": True,
        "fallback_detected": False,
        "exit_code": 0,
        "issues": [],
        "execution_surface": "codex_managed_imagegen",
        "managed_tool": "image_gen.imagegen",
        "generated_asset_sha256": image_sha256,
        "managed_tool_attestation": dict(attestation),
    }
    _write_task_file(
        task_descriptor,
        ("attempt_logs", attempt_id),
        "model_execution_receipt.yml",
        _yaml_bytes(model_document),
    )
    model_sha256 = hashlib.sha256(
        runtime._read_task_file(
            ("attempt_logs", attempt_id, "model_execution_receipt.yml")
        )
    ).hexdigest()
    attempt_receipt = attempt_root / "attempt_receipt.yml"
    attempt_document = {
        "schema_version": "task-runtime-role-attempt-receipt/v1",
        "project": project,
        "task_id": reference_task_id,
        "work_item_id": "generation",
        "attempt_id": attempt_id,
        "role": "ArtifactProducer",
        "worker": generation_profile["worker"],
        "provider": expected_payload["selected_provider"],
        "status": "pass",
        "output_path": output.relative_to(task_root).as_posix(),
        "output_sha256": hashlib.sha256(
            runtime._read_task_file(("attempt_logs", attempt_id, "output.md"))
        ).hexdigest(),
        "sealed_sources": [],
        "model_execution": {
            "path": model_receipt.relative_to(task_root).as_posix(),
            "sha256": model_sha256,
            "cli_agent": generation_profile["worker"],
            "model_key": generation_profile["model_key"],
            "model_id": expected_payload["selected_model_id"],
            "runtime_provider": expected_payload["selected_provider"],
            "executor_provider": "agentlab-cli-executor",
        },
    }
    _write_task_file(
        task_descriptor,
        ("attempt_logs", attempt_id),
        "attempt_receipt.yml",
        _yaml_bytes(attempt_document),
    )
    attempt_receipt_sha256 = hashlib.sha256(
        runtime._read_task_file(("attempt_logs", attempt_id, "attempt_receipt.yml"))
    ).hexdigest()
    if attempt["status"] == "running":
        projection = runtime._transition_executed_attempt(
            reference_task_id,
            attempt_id=attempt_id,
            status="succeeded",
            outcome={
                "execution_origin": "role_attempt_executor",
                "receipt_path": attempt_receipt.relative_to(task_root).as_posix(),
                "receipt_sha256": attempt_receipt_sha256,
                "output_sha256": hashlib.sha256(
                    runtime._read_task_file(("attempt_logs", attempt_id, "output.md"))
                ).hexdigest(),
            },
            idempotency_key="complete-managed-visual-generation",
        )
    else:
        runtime.verify_attempt_execution_receipt(reference_task_id, attempt_id)
        projection = runtime.load_task(reference_task_id)
    validation_receipt = attempt_root / "artifact_validation.yml"
    validation_document = {
        "schema_version": "protocol-artifact-validation/v1",
        "status": "pass",
        "task_id": reference_task_id,
        "attempt_id": attempt_id,
        "output_sha256": hashlib.sha256(
            runtime._read_task_file(("attempt_logs", attempt_id, "output.md"))
        ).hexdigest(),
        "issues": [],
    }
    _write_task_file(
        task_descriptor,
        ("attempt_logs", attempt_id),
        "artifact_validation.yml",
        _yaml_bytes(validation_document),
    )
    if projection["attempts"][attempt_id].get("output_validation") is None:
        projection = runtime.record_attempt_output_validation(
            reference_task_id,
            attempt_id=attempt_id,
            status="pass",
            validation_receipt_path=validation_receipt,
            issues=[],
            idempotency_key="validate-managed-visual-generation",
        )
    elif (
        projection["attempts"][attempt_id]["output_validation"].get("status") != "pass"
    ):
        raise InvalidTransition("managed imagegen output validation did not pass")
    staging = task_root / "artifacts" / "staging" / f"{version_id}{suffix}"
    existing = projection["artifacts"].get(version_id)
    if existing is None:
        _write_task_file(
            task_descriptor,
            ("artifacts", "staging"),
            staging.name,
            image_bytes,
        )
        projection = runtime.record_artifact_version(
            reference_task_id,
            artifact_id="visual_identity_reference",
            version_id=version_id,
            attempt_id=attempt_id,
            path=staging,
            media_type=media_type,
            idempotency_key="record-managed-visual-reference",
        )
    else:
        immutable_parts = tuple(Path(str(existing.get("path") or "")).parts)
        immutable_bytes = runtime._read_task_file(immutable_parts)
        if (
            existing.get("artifact_id") != "visual_identity_reference"
            or existing.get("producer_attempt_id") != attempt_id
            or existing.get("sha256") != image_sha256
            or existing.get("media_type") != media_type
            or hashlib.sha256(immutable_bytes).hexdigest() != image_sha256
            or immutable_bytes != image_bytes
        ):
            raise InvalidTransition("managed imagegen ArtifactVersion drifted")
    artifact = projection["artifacts"][version_id]
    subject_digest = _canonical_sha256(
        {"visual_identity_reference": artifact["sha256"]}
    )
    gate = projection["protocol_gates"].get("managed_imagegen_attested")
    if gate is None:
        projection = runtime.record_protocol_gate(
            reference_task_id,
            gate_id="managed_imagegen_attested",
            work_item_id="generation",
            evidence_kind="automated",
            evidence_sha256=subject_digest,
            attempt_id=attempt_id,
            subject_version_ids=[version_id],
            actor="agentlab-managed-imagegen-ingest",
            idempotency_key="record-managed-imagegen-attested-gate",
        )
    elif any(
        (
            gate.get("status") != "pass",
            gate.get("evidence_kind") != "automated",
            gate.get("evidence_sha256") != subject_digest,
            gate.get("attempt_id") != attempt_id,
            gate.get("subject_version_ids") != [version_id],
        )
    ):
        raise InvalidTransition("managed imagegen protocol gate drifted")
    if projection["work_items"]["generation"]["status"] != "accepted":
        projection = runtime.transition_work_item(
            reference_task_id,
            work_item_id="generation",
            status="accepted",
            idempotency_key="accept-managed-visual-generation",
        )
    result = {
        "status": "already_ingested" if was_complete else "ingested",
        "task_id": reference_task_id,
        "attempt_id": attempt_id,
        "artifact_version_id": version_id,
        "artifact": dict(projection["artifacts"][version_id]),
        "managed_imagegen_gate": dict(
            projection["protocol_gates"]["managed_imagegen_attested"]
        ),
        "projection": projection,
    }
    runtime.close()
    return result
