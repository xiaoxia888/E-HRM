$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "未找到 conda。请先安装 Miniconda/Miniforge，并重新打开 PowerShell。"
}

function Get-EhrmPrefix {
    $envs = (conda env list --json | ConvertFrom-Json).envs
    $matches = @($envs | Where-Object { (Split-Path $_ -Leaf) -eq "ehrm" })
    if ($matches.Count -ne 1) {
        throw "无法唯一确定 ehrm 环境目录，匹配结果：$($matches -join ', ')"
    }
    return $matches[0]
}

$envs = (conda env list --json | ConvertFrom-Json).envs
$existingMatches = @($envs | Where-Object { (Split-Path $_ -Leaf) -eq "ehrm" })
if ($existingMatches.Count -gt 1) {
    throw "发现多个名为 ehrm 的 Conda 环境，无法安全选择：$($existingMatches -join ', ')"
}
if ($existingMatches.Count -eq 1) {
    $EhrmPrefix = $existingMatches[0]
    Write-Host "更新 Conda 环境：$EhrmPrefix"
    conda env update -n ehrm -f environment.server.yml --prune
} else {
    Write-Host "创建 Conda 环境：ehrm"
    conda env create -f environment.server.yml
}
if ($LASTEXITCODE -ne 0) { throw "Conda 环境初始化失败。" }

$EhrmPrefix = Get-EhrmPrefix
$EhrmPython = Join-Path $EhrmPrefix "python.exe"
$env:PATH = "$EhrmPrefix;$EhrmPrefix\Scripts;$EhrmPrefix\Library\bin;$env:PATH"
$EhrmNpm = @(
    (Join-Path $EhrmPrefix "npm.cmd"),
    (Join-Path $EhrmPrefix "Scripts\npm.cmd"),
    (Join-Path $EhrmPrefix "Library\bin\npm.cmd")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not (Test-Path $EhrmPython)) { throw "ehrm 环境缺少 Python：$EhrmPython" }
if (-not $EhrmNpm) { throw "ehrm 环境缺少 npm。请检查 environment.server.yml。" }
Write-Host "使用 Python：$EhrmPython"
Write-Host "使用 npm：$EhrmNpm"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $ProjectRoot "runtime\playwright-browsers"
New-Item -ItemType Directory -Force $env:PLAYWRIGHT_BROWSERS_PATH | Out-Null
New-Item -ItemType Directory -Force (Join-Path $ProjectRoot "runtime\logs") | Out-Null

Write-Host "安装项目锁定版本对应的 Chromium……"
& $EhrmPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Chromium 安装失败。" }

Write-Host "构建 Web 页面……"
& $EhrmNpm --prefix (Join-Path $ProjectRoot "frontend") ci
if ($LASTEXITCODE -ne 0) { throw "前端依赖安装失败。" }
& $EhrmNpm --prefix (Join-Path $ProjectRoot "frontend") run build
if ($LASTEXITCODE -ne 0) { throw "前端构建失败。" }

Write-Host "检查 Python 依赖……"
& $EhrmPython -c "import sys, tomllib; from pathlib import Path; from importlib.metadata import version; import fastapi, playwright, pyodbc; required=tomllib.loads(Path('config/settings.toml').read_text(encoding='utf-8'))['erp']['database']['driver']; installed=pyodbc.drivers(); print('Python:', sys.executable); print('Playwright:', version('playwright')); print('pyodbc:', pyodbc.version); print('ODBC drivers:', installed); assert required in installed, f'缺少配置要求的 ODBC 驱动：{required}'"
if ($LASTEXITCODE -ne 0) { throw "Python 依赖检查失败。" }

Write-Host "检查 Chromium……"
& $EhrmPython -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); b.close(); p.stop(); print('Chromium: 启动检查通过')"
if ($LASTEXITCODE -ne 0) { throw "Chromium 启动检查失败。" }

Write-Host ""
Write-Host "初始化完成。脚本没有启动 Web 服务。"
Write-Host "启动命令：powershell -ExecutionPolicy Bypass -File .\scripts\run_server_windows.ps1"
