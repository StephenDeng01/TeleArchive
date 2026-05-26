# Build telearchive.exe on Windows (PowerShell)
# Usage: .\scripts\build_windows.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "Installing build dependencies..."
python -m pip install --upgrade pip
pip install ".[build]"

Write-Host "Running PyInstaller..."
pyinstaller --noconfirm --clean telearchive.spec

$exe = Join-Path (Get-Location) "dist\telearchive.exe"
if (Test-Path $exe) {
    $size = (Get-Item $exe).Length / 1MB
    Write-Host ""
    Write-Host "Done: $exe ($([math]::Round($size, 1)) MB)" -ForegroundColor Green
    Write-Host "Try: .\dist\telearchive.exe --help"
} else {
    Write-Error "Build failed: dist\telearchive.exe not found"
}
