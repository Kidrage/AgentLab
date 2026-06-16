from agent_runtime.context_governance.context_budget import build_context_budget
from agent_runtime.context_governance.information_profiler import build_context_profile


def test_small_task_budget_less_than_coding():
    small = build_context_budget(build_context_profile("t", "hello"), "hello")
    coding = build_context_budget(build_context_profile("t", "github repo src/ tests/ refactor"), "x" * 2000)
    assert small.max_input_tokens < coding.max_input_tokens


def test_repo_web_data_limits_and_savings_ratio():
    repo = build_context_budget(build_context_profile("t", "github repo src/ tests/"), "x" * 1000)
    web = build_context_budget(build_context_profile("t", "search latest web docs pricing"), "x" * 1000)
    data = build_context_budget(build_context_profile("t", "csv table dataframe"), "x" * 1000)
    assert repo.max_files >= 12
    assert web.max_sources <= 8
    assert data.budget_policy == "data_analysis_task"
    for b in [repo, web, data]:
        assert 0 <= b.as_dict()["estimated_savings_ratio"] <= 1
