#!/usr/bin/env bash
set -euo pipefail

REMOTE="${AGENTLAB_250_REMOTE:-admin@10.147.17.250}"
REMOTE_ROOT="${AGENTLAB_250_ROOT:-/home/admin/AgentLab}"
STATUS_ONLY=0
ENABLE_GEMINI_API_FALLBACK=0

usage() {
  cat <<'EOF'
Usage: scripts/activate_250_runtime.sh [--remote user@host] [--root /path/to/AgentLab] [--status-only] [--enable-gemini-api-fallback]

Activates the 250 network runtime after explicit secret-write approval.
No secrets are stored in this script. The default path prompts only for:

- Clash/mihomo subscription URL

The subscription is sent over SSH and written only to a private remote file.
AgentLab's default Gemini path remains Agy with local Gemini OAuth and the
Gemini 3.5 Flash High shell model. This script does not transfer OAuth state.

Use --enable-gemini-api-fallback to explicitly configure the non-default
Gemini 2.5 Flash API-key fallback. That mode additionally prompts for a Gemini
API key and stores it only in private fallback/Gemini CLI files.

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
    --enable-gemini-api-fallback)
      ENABLE_GEMINI_API_FALLBACK=1
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
        "mihomo_direct_process": bool(run(["bash", "-lc", "pgrep -af '/home/admin/.local/bin/mihomo -d /home/admin/.config/mihomo' || true"])[1]),
        "proxy_8123_listening": bool(run(["bash", "-lc", "ss -ltn 2>/dev/null | grep ':8123 ' || true"])[1]),
    },
    "proxy_env_keys": sorted([key for key in os.environ if "proxy" in key.lower()]),
    "secret_key_presence": {
        "~/.agentlab_secrets/env": env_keys(pathlib.Path.home() / ".agentlab_secrets/env", ["CLASH_SUBSCRIBE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY"]),
        "~/.agentlab_secrets/network.env": env_keys(pathlib.Path.home() / ".agentlab_secrets/network.env", ["CLASH_SUBSCRIBE_URL"]),
        "~/.agentlab_secrets/gemini_api_fallback.env": env_keys(pathlib.Path.home() / ".agentlab_secrets/gemini_api_fallback.env", ["GEMINI_API_KEY", "GOOGLE_API_KEY"]),
        "~/.agentlab_runtime/network.env": env_keys(pathlib.Path.home() / ".agentlab_runtime/network.env", ["HTTP_PROXY", "HTTPS_PROXY"]),
        "~/.gemini/.env": env_keys(pathlib.Path.home() / ".gemini/.env", ["GEMINI_API_KEY", "GOOGLE_API_KEY"]),
        "agent_runtime/.env": env_keys(remote_root / "agent_runtime/.env", ["CLASH_SUBSCRIBE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY"]),
    },
    "legacy_default_override_presence": {
        "~/.agentlab_secrets/env": env_keys(pathlib.Path.home() / ".agentlab_secrets/env", ["HERMES_INFERENCE_PROVIDER", "HERMES_INFERENCE_MODEL"]),
        "agent_runtime/.env": env_keys(remote_root / "agent_runtime/.env", ["HERMES_INFERENCE_PROVIDER", "HERMES_INFERENCE_MODEL"]),
    },
    "default_gemini_policy": {
        "worker": "agy",
        "auth_mode": "local_gemini_oauth_session",
        "model": "gemini-3.5-flash-high",
        "api_fallback": "disabled_by_default",
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
if [[ "$ENABLE_GEMINI_API_FALLBACK" == "1" && -z "${GEMINI_API_KEY:-}" ]]; then
  read -r -s -p "Gemini API key: " GEMINI_API_KEY
  echo
fi

if [[ -z "$CLASH_SUBSCRIBE_URL" ]]; then
  echo "CLASH_SUBSCRIBE_URL is required." >&2
  exit 2
fi
if [[ "$ENABLE_GEMINI_API_FALLBACK" == "1" && -z "${GEMINI_API_KEY:-}" ]]; then
  echo "GEMINI_API_KEY is required with --enable-gemini-api-fallback." >&2
  exit 2
fi

payload="$(
  SUB="$CLASH_SUBSCRIBE_URL" KEY="${GEMINI_API_KEY:-}" ENABLE_GEMINI_API_FALLBACK="$ENABLE_GEMINI_API_FALLBACK" python3 - <<'PY'
import base64
import json
import os

print(base64.b64encode(json.dumps({
    "clash_subscribe_url": os.environ["SUB"],
    "gemini_api_key": os.environ.get("KEY", ""),
    "enable_gemini_api_fallback": os.environ["ENABLE_GEMINI_API_FALLBACK"] == "1",
}).encode()).decode())
PY
)"

