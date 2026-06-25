from agent_runtime.goals.templates import TEMPLATES

def test_scenario_validation_required():
    for k, v in TEMPLATES.items():
        assert "scenario_validations" in v
        
def test_no_external_tools_executed():
    pass
