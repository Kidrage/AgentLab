from __future__ import annotations
from pathlib import Path
from typing import Iterable

from agent_runtime.long_project_governance import build_project_governance_pack, infer_project_root_from_run_dir

from ..schemas import ContextBudget, ContextProfile
from .base import evidence, external, make_pack, omitted, section, source_ref


class NarrativePacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        raw = source_ref(run_dir, "user_request.md")
        project_root = infer_project_root_from_run_dir(run_dir)
        agentlab_root = _infer_agentlab_root(project_root)
        governance = (
            build_project_governance_pack(agentlab_root, "longform_text_project", project_root)
            if agentlab_root
            else {}
        )
        setting_refs = _collect(project_root, ["设定/**/*.md"], limit=12)
        outline_refs = _collect(project_root, ["大纲/**/*.md"], limit=8)
        brain_refs = _collect(project_root, ["project_brain/*.yml"], limit=12)
        state_refs = _collect(project_root, ["project_brain/project_fact_snapshot.yml", "project_brain/project_state_contract.yml"], limit=4)
        chapter_refs = _collect(project_root, ["正文/第0*.md"], limit=30)

        sections = [
            section(
                "project_fact_state_refs",
                "Project Fact State References",
                _render_refs("Machine-readable project fact snapshot and state contract", state_refs),
                state_refs,
            ),
            section(
                "project_bible_refs",
                "Project Bible References",
                _render_refs("Stable setting, role, world, faction, and relationship files", setting_refs),
                setting_refs,
            ),
            section(
                "outline_and_scene_refs",
                "Outline And Scene References",
                _render_refs("Outline and next-batch planning files", outline_refs + brain_refs),
                outline_refs + brain_refs,
            ),
            section(
                "chapter_ledger_refs",
                "Chapter Ledger References",
                _render_chapter_refs(project_root, chapter_refs),
                chapter_refs,
            ),
            section(
                "long_project_gaps",
                "Long Project Gap Cards",
                _render_gap_cards(governance.get("gap_cards") or []),
            ),
        ]
        evidence_refs = [evidence(raw, "narrative_source")]
        evidence_refs.extend(evidence(ref, "must_read_artifact") for ref in governance.get("must_read_artifacts") or [])
        warnings = []
        if governance.get("missing_facts"):
            warnings.append("narrative context has missing long-project artifacts; see long_project_gaps")
        return make_pack(
            profile,
            budget,
            sections,
            omitted_sections=[omitted("Full prose omitted; drill down by chapter/source offset.", raw)],
            externalized=[external(raw, "raw_input", "Full narrative remains externalized.")],
            evidence_refs=evidence_refs,
            warnings=warnings,
        )


def _infer_agentlab_root(project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    for parent in [project_root, *project_root.parents]:
        if (parent / "config" / "long_project_governance.yml").exists():
            return parent
    return None


def _collect(project_root: Path | None, patterns: Iterable[str], limit: int) -> list[str]:
    if project_root is None or not project_root.exists():
        return []
    found: list[str] = []
    for pattern in patterns:
        for path in sorted(project_root.glob(pattern)):
            if len(found) >= limit:
                return found
            if path.is_file():
                found.append(str(path.relative_to(project_root)))
    return found


def _render_refs(intro: str, refs: list[str]) -> str:
    if not refs:
        return f"{intro}: none found. Create the missing artifact before execution dispatch."
    return "\n".join([f"{intro}:", *[f"- {ref}" for ref in refs]])


def _render_chapter_refs(project_root: Path | None, refs: list[str]) -> str:
    if not refs:
        return "No chapter files found. Drafting requires chapter cards or previous chapter summaries first."
    lines = ["Existing chapter files to preserve continuity:"]
    for ref in refs[:30]:
        path = project_root / ref if project_root else None
        title = ref
        preview = _first_nonempty_line(path) if path else ""
        lines.append(f"- {title}: {preview}" if preview else f"- {title}")
    return "\n".join(lines)


def _render_gap_cards(gap_cards: list[dict]) -> str:
    if not gap_cards:
        return "No blocking long-project gaps detected from configured governance artifacts."
    lines = ["Resolve or explicitly defer these gaps before executor dispatch:"]
    for card in gap_cards:
        lines.append(f"- {card.get('gap_id')}: {card.get('question')}")
    return "\n".join(lines)


def _first_nonempty_line(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip().lstrip("#").strip()
            if text:
                return text[:160]
    except UnicodeDecodeError:
        return ""
    return ""
