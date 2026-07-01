from agent_runtime.costs.model_cost_profile import load_model_cost_profiles
from agent_runtime.costs.executor_cost_profile import load_executor_cost_profiles
from agent_runtime.costs.worker_cost_profile import load_worker_cost_profiles

def test_load_model_profiles(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "model_cost_profiles.yml").write_text("models:\n  test_model:\n    input_usd_per_million_tokens: 1.0")
    profiles = load_model_cost_profiles(tmp_path)
    assert profiles["test_model"].input_usd_per_million_tokens == 1.0

def test_load_executor_profiles(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "executor_cost_profiles.yml").write_text("executors:\n  test_exec:\n    billing_mode: unknown")
    profiles = load_executor_cost_profiles(tmp_path)
    assert profiles["test_exec"].billing_mode == "unknown"

def test_load_worker_profiles(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "worker_cost_profiles.yml").write_text("workers:\n  test_worker:\n    role_markup: 2.0")
    profiles = load_worker_cost_profiles(tmp_path)
    assert profiles["test_worker"].role_markup == 2.0