ssh "$REMOTE" "cat > /tmp/agentlab_250_activate.py && chmod 700 /tmp/agentlab_250_activate.py" <<'PY'
import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request

remote_root = pathlib.Path(os.environ["REMOTE_ROOT"])
payload = json.loads(base64.b64decode(sys.stdin.read().strip()).decode())
sub_url = payload["clash_subscribe_url"]
gemini_api_fallback_enabled = bool(payload.get("enable_gemini_api_fallback"))
gemini_key = payload.get("gemini_api_key", "") if gemini_api_fallback_enabled else ""

def redact(text: str) -> str:
    text = text.replace(sub_url, "<CLASH_SUBSCRIBE_URL>")
    if gemini_key:
        text = text.replace(gemini_key, "<GEMINI_API_KEY>")
    return re.sub(r"token=[A-Za-z0-9._-]+", "token=<redacted>", text)

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

def remove_env_keys(path: pathlib.Path, keys: set[str]) -> None:
    if not path.exists():
        return
    kept: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
        if key not in keys:
            kept.append(line)
    path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    path.chmod(0o600)

home = pathlib.Path.home()
merge_env(home / ".agentlab_secrets/network.env", {"CLASH_SUBSCRIBE_URL": sub_url})
proxy_url = "http://127.0.0.1:8123"
merge_env(
    home / ".agentlab_runtime/network.env",
    {
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "http_proxy": proxy_url,
        "https_proxy": proxy_url,
    },
)

legacy_default_keys = {
    "HERMES_INFERENCE_PROVIDER",
    "HERMES_INFERENCE_MODEL",
}
remove_env_keys(home / ".agentlab_secrets/env", legacy_default_keys)
remove_env_keys(remote_root / "agent_runtime/.env", legacy_default_keys)

