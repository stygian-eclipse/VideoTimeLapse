Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[VideoTimeLapse] $Message" -ForegroundColor Cyan
}

function Write-WarnMsg {
    param([string]$Message)
    Write-Host "[VideoTimeLapse] $Message" -ForegroundColor Yellow
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $repoRoot

$venvPath = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
$requirementsPath = Join-Path $repoRoot "requirements.txt"
$appUrl = "http://127.0.0.1:8000"

Write-Step "Working directory: $repoRoot"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[VideoTimeLapse] Python was not found in PATH. Install Python 3.11+ and retry." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -Path $venvPath)) {
    Write-Step "Creating virtual environment (.venv)..."
    python -m venv .venv
} else {
    Write-Step "Virtual environment already exists."
}

if (-not (Test-Path -Path $venvPython)) {
    Write-Host "[VideoTimeLapse] .venv was created/found, but python.exe is missing at $venvPython" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -Path $activateScript)) {
    Write-Host "[VideoTimeLapse] Activation script missing at $activateScript" -ForegroundColor Red
    exit 1
}

Write-Step "Activating virtual environment..."
. $activateScript

if (-not (Test-Path -Path $requirementsPath)) {
    Write-Host "[VideoTimeLapse] requirements.txt was not found in repository root." -ForegroundColor Red
    exit 1
}

Write-Step "Upgrading pip..."
& $venvPython -m pip install --upgrade pip

Write-Step "Installing dependencies from requirements.txt..."
& $venvPython -m pip install -r $requirementsPath

$ffmpegOk = $true
$ffprobeOk = $true

Write-Step "Checking FFmpeg availability..."
try {
    & ffmpeg -version | Out-Null
} catch {
    $ffmpegOk = $false
}

try {
    & ffprobe -version | Out-Null
} catch {
    $ffprobeOk = $false
}

if (-not $ffmpegOk -or -not $ffprobeOk) {
    Write-WarnMsg "FFmpeg tools were not fully detected in PATH."
    Write-WarnMsg "Video processing requires both 'ffmpeg' and 'ffprobe'."
    Write-WarnMsg "Install option (Windows): winget install Gyan.FFmpeg"
    Write-WarnMsg "The server will still start; the UI and API will also report this issue."
} else {
    Write-Step "FFmpeg and FFprobe are available."
}

Write-Step "Scheduling browser open: $appUrl"
$null = Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:8000"
}

Write-Step "Starting FastAPI server on 127.0.0.1:8000"
Write-Step "Press Ctrl+C to stop."
& $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
