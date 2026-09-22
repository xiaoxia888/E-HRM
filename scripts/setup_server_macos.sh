#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if ! command -v conda >/dev/null 2>&1; then
  echo "错误：未找到 conda。请先安装 Miniconda/Miniforge，并重新打开终端。" >&2
  exit 1
fi

CONDA_BASE="$(conda info --base)"
BASE_PYTHON="$CONDA_BASE/bin/python"
if [[ ! -x "$BASE_PYTHON" ]]; then
  echo "错误：Conda 基础环境缺少 Python：$BASE_PYTHON" >&2
  exit 1
fi

resolve_ehrm_prefix() {
  conda env list --json | "$BASE_PYTHON" -c '
import json
import os
import sys

matches = [path for path in json.load(sys.stdin).get("envs", []) if os.path.basename(path) == "ehrm"]
if len(matches) > 1:
    raise SystemExit(f"无法唯一确定 ehrm 环境目录，匹配结果：{matches}")
print(matches[0] if matches else "")
'
}

EHRM_PREFIX="$(resolve_ehrm_prefix)"
if [[ -n "$EHRM_PREFIX" ]]; then
  echo "更新 Conda 环境：$EHRM_PREFIX"
  conda env update -n ehrm -f environment.server.yml --prune
else
  echo "创建 Conda 环境：ehrm"
  conda env create -f environment.server.yml
fi

EHRM_PREFIX="$(resolve_ehrm_prefix)"
EHRM_PYTHON="$EHRM_PREFIX/bin/python"
EHRM_NPM="$EHRM_PREFIX/bin/npm"
if [[ ! -x "$EHRM_PYTHON" || ! -x "$EHRM_NPM" ]]; then
  echo "错误：ehrm 环境不完整：$EHRM_PREFIX" >&2
  exit 1
fi
echo "使用 Python：$EHRM_PYTHON"
echo "使用 npm：$EHRM_NPM"

export PATH="$EHRM_PREFIX/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PLAYWRIGHT_BROWSERS_PATH="$PROJECT_ROOT/runtime/playwright-browsers"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" "$PROJECT_ROOT/runtime/logs"

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

echo "安装项目锁定版本对应的 Chromium……"
"$EHRM_PYTHON" -m playwright install chromium

echo "构建 Web 页面……"
"$EHRM_NPM" --prefix "$PROJECT_ROOT/frontend" ci
"$EHRM_NPM" --prefix "$PROJECT_ROOT/frontend" run build

echo "检查 Python 依赖和浏览器……"
"$EHRM_PYTHON" - <<'PY'
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path

import fastapi
import playwright
import pyodbc
from playwright.sync_api import sync_playwright

print(f"Python: {sys.executable}")
print(f"Playwright: {version('playwright')}")
print(f"pyodbc: {pyodbc.version}")
with Path("config/settings.toml").open("rb") as stream:
    required_driver = tomllib.load(stream)["erp"]["database"]["driver"]
installed_drivers = pyodbc.drivers()
print(f"ODBC drivers: {installed_drivers}")
if required_driver not in installed_drivers:
    raise SystemExit(f"缺少配置要求的 ODBC 驱动：{required_driver}")
with sync_playwright() as runtime:
    browser = runtime.chromium.launch(headless=True)
    browser.close()
print("Chromium: 启动检查通过")
PY

echo
echo "初始化完成。脚本没有启动 Web 服务。"
echo "启动命令：./scripts/run_server_macos.sh"
