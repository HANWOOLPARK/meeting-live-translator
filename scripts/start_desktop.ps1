param(
    [Parameter(Mandatory = $true)] [string]$ProjectRoot,
    [Parameter(Mandatory = $true)] [string]$ExecutablePath,
    [Parameter(Mandatory = $true)] [string]$EntryPath,
    [Parameter(Mandatory = $true)] [string]$AppUrl,
    [Parameter(Mandatory = $true)] [string]$PidFile,
    [Parameter(Mandatory = $true)] [string]$ReadyFile,
    [Parameter(Mandatory = $true)] [string]$StdoutLog,
    [Parameter(Mandatory = $true)] [string]$StderrLog
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$entry = [IO.Path]::GetFullPath($EntryPath)

function Get-OwnedDesktopProcess {
    param([int]$ProcessId)
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $ProcessId) -ErrorAction SilentlyContinue
    if ($null -eq $process -or [string]::IsNullOrWhiteSpace([string]$process.CommandLine)) {
        return $null
    }
    $commandLine = [string]$process.CommandLine
    if (
        $commandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -lt 0 -or
        $commandLine.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -lt 0
    ) {
        return $null
    }
    return $process
}

if (Test-Path -LiteralPath $PidFile) {
    $saved = (Get-Content -LiteralPath $PidFile -Raw -ErrorAction SilentlyContinue).Trim()
    $savedId = 0
    if ([int]::TryParse($saved, [ref]$savedId) -and $null -ne (Get-OwnedDesktopProcess -ProcessId $savedId)) {
        Write-Output "VerbaRadar desktop is already running. PID: $savedId"
        exit 0
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ReadyFile -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "Electron executable was not found. Run setup_desktop_overlay.bat first."
}
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw "Electron main entry was not found."
}

$env:MLT_PROJECT_ROOT = $root
$env:MLT_APP_URL = $AppUrl
$env:MLT_DESKTOP_READY_FILE = $ReadyFile
Remove-Item -LiteralPath $ReadyFile -Force -ErrorAction SilentlyContinue
$process = Start-Process `
    -FilePath $ExecutablePath `
    -ArgumentList @(('"' + $entry + '"')) `
    -WorkingDirectory (Split-Path -Parent $entry) `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog `
    -PassThru

$deadline = [DateTime]::UtcNow.AddSeconds(20)
$ready = $false
while ([DateTime]::UtcNow -lt $deadline) {
    if ($process.HasExited) {
        break
    }
    if (Test-Path -LiteralPath $ReadyFile) {
        $readyPid = (Get-Content -LiteralPath $ReadyFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($readyPid -eq [string]$process.Id) {
            $ready = $true
            break
        }
    }
    Start-Sleep -Milliseconds 200
    $process.Refresh()
}

if (-not $ready) {
    if (-not $process.HasExited) {
        & taskkill.exe /PID $process.Id /T /F | Out-Null
    }
    Remove-Item -LiteralPath $ReadyFile -Force -ErrorAction SilentlyContinue
    throw "Electron did not report a ready main window within 20 seconds."
}

$temporary = $PidFile + ".tmp"
[IO.File]::WriteAllText($temporary, [string]$process.Id, [Text.Encoding]::ASCII)
Move-Item -LiteralPath $temporary -Destination $PidFile -Force
Write-Output "VerbaRadar desktop ready. PID: $($process.Id)"
