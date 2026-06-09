$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

Write-Host "EmpkinS Radar Recorder Windows build"
Write-Host "Project: $ProjectRoot"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "uv is not installed."
    Write-Host "Install it with this PowerShell command, then run this script again:"
    Write-Host 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    exit 1
}

Write-Host ""
Write-Host "Installing uv-managed Python 3.12..."
uv python install 3.12

Write-Host ""
Write-Host "Installing locked dependencies..."
uv sync --managed-python --python 3.12 --group build

Write-Host ""
Write-Host "Building portable Windows application..."
uv run --managed-python --python 3.12 --group build pyinstaller --clean --noconfirm packaging/empkins_recorder.spec

$AppDir = Join-Path $ProjectRoot "dist\EmpkinS Radar Recorder"
$ZipPath = Join-Path $ProjectRoot "dist\EmpkinS-Radar-Recorder-Windows.zip"

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

Write-Host ""
Write-Host "Creating ZIP package..."
Compress-Archive -Path $AppDir -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Done."
Write-Host "Portable app folder:"
Write-Host "  $AppDir"
Write-Host "ZIP package:"
Write-Host "  $ZipPath"
Write-Host ""
Write-Host "To run the app, open:"
Write-Host "  $AppDir\EmpkinS Radar Recorder.exe"
