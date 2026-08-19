[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [switch]$Console
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Windows EXE 必须在 Windows 系统中构建。"
}

$PythonVersion = python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if (-not $PythonVersion.StartsWith("3.11.")) {
    throw "当前 Python 为 $PythonVersion，项目要求 Python 3.11.x。"
}

python -c "import PySide6, PyInstaller, playwright; print('构建依赖检查通过')"
if ($LASTEXITCODE -ne 0) { throw "缺少 Windows 构建依赖。" }

if (-not $SkipTests) {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "测试失败，已停止打包。" }
}

$env:PLAYWRIGHT_BROWSERS_PATH = "0"
$env:PLAYWRIGHT_SKIP_BROWSER_GC = "1"
python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Chromium 下载失败。" }

$Version = python scripts/prepare_windows_build.py
if ($LASTEXITCODE -ne 0) { throw "Windows 图标或版本信息生成失败。" }
$Version = $Version.Trim()

if ($Console) {
    $env:EHRM_BUILD_CONSOLE = "1"
} else {
    Remove-Item Env:EHRM_BUILD_CONSOLE -ErrorAction SilentlyContinue
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath dist/windows `
    --workpath build/windows `
    packaging/windows/ehrm.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败。" }

$BundleDir = Join-Path $ProjectRoot "dist/windows/E-HRM"
python scripts/verify_windows_bundle.py $BundleDir
if ($LASTEXITCODE -ne 0) { throw "冻结包结构校验失败。" }

$ZipPath = Join-Path $ProjectRoot "dist/E-HRM-$Version-windows-x64.zip"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path $BundleDir -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Host "便携目录压缩包：$ZipPath" -ForegroundColor Green

if (-not $SkipInstaller) {
    $Candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $Iscc = $Candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if ($Iscc) {
        & $Iscc "/DMyAppVersion=$Version" "packaging/windows/installer.iss"
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup 安装包生成失败。" }
        Write-Host (
            "安装程序：" +
            (Join-Path $ProjectRoot "dist/windows-installer/E-HRM-Setup-$Version.exe")
        ) -ForegroundColor Green
    } else {
        Write-Warning "未安装 Inno Setup 6，本次只生成目录版 ZIP。"
        Write-Warning "安装 Inno Setup 6 后重新运行即可生成单个安装程序 EXE。"
    }
}

Write-Host "Windows 打包完成。" -ForegroundColor Green
