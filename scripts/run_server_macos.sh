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
EHRM_PYTHON="$EHRM_PREFIX/bin/python"

export PATH="$EHRM_PREFIX/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PLAYWRIGHT_BROWSERS_PATH="$PROJECT_ROOT/runtime/playwright-browsers"

configure_odbc_registry() {
  local required_driver registry_file odbcinst_bin discovered
  local candidates=(
    "/opt/homebrew/etc/odbcinst.ini"
    "/usr/local/etc/odbcinst.ini"
    "/etc/odbcinst.ini"
    "$HOME/.odbcinst.ini"
    "$EHRM_PREFIX/etc/odbcinst.ini"
  )

  required_driver="$("$EHRM_PYTHON" -c 'import sys, tomllib; from pathlib import Path; print(tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["erp"]["database"]["driver"])' "$PROJECT_ROOT/config/settings.toml")"
  for odbcinst_bin in /opt/homebrew/bin/odbcinst /usr/local/bin/odbcinst /usr/bin/odbcinst "$EHRM_PREFIX/bin/odbcinst"; do
    [[ -x "$odbcinst_bin" ]] || continue
    discovered="$("$odbcinst_bin" -j 2>/dev/null | awk -F':' '/^DRIVERS/{sub(/^[[:space:]]*/, "", $2); print $2; exit}' || true)"
    [[ -n "$discovered" ]] && candidates+=("$discovered")
  done

  for registry_file in "${candidates[@]}"; do
    if [[ -f "$registry_file" ]] && grep -Fq "[$required_driver]" "$registry_file"; then
      export ODBCSYSINI="$(dirname "$registry_file")"
      export ODBCINSTINI="$(basename "$registry_file")"
      echo "使用 ODBC 驱动注册表：$registry_file"
      return
    fi
  done

  echo "错误：没有找到包含 [$required_driver] 的 ODBC 驱动注册表。" >&2
  exit 1
}

configure_odbc_registry

HOST="${EHRM_HOST:-0.0.0.0}"
PORT="${EHRM_PORT:-8000}"
echo "服务监听：$HOST:$PORT"
echo "本机访问：http://127.0.0.1:$PORT/rights"
echo "内网访问：http://<这台 Mac 的内网 IP>:$PORT/rights"
exec "$EHRM_PREFIX/bin/ehrm-web" --host "$HOST" --port "$PORT"
