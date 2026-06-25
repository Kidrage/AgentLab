from agent_runtime.goals.storage import get_project_brain_dir, write_yaml, read_yaml

def test_project_brain_stores_artifacts(tmp_path):
    brain_dir = get_project_brain_dir(tmp_path, "ProjX")
    assert brain_dir.name == "project_brain"
    write_yaml(brain_dir / "test.yml", {"hello": "world"})
    data = read_yaml(brain_dir / "test.yml")
    assert data["hello"] == "world"
