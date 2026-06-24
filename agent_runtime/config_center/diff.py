"""Config diff engine for M2-5 Config Center.

Compares two config snapshots and produces annotated diff records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime.config_center.loader import _deep_merge, resolve_merged_config
from agent_runtime.config_center.resolver import resolve_all_keys
from agent_runtime.config_center.schema import ConfigLayer, ConfigValue


@dataclass
class DiffEntry:
    """A single config difference between two snapshots."""

    key: str
    base_value: Any = None
    override_value: Any = None
    diff_kind: str = "changed"  # added, removed, changed, unchanged
    base_layer: str = ""
    override_layer: str = ""

    @property
    def has_diff(self) -> bool:
        return self.diff_kind != "unchanged"


@dataclass
class ConfigDiff:
    """Full diff result between two config snapshots."""

    entries: list[DiffEntry] = field(default_factory=list)
    base_label: str = "base"
    override_label: str = "override"

    @property
    def changed(self) -> list[DiffEntry]:
        return [e for e in self.entries if e.has_diff]


def diff_configs(
    base: dict[str, ConfigValue],
    override: dict[str, ConfigValue],
    *,
    base_label: str = "base",
    override_label: str = "override",
) -> ConfigDiff:
    """Compare two resolved config snapshots.

    Produces a diff showing what changed between them.
    """
    all_keys = sorted(set(base.keys()) | set(override.keys()))
    entries: list[DiffEntry] = []

    for key in all_keys:
        base_cv = base.get(key)
        override_cv = override.get(key)

        if base_cv is None and override_cv is not None:
            entries.append(
                DiffEntry(
                    key=key,
                    override_value=override_cv.value,
                    diff_kind="added",
                    override_layer=override_cv.source_label,
                )
            )
        elif base_cv is not None and override_cv is None:
            entries.append(
                DiffEntry(
                    key=key,
                    base_value=base_cv.value,
                    diff_kind="removed",
                    base_layer=base_cv.source_label,
                )
            )
        elif base_cv is not None and override_cv is not None:
            if base_cv.value != override_cv.value:
                entries.append(
                    DiffEntry(
                        key=key,
                        base_value=base_cv.value,
                        override_value=override_cv.value,
                        diff_kind="changed",
                        base_layer=base_cv.source_label,
                        override_layer=override_cv.source_label,
                    )
                )
            else:
                entries.append(
                    DiffEntry(
                        key=key,
                        base_value=base_cv.value,
                        diff_kind="unchanged",
                        base_layer=base_cv.source_label,
                    )
                )

    return ConfigDiff(entries=entries, base_label=base_label, override_label=override_label)


def project_diff(
    agentlab_root: Path,
    project_name: str,
) -> ConfigDiff:
    """Diff a project's config overrides against the base (no-project) config."""
    base, _, _ = resolve_all_keys(agentlab_root, project_name=None)
    override, _, _ = resolve_all_keys(agentlab_root, project_name=project_name)
    return diff_configs(base, override, base_label="base", override_label=f"project:{project_name}")
