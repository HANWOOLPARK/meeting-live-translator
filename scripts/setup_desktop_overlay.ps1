param(
    [Parameter(Mandatory = $true)] [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$nodeVersion = "v24.18.0"
$nodeArchiveName = "node-$nodeVersion-win-x64.zip"
$nodeReleaseBase = "https://nodejs.org/dist/$nodeVersion"
$electronVersion = "43.1.1"
$root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$runtimeRoot = Join-Path $root ".runtime"
$nodeRoot = Join-Path $runtimeRoot "node"
$desktopRoot = Join-Path $root "desktop"

function Assert-UnderDirectory {
    param([string]$Path, [string]$Parent)
    $full = [IO.Path]::GetFullPath($Path)
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + "\"
    if (-not $full.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a runtime operation outside the project-local directory."
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $desktopRoot "package.json") -PathType Leaf)) {
    throw "desktop\package.json was not found."
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$nodeExe = Join-Path $nodeRoot "node.exe"
$npmCmd = Join-Path $nodeRoot "npm.cmd"

if (-not (Test-Path -LiteralPath $nodeExe -PathType Leaf) -or -not (Test-Path -LiteralPath $npmCmd -PathType Leaf)) {
    $stage = Join-Path $runtimeRoot (".node-install-" + [Guid]::NewGuid().ToString("N"))
    Assert-UnderDirectory -Path $stage -Parent $runtimeRoot
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        $archive = Join-Path $stage $nodeArchiveName
        $checksums = Join-Path $stage "SHASUMS256.txt"
        Write-Output "Downloading portable Node.js $nodeVersion..."
        Invoke-WebRequest -Uri "$nodeReleaseBase/$nodeArchiveName" -OutFile $archive -UseBasicParsing
        Invoke-WebRequest -Uri "$nodeReleaseBase/SHASUMS256.txt" -OutFile $checksums -UseBasicParsing
        $checksumLine = Get-Content -LiteralPath $checksums | Where-Object {
            $_ -match ("\s" + [Regex]::Escape($nodeArchiveName) + "$")
        } | Select-Object -First 1
        if (-not $checksumLine) {
            throw "The official Node.js checksum entry was not found."
        }
        $expected = ($checksumLine -split "\s+")[0].ToUpperInvariant()
        $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
        if ($actual -ne $expected) {
            throw "The portable Node.js archive checksum did not match the official manifest."
        }
        $expanded = Join-Path $stage "expanded"
        Expand-Archive -LiteralPath $archive -DestinationPath $expanded
        $source = Join-Path $expanded ("node-$nodeVersion-win-x64")
        if (-not (Test-Path -LiteralPath (Join-Path $source "node.exe") -PathType Leaf)) {
            throw "The portable Node.js archive did not contain node.exe."
        }
        if (Test-Path -LiteralPath $nodeRoot) {
            Assert-UnderDirectory -Path $nodeRoot -Parent $runtimeRoot
            Remove-Item -LiteralPath $nodeRoot -Recurse -Force
        }
        Move-Item -LiteralPath $source -Destination $nodeRoot
        [IO.File]::WriteAllText(
            (Join-Path $runtimeRoot "node.version"),
            $nodeVersion,
            [Text.UTF8Encoding]::new($false)
        )
    }
    finally {
        if (Test-Path -LiteralPath $stage) {
            Assert-UnderDirectory -Path $stage -Parent $runtimeRoot
            Remove-Item -LiteralPath $stage -Recurse -Force
        }
    }
}

Write-Output ("Node.js: " + (& $nodeExe --version))
Write-Output "Installing Electron $electronVersion inside desktop\node_modules..."
$lockFile = Join-Path $desktopRoot "package-lock.json"
if (Test-Path -LiteralPath $lockFile -PathType Leaf) {
    & $npmCmd ci --prefix $desktopRoot --no-audit --no-fund
}
else {
    & $npmCmd install --prefix $desktopRoot --no-audit --no-fund
}
if ($LASTEXITCODE -ne 0) {
    throw "npm could not install the project-local Electron runtime."
}

$electronExe = Join-Path $desktopRoot "node_modules\electron\dist\electron.exe"
if (-not (Test-Path -LiteralPath $electronExe -PathType Leaf)) {
    # Some npm environments finish dependency resolution without executing the
    # Electron download hook. Run that package-owned hook explicitly and then
    # verify the expected executable instead of silently reporting success.
    $electronInstall = Join-Path $desktopRoot "node_modules\electron\install.js"
    if (Test-Path -LiteralPath $electronInstall -PathType Leaf) {
        Write-Output "Completing the Electron binary download..."
        & $nodeExe $electronInstall
        if ($LASTEXITCODE -ne 0) {
            throw "Electron's project-local binary download hook failed."
        }
    }
}
if (-not (Test-Path -LiteralPath $electronExe -PathType Leaf)) {
    throw "Electron installation finished without electron.exe."
}
Write-Output "Electron runtime ready: $electronVersion"
