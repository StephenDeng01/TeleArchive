# Build TeleArchive.exe (GUI) on Windows (PowerShell)
# Usage: .\scripts\build_windows.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "Installing build dependencies..."
python -m pip install --upgrade pip
pip install ".[build]"

Write-Host "Running PyInstaller..."
pyinstaller --noconfirm --clean telearchive.spec

$exe = Join-Path (Get-Location) "dist\TeleArchive.exe"
if (Test-Path $exe) {
    $size = (Get-Item $exe).Length / 1MB
    Write-Host ""
    Write-Host "Done: $exe ($([math]::Round($size, 1)) MB)" -ForegroundColor Green
    Write-Host "Double-click TeleArchive.exe to open the GUI."
    Write-Host "CLI: TeleArchive.exe --cli ingest <path>"
} else {
    Write-Error "Build failed: dist\TeleArchive.exe not found"
}
