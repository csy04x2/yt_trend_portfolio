$ErrorActionPreference = "Stop"

Write-Host "=== Chim Stage 2 evidence collector ==="

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "Python launcher 'py' not found. Install Python first."
    exit 1
}

Write-Host "Checking yt-dlp Python module..."
py -m yt_dlp --version | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing yt-dlp..."
    py -m pip install -U yt-dlp
    if ($LASTEXITCODE -ne 0) {
        Write-Host "yt-dlp installation failed."
        exit 1
    }
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "ffmpeg is not installed or not in PATH."
    Write-Host "Install it, reopen PowerShell, then run this script again."
    exit 1
}

py "$PSScriptRoot\stage2_collect.py" --queue "$PSScriptRoot\stage2_escalation_15.json" --out "$PSScriptRoot\stage2_output"

