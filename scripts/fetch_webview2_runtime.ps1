# Download WebView2 Fixed Runtime (x64) into dist/WebView2Runtime for portable bundling.
param(
    [string]$Version = "",
    [string]$OutDir = "dist/WebView2Runtime"
)

$ErrorActionPreference = "Stop"

function Get-LatestWebView2RuntimeVersion {
    $index = Invoke-RestMethod -Uri "https://api.nuget.org/v3-flatcontainer/webview2.runtime.x64/index.json"
    return $index.versions[-1]
}

if (-not $Version) {
    $Version = Get-LatestWebView2RuntimeVersion
}

$zipUrl = "https://api.nuget.org/v3-flatcontainer/webview2.runtime.x64/$Version/webview2.runtime.x64.$Version.nupkg"
$staging = Join-Path $env:RUNNER_TEMP "webview2_pkg"
$zip = Join-Path $env:RUNNER_TEMP "webview2.runtime.x64.nupkg"

if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Path $staging | Out-Null

Write-Host "Downloading WebView2.Runtime.X64 $Version ..."
Write-Host "URL: $zipUrl"

$maxAttempts = 3
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    try {
        if (Test-Path $zip) { Remove-Item -Force $zip }
        Invoke-WebRequest -Uri $zipUrl -OutFile $zip -TimeoutSec 1200 -UseBasicParsing
        break
    } catch {
        if ($attempt -ge $maxAttempts) { throw }
        Write-Host "Download attempt $attempt failed: $($_.Exception.Message). Retrying..."
        Start-Sleep -Seconds 5
    }
}

Expand-Archive -Path $zip -DestinationPath $staging -Force

$exe = Get-ChildItem -Path $staging -Recurse -Filter "msedgewebview2.exe" | Select-Object -First 1
if (-not $exe) {
    throw "msedgewebview2.exe not found in WebView2.Runtime.X64 $Version package"
}

$nativeDir = $exe.Directory.FullName
Write-Host "Runtime binaries at: $nativeDir"

if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Path $OutDir | Out-Null
Copy-Item -Path (Join-Path $nativeDir "*") -Destination $OutDir -Recurse -Force

$versionFile = Join-Path $OutDir "telearchive-webview2-version.txt"
Set-Content -Path $versionFile -Value $Version -Encoding ascii
Write-Host "WebView2 Fixed Runtime $Version ready at $OutDir"
