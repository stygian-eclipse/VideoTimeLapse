param(
    [bool]$Desktop = $true,
    [switch]$StartMenu,
    [switch]$AllUsers
)

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

function New-VideoTimeLapseShortcut {
    param(
        [string]$ShortcutPath,
        [string]$LauncherPath,
        [string]$RepoRoot
    )

    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($ShortcutPath)
        $shortcut.TargetPath = "powershell.exe"
        $shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$LauncherPath`""
        $shortcut.WorkingDirectory = $RepoRoot
        $shortcut.WindowStyle = 1
        $shortcut.Description = "VideoTimeLapse local timelapse maker"
        $shortcut.Save()
    } catch {
        throw "PowerShell could not create shortcut at '$ShortcutPath'. $_"
    }
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $repoRoot

$launcherPath = Join-Path $repoRoot "run_timelapse_maker.ps1"
if (-not (Test-Path -LiteralPath $launcherPath)) {
    Write-Host "[VideoTimeLapse] run_timelapse_maker.ps1 was not found at: $launcherPath" -ForegroundColor Red
    exit 1
}

$created = New-Object System.Collections.Generic.List[string]

if (-not $Desktop -and -not $StartMenu) {
    Write-WarnMsg "No destination selected. Use -Desktop and/or -StartMenu."
    exit 1
}

if ($Desktop) {
    $desktopDir = [Environment]::GetFolderPath("Desktop")
    if (-not $desktopDir) {
        Write-WarnMsg "Desktop folder could not be resolved. Skipping Desktop shortcut."
    } else {
        $desktopShortcut = Join-Path $desktopDir "VideoTimeLapse.lnk"
        New-VideoTimeLapseShortcut -ShortcutPath $desktopShortcut -LauncherPath $launcherPath -RepoRoot $repoRoot
        $created.Add($desktopShortcut) | Out-Null
    }
}

if ($StartMenu) {
    $startMenuBase = if ($AllUsers) {
        Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs"
    } else {
        Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    }
    if (-not (Test-Path -LiteralPath $startMenuBase)) {
        Write-WarnMsg "Start Menu path not found: $startMenuBase"
    } else {
        $startMenuShortcut = Join-Path $startMenuBase "VideoTimeLapse.lnk"
        New-VideoTimeLapseShortcut -ShortcutPath $startMenuShortcut -LauncherPath $launcherPath -RepoRoot $repoRoot
        $created.Add($startMenuShortcut) | Out-Null
    }
}

if ($created.Count -eq 0) {
    Write-WarnMsg "No shortcuts were created."
    exit 1
}

Write-Step "Shortcut created:"
foreach ($item in $created) {
    Write-Host $item
}
Write-Host "To pin to taskbar, right-click the created shortcut and choose Pin to taskbar."
