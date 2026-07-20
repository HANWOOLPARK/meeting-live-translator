param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [Parameter(Mandatory = $true)]
    [int]$Port
)

$ErrorActionPreference = "Continue"
$root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$runDir = Join-Path $root ".run"
$serverPidFile = Join-Path $runDir "server.pid"
$workerPidFile = Join-Path $runDir "translation-worker.pid"
$desktopPidFile = Join-Path $runDir "desktop.pid"
$desktopReadyFile = Join-Path $runDir "desktop.ready"
$desktopEntry = Join-Path $root "desktop\main.cjs"
$captureStopUrl = "http://127.0.0.1:$Port/api/capture/stop"
$workerStopUrl = "http://127.0.0.1:$Port/api/translation/worker/stop"
$failed = $false

function Read-SavedProcessId {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $raw = (Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue).Trim()
    $parsed = 0
    if (-not [int]::TryParse($raw, [ref]$parsed) -or $parsed -le 0) {
        Write-Warning "$Label PID file is invalid and will be removed."
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        return $null
    }
    return $parsed
}

function Get-OwnedProcess {
    param([int]$ProcessId, [string]$Marker)
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $ProcessId) -ErrorAction SilentlyContinue
    if ($null -eq $process -or [string]::IsNullOrWhiteSpace([string]$process.CommandLine)) {
        return $null
    }
    $commandLine = [string]$process.CommandLine
    if (
        $commandLine.IndexOf($Marker, [StringComparison]::OrdinalIgnoreCase) -lt 0 -or
        $commandLine.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -lt 0
    ) {
        return $null
    }
    return $process
}

function Wait-UntilExited {
    param([int]$ProcessId, [int]$TimeoutSeconds)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($null -eq (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            return $true
        }
        Start-Sleep -Milliseconds 200
    }
    return $null -eq (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Remove-MatchingPidFile {
    param([string]$Path, [int]$ProcessId)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $current = (Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue).Trim()
    if ($current -eq [string]$ProcessId) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
}

$desktopProcessId = Read-SavedProcessId -Path $desktopPidFile -Label "Desktop"
if ($null -ne $desktopProcessId) {
    $desktopOwned = Get-OwnedProcess -ProcessId $desktopProcessId -Marker $desktopEntry
    if ($null -eq $desktopOwned) {
        $existingDesktop = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $desktopProcessId) -ErrorAction SilentlyContinue
        if ($null -eq $existingDesktop) {
            Write-Output "The saved desktop PID is no longer running."
        }
        else {
            Write-Warning "The saved desktop PID belongs to another process. No process was stopped."
        }
        Remove-Item -LiteralPath $desktopPidFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $desktopReadyFile -Force -ErrorAction SilentlyContinue
    }
    else {
        try {
            # /T is deliberately scoped to the validated Electron root PID. It does
            # not target unrelated Electron or browser processes.
            & taskkill.exe /PID $desktopProcessId /T /F | Out-Null
            if ($LASTEXITCODE -ne 0 -and $null -ne (Get-Process -Id $desktopProcessId -ErrorAction SilentlyContinue)) {
                throw "Targeted Electron process-tree shutdown failed."
            }
            if (-not (Wait-UntilExited -ProcessId $desktopProcessId -TimeoutSeconds 10)) {
                throw "Desktop process did not exit within 10 seconds."
            }
            Remove-MatchingPidFile -Path $desktopPidFile -ProcessId $desktopProcessId
            Remove-Item -LiteralPath $desktopReadyFile -Force -ErrorAction SilentlyContinue
            Write-Output "Meeting Live Translator desktop stopped. PID: $desktopProcessId"
        }
        catch {
            Write-Error "Could not stop the validated desktop PID $desktopProcessId."
            $failed = $true
        }
    }
}
elseif (Test-Path -LiteralPath $desktopReadyFile) {
    Remove-Item -LiteralPath $desktopReadyFile -Force -ErrorAction SilentlyContinue
}

$serverProcessId = Read-SavedProcessId -Path $serverPidFile -Label "Server"
$workerProcessIds = [Collections.Generic.List[int]]::new()
$initialWorkerProcessId = Read-SavedProcessId -Path $workerPidFile -Label "Worker"
if ($null -ne $initialWorkerProcessId) {
    $workerProcessIds.Add($initialWorkerProcessId)
}

$serverOwned = $null
if ($null -ne $serverProcessId) {
    $serverOwned = Get-OwnedProcess -ProcessId $serverProcessId -Marker "backend.app.main:app"
    if ($null -eq $serverOwned) {
        $existing = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $serverProcessId) -ErrorAction SilentlyContinue
        if ($null -eq $existing) {
            Write-Output "The saved server PID is no longer running."
        }
        else {
            Write-Warning "The saved server PID belongs to another process. No process was stopped."
        }
        Remove-Item -LiteralPath $serverPidFile -Force -ErrorAction SilentlyContinue
        $serverProcessId = $null
    }
}

