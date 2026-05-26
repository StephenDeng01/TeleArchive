# Download Microsoft WebView2 Fixed Version (x64) into dist/WebView2Runtime for portable bundling.
param(
    [string]$Version = "131.0.2903.86",
    [string]$OutDir = "dist/WebView2Runtime"
)

$ErrorActionPreference = "Stop"
$pkg = "Microsoft.WebView2.FixedVersionRuntime.$Version"
$url = "https://www.nuget.org/api/v2/package/$pkg/"
$staging = Join-Path $env:RUNNER_TEMP "webview2_pkg"
$zip = Join-Path $env:RUNNER_TEMP "webview2.nupkg.zip"

if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Path $staging | Out-Null

Write-Host "Downloading $pkg ..."
Invoke-WebRequest -Uri $url -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $staging -Force

$native = Join-Path $staging "runtimes/win-x64/native"
$exe = Join-Path $native "msedgewebview2.exe"
if (-not (Test-Path $exe)) {
    throw "msedgewebview2.exe not found under $native"
}

if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Path $OutDir | Out-Null
Copy-Item -Path (Join-Path $native "*") -Destination $OutDir -Recurse -Force
Write-Host "WebView2 Fixed Runtime ready at $OutDir"
