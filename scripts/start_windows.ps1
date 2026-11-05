# Start the whole backend on Windows, one double-click.
#
# What it does, in order: finds Python, creates .venv, installs requirements,
# remembers/creates an API key, starts the server, opens the UI in your browser.
#
# Usage:
#   .\scripts\start_windows.ps1                 # local only, opens the editor UI
#   .\scripts\start_windows.ps1 -Port 8100      # different port
#   .\scripts\start_windows.ps1 -Lan            # reachable from your phone on the same wifi
#   .\scripts\start_windows.ps1 -NoBrowser      # server only (for Task Scheduler)
#   .\scripts\start_windows.ps1 -NoInstall      # skip pip when nothing changed

param(
    [int]$Port = 8000,
    [switch]$Lan,
    [switch]$NoBrowser,
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Fail($message) {
    Write-Host "ERROR: $message" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

# ---- 1. Python ---------------------------------------------------------------
Write-Step "Looking for Python 3.10+"
$python = $null
foreach ($candidate in @("py -3", "python", "python3")) {
    $parts = $candidate.Split(" ")
    $exe = $parts[0]
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        try {
            $version = & $exe $parts[1..($parts.Length - 1)] -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($version -and [version]$version -ge [version]"3.10") {
                $python = $candidate
                break
            }
        } catch { }
    }
}
if (-not $python) {
    Fail "Python 3.10 or newer nahi mila. python.org se install karo ('Add Python to PATH' tick karke), phir dobara chalao."
}
Write-Host "    using: $python"

# ---- 2. Virtual environment --------------------------------------------------
$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Step "Creating .venv (one time, ~1 minute)"
    $parts = $python.Split(" ")
    & $parts[0] $parts[1..($parts.Length - 1)] -m venv .venv
    if (-not (Test-Path $venvPython)) { Fail "venv banane me masla hua." }
}

# ---- 3. Dependencies ---------------------------------------------------------
if (-not $NoInstall) {
    Write-Step "Installing requirements (first run ~2 minutes, later ~5 seconds)"
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "pip install fail hua. Internet check karo, phir dobara." }
}

# ---- 4. API key --------------------------------------------------------------
$keyFile = Join-Path $RepoRoot ".backend_api_key"
if (-not $env:BACKEND_API_KEY) {
    if (Test-Path $keyFile) {
        $env:BACKEND_API_KEY = (Get-Content $keyFile -Raw).Trim()
    } else {
        $env:BACKEND_API_KEY = (& $venvPython -c "import secrets; print(secrets.token_urlsafe(24))").Trim()
        Set-Content -Path $keyFile -Value $env:BACKEND_API_KEY -NoNewline
        Write-Host "    new API key saved to .backend_api_key" -ForegroundColor DarkGray
    }
}

$bindHost = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
$baseUrl = "http://127.0.0.1:$Port"
$uiUrl = "$baseUrl/editor"

Write-Step "Checking the install before starting (no network needed)"
try {
    & $venvPython scripts/preflight.py 2>$null | Out-Null
} catch {
    Write-Host "    preflight skipped (not fatal)" -ForegroundColor DarkGray
}

# ---- 5. Start ----------------------------------------------------------------
if ($Lan) {
    Write-Host ""
    Write-Host "LAN mode: phone se http://<is-pc-ka-IP>:$Port/editor kholo" -ForegroundColor Yellow
    Write-Host "Windows Firewall poochh sakta hai — 'Allow' karo (private network)." -ForegroundColor Yellow
}

if (-not $NoBrowser) {
    Write-Step "Server start ho raha hai, browser 6 second me khulega"
    Start-Job -ScriptBlock {
        param($url)
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                Invoke-WebRequest -Uri "$url/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
                Start-Process $url
                return
            } catch { }
        }
    } -ArgumentList $uiUrl | Out-Null
}

Write-Host ""
Write-Host "  UI      : $uiUrl" -ForegroundColor Green
Write-Host "  API docs: $baseUrl/docs" -ForegroundColor Green
Write-Host "  API key : $env:BACKEND_API_KEY" -ForegroundColor Green
Write-Host "  Stop    : Ctrl+C (ya is window ko band kar do)" -ForegroundColor DarkGray
Write-Host ""

$env:UAI_JOBS_CONCURRENCY = if ($env:UAI_JOBS_CONCURRENCY) { $env:UAI_JOBS_CONCURRENCY } else { "2" }
& $venvPython -m uvicorn app.main:app --host $bindHost --port $Port
