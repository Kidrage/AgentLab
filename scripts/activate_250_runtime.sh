#!/usr/bin/env bash
set -euo pipefail

REMOTE="${AGENTLAB_250_REMOTE:-admin@10.147.17.250}"
REMOTE_ROOT="${AGENTLAB_250_ROOT:-/home/admin/AgentLab}"
STATUS_ONLY=0

usage() {
  cat <<'EOF'
Usage: scripts/activate_250_runtime.sh [--remote user@host] [--root /path/to/AgentLab] [--status-only]

Activates the 250 AgentLab runtime after explicit secret-write approval.
No secrets are stored in this script. It prompts for:

- Clash/mihomo subscription URL
- Gemini API key

The secrets are sent over SSH and written only to private files on the remote:

- ~/.agentlab_secrets/env
- ~/.gemini/.env
- <AgentLab>/agent_runtime/.env

Use --status-only for a read-only remote activation audit.

EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      REMOTE="$2"
      shift 2
      ;;
    --root)
      REMOTE_ROOT="$2"
      shift 2
      ;;
    --status-only)
      STATUS_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$STATUS_ONLY" == "1" ]]; then
  ssh "$REMOTE" "REMOTE_ROOT='$REMOTE_ROOT' python3.11 -" <<'PY'
import json
import os
import pathlib
import subprocess

remote_root = pathlib.Path(os.environ["REMOTE_ROOT"])

def run(cmd: list[str], *, cwd: pathlib.Path | None = None, timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip()
    except Exception as exc:
        return 255, f"{type(exc).__name__}: {exc}"

def command_version(command: str, *args: str) -> dict[str, object]:
    code, path = run(["bash", "-lc", f"command -v {command}"])
    if code != 0:
        return {"present": False}
    version_code, version = run([command, *args])
    return {"present": True, "path": path.splitlines()[-1], "version": version.splitlines()[:2], "version_code": version_code}

def env_keys(path: pathlib.Path, keys: list[str]) -> dict[str, bool]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    present = {}
    for key in keys:
        present[key] = any(line.startswith(f"{key}=") for line in text.splitlines())
    return present

head_code, head = run(["git", "rev-parse", "HEAD"], cwd=remote_root)
status_code, status = run(["git", "status", "--short"], cwd=remote_root)
doctor_code, doctor = run(["bash", "-lc", "./agentlab.sh models doctor"], cwd=remote_root, timeout=60)

results = {
    "remote_root": str(remote_root),
    "git": {
        "head": head if head_code == 0 else None,
        "status_short": status.splitlines(),
    },
    "cli": {
        "hermes": command_version("hermes", "--version"),
        "gemini": command_version("gemini", "--version"),
        "qwen": command_version("qwen", "--version"),
        "agy": command_version("agy", "--version"),
        "claude": command_version("claude", "--version"),
        "codex": command_version("codex", "--version"),
        "bl": command_version("bl", "--version"),
        "openclaw": command_version("openclaw", "--version"),
        "mihomod": command_version("mihomod", "--help"),
        "mihomo": command_version("mihomo", "-v"),
    },
    "services": {
        "mihomo_user_systemd": run(["bash", "-lc", "systemctl --user is-active mihomo 2>/dev/null || true"])[1] or "unknown",
        "clash_user_systemd": run(["bash", "-lc", "systemctl --user is-active clash 2>/dev/null || true"])[1] or "unknown",
    },
    "proxy_env_keys": sorted([key for key in os.environ if "proxy" in key.lower()]),
    "secret_key_presence": {
        "~/.agentlab_secrets/env": env_keys(pathlib.Path.home() / ".agentlab_secrets/env", ["CLASH_SUBSCRIBE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY"]),
        "~/.gemini/.env": env_keys(pathlib.Path.home() / ".gemini/.env", ["GEMINI_API_KEY", "GOOGLE_API_KEY"]),
        "agent_runtime/.env": env_keys(remote_root / "agent_runtime/.env", ["CLASH_SUBSCRIBE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY"]),
    },
    "models_doctor": {
        "code": doctor_code,
        "status_line": next((line for line in doctor.splitlines() if line.startswith("status:")), None),
        "issue_count_line": next((line for line in doctor.splitlines() if line.startswith("issue_count:")), None),
    },
}

print(json.dumps(results, ensure_ascii=False, indent=2))
PY
  exit 0
fi

if [[ -z "${CLASH_SUBSCRIBE_URL:-}" ]]; then
  read -r -s -p "Clash subscription URL: " CLASH_SUBSCRIBE_URL
  echo
fi
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  read -r -s -p "Gemini API key: " GEMINI_API_KEY
  echo
fi

if [[ -z "$CLASH_SUBSCRIBE_URL" || -z "$GEMINI_API_KEY" ]]; then
  echo "Both CLASH_SUBSCRIBE_URL and GEMINI_API_KEY are required." >&2
  exit 2
fi

payload="$(
  SUB="$CLASH_SUBSCRIBE_URL" KEY="$GEMINI_API_KEY" python3 - <<'PY'
import base64
import json
import os

print(base64.b64encode(json.dumps({
    "clash_subscribe_url": os.environ["SUB"],
    "gemini_api_key": os.environ["KEY"],
}).encode()).decode())
PY
)"

