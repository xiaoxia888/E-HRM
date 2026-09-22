$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "未找到 conda。请先安装 Miniconda/Miniforge，并重新打开 PowerShell。"
}
$envs = (conda env list --json | ConvertFrom-Json).envs
$matches = @($envs | Where-Object { (Split-Path $_ -Leaf) -eq "ehrm" })
if ($matches.Count -ne 1) {
    throw "无法唯一确定 ehrm 环境目录，匹配结果：$($matches -join ', ')"
}

$EhrmPrefix = $matches[0]
$env:PATH = "$EhrmPrefix;$EhrmPrefix\Scripts;$EhrmPrefix\Library\bin;$env:PATH"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $ProjectRoot "runtime\playwright-browsers"
$HostAddress = if ($env:EHRM_HOST) { $env:EHRM_HOST } else { "0.0.0.0" }
$Port = if ($env:EHRM_PORT) { $env:EHRM_PORT } else { "8000" }
$EhrmWeb = Join-Path $EhrmPrefix "Scripts\ehrm-web.exe"
if (-not (Test-Path $EhrmWeb)) {
    throw "ehrm 环境缺少 Web 启动程序：$EhrmWeb。请先运行初始化脚本。"
}
& $EhrmWeb --host $HostAddress --port $Port
exit $LASTEXITCODE
