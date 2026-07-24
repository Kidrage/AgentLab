#!/usr/bin/env bash
# Crown of Ash Episode 1 — Seedance 1.5 Pro 生成脚本
# 用法: 在终端执行 bash run_crown_ep1.sh
# 注意: 请在 Claude Code 沙箱外运行 (即普通终端, 非 agent shell), 以确保网络直连

SCRIPT_DIR="$HOME/.claude/skills/byted-ark-seedance-skill"

echo "=== Crown of Ash Episode 1: The Grey of Grey Valley ==="
echo "模型: doubao-seedance-1.5-pro | 时长: 12s | 分辨率: 720p | 16:9 | 含音频"
echo ""

node "$SCRIPT_DIR/scripts/seedance-wrapper.js" create \
  --prompt "Cinematic opening for dark-fantasy animated series 'Crown of Ash' Episode 1: 'The Grey of Grey Valley'. 16:9, 12 seconds.

[0-3s] Slow descending wide shot over cramped slate roofs of Grey Valley, a medieval town beneath a permanently pale ash-grey sky at dusk. Countless fine ash particles drift like silent snow, catching faint ember glow. Townspeople in worn brown cloaks sweep ash from stone doorsteps. Distant iron church bells toll. Color: oppressive charcoal grey, muted brown, cold blue.

[3-8s] Cut to interior of a warm smoky blacksmith forge. KANE, a lean young man with soot-dark hair and worn leather apron, strikes glowing iron on an anvil. Each hammer blow sends restrained orange sparks through the cold grey air. His mentor works beside him in silence — a brief moment of quiet camaraderie. Warm forge orange contrasts with the cold exterior. Cinematic depth of field.

[8-11s] Through the forge window: white-robed church enforcers march across the distant town square. A solemn gold-white ceremonial flame rises. Kane lowers his hammer, his expression hardening.

[11-12s] Extreme close-up on Kane's clenched left fist. A tiny ember-like ash brand glows faintly beneath his sleeve for the first time — a warm pulse of orange light through dark fabric. Hold for one beat, then cut to black.

Realistic cloth, smoke and ash physics. Stable character identity. Deliberate, smooth camera movement. Synchronized sound: dry wind, soft ash hiss, three measured hammer strikes, distant iron bells, low restrained strings building to a single sustained note. No dialogue. No gore, no visible wounds, no horror close-ups, no subtitles, no on-screen text, no logos, no watermark." \
  --duration 12 \
  --ratio "16:9" \
  --resolution "720p" \
  --generate-audio true \
  --watermark false \
  --model "doubao-seedance-1.5-pro"