ssh "$REMOTE" "cat > /tmp/agentlab_250_activate.py && chmod 700 /tmp/agentlab_250_activate.py" <<'PY'
import base64
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

remote_root = pathlib.Path(os.environ["REMOTE_ROOT"])
payload = json.loads(base64.b64decode(sys.stdin.read().strip()).decode())
sub_url = payload["clash_subscribe_url"]
gemini_key = payload["gemini_api_key"]

def merge_env(path: pathlib.Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    seen: set[str] = set()
    for line in existing:
        key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    path.chmod(0o600)

updates = {
    "CLASH_SUBSCRIBE_URL": sub_url,
    "GEMINI_API_KEY": gemini_key,
    "GOOGLE_API_KEY": gemini_key,
    "HERMES_INFERENCE_MODEL": "gemini/gemini-2.5-flash",
}
merge_env(pathlib.Path.home() / ".agentlab_secrets/env", updates)
merge_env(pathlib.Path.home() / ".gemini/.env", {"GEMINI_API_KEY": gemini_key, "GOOGLE_API_KEY": gemini_key})
merge_env(remote_root / "agent_runtime/.env", updates)

source_line = 'test -f "$HOME/.agentlab_secrets/env" && set -a && . "$HOME/.agentlab_secrets/env" && set +a'
for name in (".bashrc", ".zshrc"):
    profile = pathlib.Path.home() / name
    text = profile.read_text(encoding="utf-8") if profile.exists() else ""
    if source_line not in text:
        profile.write_text(text.rstrip() + "\n" + source_line + "\n", encoding="utf-8")

def run(cmd: list[str], *, timeout: int = 120, env: dict[str, str] | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env=env,
    )
    return proc.returncode, proc.stdout.strip()

base_env = os.environ.copy()
base_env.pop("HTTP_PROXY", None)
base_env.pop("HTTPS_PROXY", None)
base_env.pop("http_proxy", None)
base_env.pop("https_proxy", None)
base_env["GEMINI_API_KEY"] = gemini_key
base_env["GOOGLE_API_KEY"] = gemini_key

results: dict[str, object] = {"secret_files": "configured"}

code, out = run(["bash", "-lc", "command -v mihomod || npm install -g mihomod@0.2.0 >/dev/null && command -v mihomod"], env=base_env)
results["mihomod"] = {"code": code, "output": out.splitlines()[-1:] if out else []}

code, out = run(["bash", "-lc", "command -v mihomo >/dev/null || mihomod install --json"], timeout=180, env=base_env)
results["mihomo_install"] = {"code": code, "output_tail": out.splitlines()[-5:]}

if run(["bash", "-lc", "command -v mihomo >/dev/null"], env=base_env)[0] == 0:
    code, out = run(["mihomod", "config", sub_url, "--json"], timeout=60, env=base_env)
    results["mihomo_config"] = {"code": code, "output_tail": out.splitlines()[-5:]}
    code, out = run(["mihomod", "start", "--json"], timeout=60, env=base_env)
    results["mihomo_start"] = {"code": code, "output_tail": out.splitlines()[-5:]}
else:
    results["mihomo_config"] = {"skipped": "mihomo binary is not installed"}

try:
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        data=b'{"contents":[{"parts":[{"text":"Reply with OK only."}]}],"generationConfig":{"maxOutputTokens":8}}',
        headers={"Content-Type": "application/json", "x-goog-api-key": gemini_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        results["gemini_api_smoke"] = {"code": resp.status, "body_prefix": resp.read(160).decode("utf-8", "replace")}
except Exception as exc:
    results["gemini_api_smoke"] = {"error": type(exc).__name__, "message": str(exc)}

code, out = run(
    ["gemini", "--approval-mode", "plan", "--model", "gemini-2.5-flash", "--prompt", "Reply with OK only.", "--output-format", "json"],
    timeout=60,
    env=base_env,
)
results["gemini_cli_smoke"] = {"code": code, "output_tail": out.splitlines()[-10:]}

print(json.dumps(results, ensure_ascii=False, indent=2))
PY

printf '%s\n' "$payload" | ssh "$REMOTE" "REMOTE_ROOT='$REMOTE_ROOT' python3.11 /tmp/agentlab_250_activate.py; rc=\$?; rm -f /tmp/agentlab_250_activate.py; exit \$rc"