# A Python virtual-environment launcher can hand execution to the base Python
# process. If an older PID file points at the exited launcher, recover only a
# listener whose command line proves that it belongs to this exact project.
if ($null -eq $serverOwned) {
    $listenerCandidates = @(
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    )
    if ($listenerCandidates.Count -eq 1) {
        $listenerProcessId = [int]$listenerCandidates[0].OwningProcess
        $listenerOwned = Get-OwnedProcess `
            -ProcessId $listenerProcessId `
            -Marker "backend.app.main:app"
        if ($null -ne $listenerOwned) {
            $serverProcessId = $listenerProcessId
            $serverOwned = $listenerOwned
            Write-Output "Recovered project server PID from port $Port`: $serverProcessId"
        }
    }
}

if ($null -ne $serverOwned) {
    $ownedListeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    $serverOwnsPort = (
        $ownedListeners.Count -eq 1 -and
        [int]$ownedListeners[0].OwningProcess -eq [int]$serverProcessId
    )
    if ($serverOwnsPort) {
        try {
            Invoke-RestMethod -Method Post -Uri $captureStopUrl -TimeoutSec 20 | Out-Null
        }
        catch {
            Write-Warning "Capture stop did not respond; continuing with targeted process shutdown."
        }
        try {
            Invoke-RestMethod -Method Post -Uri $workerStopUrl -TimeoutSec 25 | Out-Null
        }
        catch {
            Write-Warning "Worker graceful stop did not respond; a validated PID fallback will be used."
        }
    }
    else {
        Write-Warning "Port $Port is not owned exclusively by the saved server PID; API stop calls were skipped."
    }
    try {
        Stop-Process -Id $serverProcessId -Force -ErrorAction Stop
        if (-not (Wait-UntilExited -ProcessId $serverProcessId -TimeoutSeconds 10)) {
            throw "Server process did not exit within 10 seconds."
        }
        Remove-MatchingPidFile -Path $serverPidFile -ProcessId $serverProcessId
        Write-Output "Meeting Live Translator server stopped. PID: $serverProcessId"
    }
    catch {
        Write-Error "Could not stop the validated project server PID $serverProcessId."
        $failed = $true
    }
}
elseif (-not (Test-Path -LiteralPath $serverPidFile)) {
    Write-Output "Meeting Live Translator server is not running."
}

$currentWorkerProcessId = Read-SavedProcessId -Path $workerPidFile -Label "Worker"
if ($null -ne $currentWorkerProcessId -and -not $workerProcessIds.Contains($currentWorkerProcessId)) {
    $workerProcessIds.Add($currentWorkerProcessId)
}

foreach ($workerProcessId in $workerProcessIds) {
    $workerOwned = Get-OwnedProcess -ProcessId $workerProcessId -Marker "local_translation_worker.py"
    if ($null -eq $workerOwned) {
        $existing = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $workerProcessId) -ErrorAction SilentlyContinue
        if ($null -eq $existing) {
            Remove-MatchingPidFile -Path $workerPidFile -ProcessId $workerProcessId
            continue
        }
        Write-Warning "A saved Worker PID belongs to another process. No process was stopped."
        Remove-MatchingPidFile -Path $workerPidFile -ProcessId $workerProcessId
        continue
    }

    if (Wait-UntilExited -ProcessId $workerProcessId -TimeoutSeconds 2) {
        Remove-MatchingPidFile -Path $workerPidFile -ProcessId $workerProcessId
        continue
    }
    try {
        Stop-Process -Id $workerProcessId -Force -ErrorAction Stop
        if (-not (Wait-UntilExited -ProcessId $workerProcessId -TimeoutSeconds 10)) {
            throw "Worker process did not exit within 10 seconds."
        }
        Remove-MatchingPidFile -Path $workerPidFile -ProcessId $workerProcessId
        Write-Output "Local translation Worker stopped. PID: $workerProcessId"
    }
    catch {
        Write-Error "Could not stop the validated local translation Worker PID $workerProcessId."
        $failed = $true
    }
}

if ((Test-Path -LiteralPath $workerPidFile) -and $workerProcessIds.Count -eq 0) {
    Remove-Item -LiteralPath $workerPidFile -Force -ErrorAction SilentlyContinue
}

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    Write-Warning "Port $Port is still in use. No unowned listener was terminated."
    $failed = $true
}

if ($failed) {
    exit 1
}
Write-Output "Meeting Live Translator stopped. Project PID files are clean."
exit 0
