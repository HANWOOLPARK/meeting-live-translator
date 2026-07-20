param(
    [Parameter(Mandatory = $true)] [string]$ProjectRoot,
    [Parameter(Mandatory = $true)] [string]$PythonPath,
    [Parameter(Mandatory = $true)] [string]$HostAddress,
    [Parameter(Mandatory = $true)] [int]$Port,
    [Parameter(Mandatory = $true)] [string]$PidFile,
    [Parameter(Mandatory = $true)] [string]$StdoutLog,
    [Parameter(Mandatory = $true)] [string]$StderrLog
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$launcher = $null
$ownedCandidates = [Collections.Generic.HashSet[int]]::new()

function Get-ProjectServerProcess {
    param([int]$ProcessId)
    $process = Get-CimInstance Win32_Process `
        -Filter ("ProcessId=" + $ProcessId) `
        -ErrorAction SilentlyContinue
    if ($null -eq $process -or [string]::IsNullOrWhiteSpace([string]$process.CommandLine)) {
        return $null
    }
    $commandLine = [string]$process.CommandLine
    if (
        $commandLine.IndexOf("backend.app.main:app", [StringComparison]::OrdinalIgnoreCase) -lt 0 -or
        $commandLine.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -lt 0
    ) {
        return $null
    }
    return $process
}

try {
    $existingListeners = @(
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    )
    if ($existingListeners.Count -gt 0) {
        throw "Port $Port is already in use. Run stop_all.bat before starting again."
    }

    $quotedRoot = '"' + $root + '"'
    $arguments = @(
        "-m", "uvicorn", "backend.app.main:app",
        "--app-dir", $quotedRoot,
        "--host", $HostAddress,
        "--port", [string]$Port
    )
    $launcher = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList $arguments `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru

    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    $server = $null
    while ([DateTime]::UtcNow -lt $deadline -and $null -eq $server) {
        $projectProcesses = @(
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.CommandLine -and
                    ([string]$_.CommandLine).IndexOf("backend.app.main:app", [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                    ([string]$_.CommandLine).IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0
                }
        )
        foreach ($process in $projectProcesses) {
            [void]$ownedCandidates.Add([int]$process.ProcessId)
        }
        $listeners = @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        )
        if ($listeners.Count -gt 1) {
            throw "More than one listener was found on port $Port."
        }
        if ($listeners.Count -eq 1) {
            $candidate = Get-ProjectServerProcess -ProcessId ([int]$listeners[0].OwningProcess)
            if ($null -eq $candidate) {
                throw "The new port listener is not owned by this project."
            }
            $server = $candidate
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if ($null -eq $server) {
        throw "The project server did not acquire port $Port within 15 seconds."
    }

    $temporary = $PidFile + ".tmp"
    [IO.File]::WriteAllText(
        $temporary,
        [string]$server.ProcessId,
        [Text.Encoding]::ASCII
    )
    Move-Item -LiteralPath $temporary -Destination $PidFile -Force
    exit 0
}
catch {
    foreach ($processId in $ownedCandidates) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $launcher -and -not $launcher.HasExited) {
        Stop-Process -Id $launcher.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath ($PidFile + ".tmp") -Force -ErrorAction SilentlyContinue
    Write-Error ("Could not start server: " + $_.Exception.Message)
    exit 1
}
