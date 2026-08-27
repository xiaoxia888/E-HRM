[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+(\.\d+)?$')]
    [string]$Version,
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [switch]$Console
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Compress-DirectoryWithRetry {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,
        [Parameter(Mandatory = $true)]
        [string]$DestinationPath,
        [int]$MaxAttempts = 15,
        [int]$RetryDelaySeconds = 2
    )

    for ($Attempt = 1; $Attempt -le $MaxAttempts; $Attempt++) {
        try {
            if (Test-Path $DestinationPath) {
                Remove-Item -Force $DestinationPath
            }

            Compress-Archive `
                -Path $SourcePath `
                -DestinationPath $DestinationPath `
                -CompressionLevel Optimal `
                -ErrorAction Stop
            return
        } catch {
            $FailureMessage = $_.Exception.Message
            if ($Attempt -eq $MaxAttempts) {
                if (Test-Path $DestinationPath) {
                    Remove-Item -Force $DestinationPath -ErrorAction SilentlyContinue
                }
                throw (
                    "Failed to create the portable ZIP after $MaxAttempts attempts. " +
                    "Close any running E-HRM process and temporarily pause real-time " +
                    "antivirus scanning for the build directory, then try again. " +
                    "Last error: $FailureMessage"
                )
            }

            Write-Warning (
                "A build file is temporarily locked. ZIP attempt " +
                "$Attempt/$MaxAttempts failed; retrying in " +
                "$RetryDelaySeconds seconds."
            )
            Start-Sleep -Seconds $RetryDelaySeconds
        }
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Windows EXE must be built on a Windows system."
}

$PythonVersion = python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if (-not $PythonVersion.StartsWith("3.11.")) {
    throw "Current Python version is $PythonVersion. This project requires Python 3.11.x."
}

python -c "import PySide6, PyInstaller, playwright; print(f'Build dependency check passed. PySide6={PySide6.__version__}, PyInstaller={PyInstaller.__version__}')"
if ($LASTEXITCODE -ne 0) {
    throw "Required Windows build dependencies are missing."
}

$QtPdfQmlDir = python -c "from pathlib import Path; from PySide6.QtCore import QLibraryInfo; path = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath)) / 'QtQuick' / 'Pdf'; assert (path / 'qmldir').is_file(), f'Missing QtQuick.Pdf QML module: {path}'; print(path.resolve())"
if ($LASTEXITCODE -ne 0) {
    throw "PySide6 QtQuick.Pdf QML module is missing. Check that PySide6-Addons and PySide6 are both installed at version 6.10.1."
}
Write-Host "QtQuick.Pdf source module: $($QtPdfQmlDir.Trim())"

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

$PrepareArgs = @("scripts/prepare_windows_build.py")
if ($Version) {
    $PrepareArgs += @("--version", $Version)
}

$PreparedVersion = python @PrepareArgs
if ($LASTEXITCODE -ne 0) {
    throw "Failed to generate Windows icon or version information."
}

$Version = $PreparedVersion.Trim()
$ReleaseDir = Join-Path $ProjectRoot "dist/E-HRM-Setup-$Version"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

if ($Console) {
    $env:EHRM_BUILD_CONSOLE = "1"
} else {
    Remove-Item Env:EHRM_BUILD_CONSOLE -ErrorAction SilentlyContinue
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath build/windows-dist `
    --workpath build/windows-work `
    packaging/windows/ehrm.spec

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$BundleDir = Join-Path $ProjectRoot "build/windows-dist/E-HRM"

python scripts/verify_windows_bundle.py $BundleDir
if ($LASTEXITCODE -ne 0) {
    throw "Frozen bundle structure validation failed."
}

$ZipPath = Join-Path $ReleaseDir "E-HRM-$Version-windows-x64.zip"

Compress-DirectoryWithRetry `
    -SourcePath $BundleDir `
    -DestinationPath $ZipPath

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
        & $Iscc `
            "/DMyAppVersion=$Version" `
            "/DMySourceDir=$BundleDir" `
            "/DMyOutputDir=$ReleaseDir" `
            "packaging/windows/installer.iss"

        if ($LASTEXITCODE -ne 0) {
            throw "Failed to generate the Inno Setup installer."
        }

        Write-Host (
            "Installer: " +
            (Join-Path $ReleaseDir "E-HRM-Setup-$Version.exe")
        ) -ForegroundColor Green
    } else {
        Write-Warning "Inno Setup 6 is not installed. Only the portable ZIP package will be generated."
        Write-Warning "Install Inno Setup 6 and run this script again to generate the installer EXE."
    }
}

Write-Host "Release directory: $ReleaseDir" -ForegroundColor Green
Write-Host "Windows packaging completed successfully." -ForegroundColor Green