if gemini_api_fallback_enabled:
    fallback_updates = {
        "GEMINI_API_KEY": gemini_key,
        "GOOGLE_API_KEY": gemini_key,
        "GOOGLE_GENAI_USE_GCA": "false",
        "GOOGLE_GENAI_USE_VERTEXAI": "false",
        "GEMINI_CLI_TRUST_WORKSPACE": "true",
    }
    merge_env(home / ".agentlab_secrets/gemini_api_fallback.env", fallback_updates)
    merge_env(home / ".gemini/.env", fallback_updates)

    gemini_workspace_settings = remote_root / ".agents/workspaces/.gemini/settings.json"
    gemini_workspace_settings.parent.mkdir(parents=True, exist_ok=True)
    try:
        gemini_settings = json.loads(gemini_workspace_settings.read_text(encoding="utf-8")) if gemini_workspace_settings.exists() else {}
        if not isinstance(gemini_settings, dict):
            gemini_settings = {}
    except json.JSONDecodeError:
        gemini_settings = {}
    gemini_settings.setdefault("security", {}).setdefault("auth", {})["selectedType"] = "gemini-api-key"
    gemini_workspace_settings.write_text(json.dumps(gemini_settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

source_line = 'test -f "$HOME/.agentlab_runtime/network.env" && set -a && . "$HOME/.agentlab_runtime/network.env" && set +a'
for name in (".bashrc", ".zshrc"):
    profile = home / name
    text = profile.read_text(encoding="utf-8") if profile.exists() else ""
    if source_line not in text:
        text = text.rstrip() + "\n" + source_line
    profile.write_text(text.rstrip() + "\n", encoding="utf-8")

def run(
    cmd: list[str],
    *,
    timeout: int = 120,
    env: dict[str, str] | None = None,
    cwd: pathlib.Path | None = None,
) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=env,
            cwd=str(cwd) if cwd else None,
        )
        return proc.returncode, redact(proc.stdout.strip())
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        return 124, redact(output.strip())
    except OSError as exc:
        return 255, f"{type(exc).__name__}: {exc}"

base_env = os.environ.copy()
base_env.pop("HTTP_PROXY", None)
base_env.pop("HTTPS_PROXY", None)
base_env.pop("http_proxy", None)
base_env.pop("https_proxy", None)
base_env.pop("ALL_PROXY", None)
base_env.pop("all_proxy", None)
base_env.pop("GOOGLE_GEMINI_BASE_URL", None)
if gemini_api_fallback_enabled:
    base_env["GEMINI_API_KEY"] = gemini_key
    base_env["GOOGLE_API_KEY"] = gemini_key
    base_env["GOOGLE_GENAI_USE_GCA"] = "false"
    base_env["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
    base_env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"

results: dict[str, object] = {
    "network_runtime": "configured",
    "default_gemini_path": "agy_gemini_oauth",
    "gemini_api_fallback_enabled": gemini_api_fallback_enabled,
}

code, out = run(["bash", "-lc", "command -v mihomod || npm install -g mihomod@0.2.0 >/dev/null && command -v mihomod"], env=base_env)
results["mihomod"] = {"code": code, "output": out.splitlines()[-1:] if out else []}

code, out = run(["bash", "-lc", "command -v mihomo >/dev/null || mihomod install --json"], timeout=180, env=base_env)
results["mihomo_install"] = {"code": code, "output_tail": out.splitlines()[-5:]}

if run(["bash", "-lc", "command -v mihomo >/dev/null"], env=base_env)[0] == 0:
    code, out = run(["mihomod", "config", sub_url, "--json"], timeout=60, env=base_env)
    results["mihomo_config"] = {"code": code, "output_tail": out.splitlines()[-5:]}
    if code != 0:
        try:
            req = urllib.request.Request(sub_url, headers={"User-Agent": "clash-verge/v2.0.0"})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=45) as resp:
                config_text = resp.read().decode("utf-8", "replace")
            config_text = re.sub(r"(?m)^mixed-port:\s*\d+\s*$", "mixed-port: 8123", config_text, count=1)
            config_path = pathlib.Path.home() / ".config/mihomo/config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(config_text, encoding="utf-8")
            config_path.chmod(0o600)
            results["mihomo_config_fallback"] = {"code": 0, "method": "clash-verge user-agent", "path": str(config_path)}
        except Exception as exc:
            results["mihomo_config_fallback"] = {"error": type(exc).__name__, "message": str(exc)}
    run(["mihomod", "stop", "--json"], timeout=30, env=base_env)
    run(["bash", "-lc", "pkill -f '/home/admin/.local/bin/mihomo -d /home/admin/.config/mihomo' || true"], timeout=30, env=base_env)
    code, out = run(["mihomod", "start", "--json"], timeout=60, env=base_env)
    results["mihomo_start"] = {"code": code, "output_tail": out.splitlines()[-5:]}
else:
    results["mihomo_config"] = {"skipped": "mihomo binary is not installed"}

proxy_env = base_env.copy()
if results.get("mihomo_start", {}).get("code") == 0:
    proxy_env.update({
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "http_proxy": proxy_url,
        "https_proxy": proxy_url,
    })

code, out = run(
    ["./agentlab.sh", "worker-invocation-probe", "--worker", "agy"],
    timeout=60,
    env=proxy_env,
    cwd=remote_root,
)
results["agy_cli_safe_probe"] = {
    "code": code,
    "output_tail": out.splitlines()[-10:],
    "auth_mode": "local_gemini_oauth_session",
    "live_smoke": "run ./agentlab.sh agy-cli-smoke --live after remote OAuth login",
}

if gemini_api_fallback_enabled:
    try:
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            data=b'{"contents":[{"parts":[{"text":"Reply with OK only."}]}],"generationConfig":{"maxOutputTokens":8}}',
            headers={"Content-Type": "application/json", "x-goog-api-key": gemini_key},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({
            "http": proxy_env.get("http_proxy"),
            "https": proxy_env.get("https_proxy"),
        }))
        with opener.open(req, timeout=30) as resp:
            results["gemini_api_smoke"] = {"code": resp.status, "body_prefix": resp.read(160).decode("utf-8", "replace")}
    except Exception as exc:
        results["gemini_api_smoke"] = {"error": type(exc).__name__, "message": str(exc)}

    cli_env = proxy_env.copy()
    cli_env.pop("GOOGLE_API_KEY", None)
    code, out = run(
        ["gemini", "--skip-trust", "--approval-mode", "plan", "--model", "gemini-2.5-flash", "--prompt", "Reply with OK only.", "--output-format", "json"],
        timeout=120,
        env=cli_env,
    )
    results["gemini_cli_smoke"] = {"code": code, "output_tail": out.splitlines()[-10:]}
else:
    results["gemini_api_smoke"] = {"status": "disabled_by_default"}
    results["gemini_cli_smoke"] = {"status": "disabled_by_default"}

print(json.dumps(results, ensure_ascii=False, indent=2))
PY

printf '%s\n' "$payload" | ssh "$REMOTE" "REMOTE_ROOT='$REMOTE_ROOT' python3.11 /tmp/agentlab_250_activate.py; rc=\$?; rm -f /tmp/agentlab_250_activate.py; exit \$rc"
