from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "activate_250_runtime.sh"


def test_250_runtime_activation_script_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)


def test_250_runtime_activation_help_documents_status_only() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--status-only" in result.stdout
    assert "read-only remote activation audit" in result.stdout
    assert "No secrets are stored in this script" in result.stdout


def test_250_runtime_activation_script_does_not_embed_live_secrets() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    forbidden_patterns = [
        r"AQ\.",
        r"bbe166",
        r"ddns-gjy",
        r"CLASH_SUBSCRIBE_URL=https://",
        r"GEMINI_API_KEY=[A-Za-z0-9_.-]{12,}",
        r"GOOGLE_API_KEY=[A-Za-z0-9_.-]{12,}",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, text), f"script embeds secret-like pattern: {pattern}"


def test_250_runtime_status_only_runs_before_secret_prompts() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    status_pos = text.index('if [[ "$STATUS_ONLY" == "1" ]]')
    clash_prompt_pos = text.index("Clash subscription URL:")
    gemini_prompt_pos = text.index("Gemini API key:")

    assert status_pos < clash_prompt_pos
    assert status_pos < gemini_prompt_pos
    assert "secret_key_presence" in text[status_pos:clash_prompt_pos]
