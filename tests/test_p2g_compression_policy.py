from agent_runtime.context_governance.compression_policy import compression_decision


def test_code_config_tests_no_lossy():
    for kind in ["code", "config", "tests"]:
        d = compression_decision(kind)
        assert d["lossy_allowed"] is False
        assert d["compression_safety"] in {"no_lossy_compression", "extractive_only"}


def test_legal_exact_extractive_only():
    d = compression_decision("legal", exact_required=True)
    assert d["lossy_allowed"] is False
    assert "C2_extractive" in d["allowed_levels"]


def test_narrative_web_lossy_and_data_externalized():
    assert compression_decision("narrative")["lossy_allowed"] is True
    assert compression_decision("web")["lossy_allowed"] is True
    data = compression_decision("data")
    assert data["lossy_allowed"] is False
    assert "C6_externalize_and_drilldown" in data["allowed_levels"]
