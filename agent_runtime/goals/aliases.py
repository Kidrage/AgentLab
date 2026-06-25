ENGLISH_ALIASES = {
    "set": "set",
    "plan": "plan",
    "status": "status",
    "progress": "progress",
    "validate": "validate",
    "report": "report",
    "pause": "pause",
    "resume": "resume",
    "close": "close",
}

CHINESE_ALIASES = {
    "设置": "set",
    "计划": "plan",
    "状态": "status",
    "进度": "progress",
    "验收": "validate",
    "报告": "report",
    "暂停": "pause",
    "恢复": "resume",
    "关闭": "close",
}

def resolve_action(raw_action: str) -> tuple[str, str]:
    """Resolve action string and return (canonical_action, language)."""
    raw_action = raw_action.strip().lower()
    if not raw_action:
        return "set", "en"
    if raw_action in ENGLISH_ALIASES:
        return ENGLISH_ALIASES[raw_action], "en"
    if raw_action in CHINESE_ALIASES:
        return CHINESE_ALIASES[raw_action], "zh"
    return raw_action, "unknown"
