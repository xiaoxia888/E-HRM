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
    throw "Windows EXE must be built on a Windows system."
}

$PythonVersion = python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if (-not $PythonVersion.StartsWith("3.11.")) {
    throw "Current Python version is $PythonVersion. This project requires Python 3.11.x."
}

python -c "import PySide6, PyInstaller, playwright; print('Build dependency check passed.')"
if ($LASTEXITCODE -ne 0) {
    throw "Required Windows build dependencies are missing."
}

if (-not $SkipTests) {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed. Packaging has been stopped."
    }
}

$env:PLAYWRIGHT_BROWSERS_PATH = "0"
$env:PLAYWRIGHT_SKIP_BROWSER_GC = "1"

python -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    throw "Failed to download Chromium."
}

$Version = python scripts/prepare_windows_build.py
if ($LASTEXITCODE -ne 0) {
    throw "Failed to generate Windows icon or version information."
}

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

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$BundleDir = Join-Path $ProjectRoot "dist/windows/E-HRM"

python scripts/verify_windows_bundle.py $BundleDir
if ($LASTEXITCODE -ne 0) {
    throw "Frozen bundle structure validation failed."
}

$ZipPath = Join-Path $ProjectRoot "dist/E-HRM-$Version-windows-x64.zip"

if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}

Compress-Archive `
    -Path $BundleDir `
    -DestinationPath $ZipPath `
    -CompressionLevel Optimal

Write-Host "Portable ZIP package: $ZipPath" -ForegroundColor Green

if (-not $SkipInstaller) {
    $Candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )

    $Iscc = $Candidates |
        Where-Object { $_ -and (Test-Path $_) } |
        Select-Object -First 1

    if ($Iscc) {
        & $Iscc "/DMyAppVersion=$Version" "packaging/windows/installer.iss"

        if ($LASTEXITCODE -ne 0) {
            throw "Failed to generate the Inno Setup installer."
        }

        Write-Host (
            "Installer: " +
            (Join-Path $ProjectRoot "dist/windows-installer/E-HRM-Setup-$Version.exe")
        ) -ForegroundColor Green
    } else {
        Write-Warning "Inno Setup 6 is not installed. Only the portable ZIP package will be generated."
        Write-Warning "Install Inno Setup 6 and run this script again to generate the installer EXE."
    }
}

Write-Host "Windows packaging completed successfully." -ForegroundColor Green