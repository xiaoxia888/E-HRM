#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if ! command -v conda >/dev/null 2>&1; then
  echo "错误：未找到 conda。" >&2
  exit 1
fi

CONDA_BASE="$(conda info --base)"
EHRM_PREFIX="$(conda env list --json | "$CONDA_BASE/bin/python" -c '
import json
import os
import sys

matches = [path for path in json.load(sys.stdin).get("envs", []) if os.path.basename(path) == "ehrm"]
if len(matches) != 1:
    raise SystemExit(f"无法唯一确定 ehrm 环境目录，匹配结果：{matches}")
print(matches[0])
')"

export PATH="$EHRM_PREFIX/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PLAYWRIGHT_BROWSERS_PATH="$PROJECT_ROOT/runtime/playwright-browsers"

HOST="${EHRM_HOST:-0.0.0.0}"
PORT="${EHRM_PORT:-8000}"
exec "$EHRM_PREFIX/bin/ehrm-web" --host "$HOST" --port "$PORT"
