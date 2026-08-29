"""Deterministic project Agent team proposals from broad project goals."""

from __future__ import annotations

from agent_runtime.project_truth import CanonicalCommitReceipt

from .models import AgentManifest, AgentTeamProposal
from .registry import ProjectAgentRegistry


_TEAMS: dict[str, tuple[tuple[str, str, str, tuple[str, ...]], ...]] = {
    "narrative": (
        ("supervisor", "Narrative Supervisor Agent", "project_manager", ("plan.*",)),
        ("world", "World Agent", "world_architect", ("world.*",)),
        ("character", "Character Agent", "character_architect", ("character.*",)),
        ("timeline", "Timeline Agent", "timeline_guardian", ("timeline.*",)),
        ("plot", "Plot Agent", "plot_architect", ("plot.*",)),
        ("foreshadow", "Foreshadow Agent", "foreshadow_guardian", ("foreshadow.*",)),
        (
            "blueprint_producer",
            "Blueprint Producer Agent",
            "artifact_producer",
            ("blueprint.*",),
        ),
        ("writer", "Writer Agent", "writer", ("manuscript.*",)),
        ("checker", "Checker Agent", "consistency_checker", ()),
        ("reviewer", "Reviewer Agent", "quality_reviewer", ()),
    ),
    "game": (
        ("world", "World Agent", "world_designer", ("world.*",)),
        ("character", "Character Agent", "character_designer", ("character.*",)),
        ("quest", "Quest Agent", "quest_designer", ("quest.*",)),
        ("balance", "Balance Agent", "balance_designer", ("balance.*",)),
        ("reviewer", "Reviewer Agent", "quality_reviewer", ()),
    ),
    "software": (
        ("architecture", "Architecture Agent", "software_architect", ("architecture.*",)),
        ("coder", "Coder Agent", "coder", ("source.*",)),
        ("test", "Test Agent", "test_engineer", ("tests.*",)),
        ("security", "Security Agent", "security_reviewer", ("security.*",)),
        ("reviewer", "Reviewer Agent", "quality_reviewer", ()),
    ),
    "audio": (
        ("dsp", "DSP Agent", "dsp_engineer", ("audio.dsp.*",)),
        ("mix", "Mix Agent", "mix_engineer", ("audio.mix.*",)),
        ("listener_qa", "Listener QA Agent", "listener_qa", ("audio.qa.*",)),
        ("reviewer", "Reviewer Agent", "quality_reviewer", ()),
    ),
    "generic": (
        ("project_manager", "Project Manager Agent", "project_manager", ("plan.*",)),
        ("domain_expert", "Domain Expert Agent", "domain_expert", ("domain.*",)),
        ("producer", "Producer Agent", "artifact_producer", ("artifact.*",)),
        ("reviewer", "Reviewer Agent", "quality_reviewer", ()),
    ),
}

_NARRATIVE_SPECIALISTS = (
    (
        "mystery_keeper",
        "Mystery Keeper",
        "mystery_keeper",
        ("mystery.*",),
        ("mystery", "suspense", "secret", "谜团", "悬念", "秘密", "信息差"),
    ),
    (
        "style_guardian",
        "Style Guardian",
        "style_guardian",
        ("style.*",),
        (
            "style",
            "aesthetic",
            "atmosphere",
            "adult",
            "sensual",
            "风格",
            "美学",
            "氛围",
            "成人",
            "感官",
        ),
    ),
)

_RUNTIME_ROLE_BY_PROJECT_ROLE = {
    "artifact_producer": "ArtifactProducer",
    "coder": "Coder",
    "consistency_checker": "Verifier",
    "listener_qa": "Reviewer",
    "project_manager": "Supervisor",
    "quality_reviewer": "Reviewer",
    "security_reviewer": "Reviewer",
    "test_engineer": "Verifier",
    "writer": "Writer",
}


class ProjectAgentFactory:
    """Select a trusted generic team template without invoking a model."""

    def propose(self, prompt: str, *, project_id: str) -> AgentTeamProposal:
        domain = self._classify(prompt)
        templates = list(_TEAMS[domain])
        specialist_ids: list[str] = []
        if domain == "narrative":
            text = prompt.casefold()
            insert_at = next(
                index
                for index, template in enumerate(templates)
                if template[0] == "writer"
            )
            for agent_id, name, role, write_scope, keywords in (
                _NARRATIVE_SPECIALISTS
            ):
                if any(keyword in text for keyword in keywords):
                    templates.insert(
                        insert_at,
                        (agent_id, name, role, write_scope),
                    )
                    specialist_ids.append(agent_id)
                    insert_at += 1
        manifests = tuple(
            self._manifest(project_id, *template) for template in templates
        )
        rationale = f"Matched trusted {domain} project organization template."
        if specialist_ids:
            rationale = (
                f"{rationale} Added prompt-requested specialists: "
                f"{', '.join(specialist_ids)}."
            )
        return AgentTeamProposal(
            project_id=project_id,
            manifests=manifests,
            source="factory",
            requires_approval=True,
            rationale=rationale,
        )

    def create_team(
        self,
        registry: ProjectAgentRegistry,
        prompt: str,
        *,
        expected_snapshot_id: str,
        actor_id: str,
        approved: bool,
    ) -> CanonicalCommitReceipt:
        proposal = self.propose(
            prompt, project_id=registry.truth.current().project_id
        )
        return registry.register_many(
            proposal.manifests,
            expected_snapshot_id=expected_snapshot_id,
            actor_id=actor_id,
            source=proposal.source,
            approved=approved,
        )

    @staticmethod
    def _classify(prompt: str) -> str:
        text = prompt.casefold()
        if any(token in text for token in ("rpg", "game", "游戏", "任务设计", "数值设计")):
            return "game"
        if any(token in text for token in ("audio", "music", "mix", "音乐", "音频", "混音", "专辑")):
            return "audio"
        if any(
            token in text
            for token in (
                "code",
                "software",
                "service",
                "api",
                "web",
                "代码",
                "软件",
                "应用",
            )
        ):
            return "software"
        if any(token in text for token in ("novel", "story", "小说", "故事", "剧本")):
            return "narrative"
        return "generic"

    @staticmethod
    def _manifest(
        project_id: str,
        agent_id: str,
        name: str,
        role: str,
        write_scope: tuple[str, ...],
    ) -> AgentManifest:
        reviewer = role == "quality_reviewer"
        return AgentManifest(
            id=agent_id,
            name=name,
            version="1.0.0",
            role=role,
            description=f"Project-scoped {role.replace('_', ' ')}.",
            responsibilities=(f"Own {role.replace('_', ' ')} decisions.",),
            runtime_role=_RUNTIME_ROLE_BY_PROJECT_ROLE.get(
                role,
                "Researcher",
            ),
            read_scope=("*",),
            write_scope=write_scope,
            approval_scope=() if reviewer else write_scope,
            knowledge_binding={
                "namespace": f"agent.{project_id}.{agent_id}",
                "documents": (),
                "artifacts": (),
            },
            model_profile="balanced",
            tool_permission=("knowledge.read",),
            budget_profile="standard",
            status="active",
            acceptance_rules=("scope_contract_satisfied",),
            collaboration={"reviewed_by": () if reviewer else ("reviewer",)},
        )
