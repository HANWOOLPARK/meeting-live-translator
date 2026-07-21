param(
    [string]$Version = (Get-Date -Format "yyyyMMdd")
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$distDir = Join-Path $root "dist"
$stageDir = Join-Path $distDir (".lite-stage-" + [Guid]::NewGuid().ToString("N"))
$packageName = "whykaigi-lite-$Version"
$packageRoot = Join-Path $stageDir $packageName
$zipPath = Join-Path $distDir ($packageName + ".zip")

function Assert-UnderDirectory {
    param([string]$Path, [string]$Parent)
    $full = [IO.Path]::GetFullPath($Path)
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + "\"
    if (-not $full.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a release operation outside the expected directory: $full"
    }
}

function Copy-RelativeFile {
    param([string]$RelativePath)
    $source = Join-Path $root $RelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required release file was not found: $RelativePath"
    }
    $destination = Join-Path $packageRoot $RelativePath
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($destination)) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
}

function Copy-SourceTree {
    param([string]$RelativeDirectory)
    $sourceRoot = Join-Path $root $RelativeDirectory
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | Where-Object {
        $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
        $_.Extension -notin @('.pyc', '.pyo', '.log')
    } | ForEach-Object {
        $relative = $_.FullName.Substring($root.Length + 1)
        Copy-RelativeFile -RelativePath $relative
    }
}

New-Item -ItemType Directory -Path $distDir -Force | Out-Null
Assert-UnderDirectory -Path $stageDir -Parent $distDir
New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null

try {
    @(
        ".env.example",
        "README.md",
        "README_KO.md",
        "DISTRIBUTION_KO.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "setup.bat",
        "setup_desktop_overlay.bat",
        "setup_local_translation.bat",
        "start_all.bat",
        "stop_all.bat"
    ) | ForEach-Object { Copy-RelativeFile -RelativePath $_ }

    Copy-SourceTree -RelativeDirectory "backend"
    Copy-SourceTree -RelativeDirectory "frontend"
    @(
        "desktop\main.cjs",
        "desktop\preload.cjs",
        "desktop\package.json",
        "desktop\package-lock.json",
        "desktop\assets\whykaigi.ico",
        "desktop\assets\whykaigi-icon.png"
    ) | ForEach-Object { Copy-RelativeFile -RelativePath $_ }
    Copy-RelativeFile -RelativePath "config\translation_glossary.example.json"
    @(
        "scripts\check_audio_devices.py",
        "scripts\install_local_translation.ps1",
        "scripts\local_translation_worker.py",
        "scripts\setup_desktop_overlay.ps1",
        "scripts\start_desktop.ps1",
        "scripts\start_project_server.ps1",
        "scripts\stop_project.ps1"
    ) | ForEach-Object { Copy-RelativeFile -RelativePath $_ }

    $sessionDir = Join-Path $packageRoot "data\sessions"
    New-Item -ItemType Directory -Path $sessionDir -Force | Out-Null
    [IO.File]::WriteAllText(
        (Join-Path $sessionDir ".gitkeep"),
        "",
        [Text.UTF8Encoding]::new($false)
    )

    $forbiddenDirectoryNames = @(
        ".venv",
        ".venv-translation",
        ".venv-translation-build",
        ".run",
        ".runtime",
        ".pytest_cache",
        "models",
        "work",
        "tests",
        "__pycache__",
        "node_modules"
    )
    $releaseEntries = @(Get-ChildItem -LiteralPath $packageRoot -Recurse -Force)
    foreach ($entry in $releaseEntries) {
        if ($entry.Name -eq ".env") {
            throw "A real .env file entered the release package."
        }
        if ($entry.PSIsContainer -and $forbiddenDirectoryNames -contains $entry.Name) {
            throw "Forbidden directory entered the release package: $($entry.Name)"
        }
        if (-not $entry.PSIsContainer -and $entry.Extension -in @('.pyc', '.pyo', '.log')) {
            throw "Runtime artifact entered the release package: $($entry.Name)"
        }
    }

    $textExtensions = @('.bat', '.ps1', '.py', '.txt', '.md', '.json', '.example', '')
    $secretPatterns = @(
        '(?im)^(OPENAI|GEMINI|DEEPGRAM)_API_KEY[\t ]*=[\t ]*(?!$|your[_-])["'']?[^\s#"'']{12,}',
        '(?i)\bsk-[A-Za-z0-9_-]{20,}\b',
        '(?i)\bAQ\.[A-Za-z0-9_-]{20,}\b'
    )
    foreach ($file in @(Get-ChildItem -LiteralPath $packageRoot -Recurse -File -Force)) {
        if ($textExtensions -notcontains $file.Extension.ToLowerInvariant()) {
            continue
        }
        $content = [IO.File]::ReadAllText($file.FullName)
        foreach ($pattern in $secretPatterns) {
            if ($content -match $pattern) {
                throw "A possible API secret was detected in release file: $($file.FullName.Substring($packageRoot.Length + 1))"
            }
        }
    }

    $manifestLines = @(Get-ChildItem -LiteralPath $packageRoot -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
        $relative = $_.FullName.Substring($packageRoot.Length + 1).Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $relative"
    })
    [IO.File]::WriteAllLines(
        (Join-Path $packageRoot "RELEASE_MANIFEST_SHA256.txt"),
        $manifestLines,
        [Text.UTF8Encoding]::new($false)
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $zipPath) {
        Assert-UnderDirectory -Path $zipPath -Parent $distDir
        Remove-Item -LiteralPath $zipPath -Force
    }
    [IO.Compression.ZipFile]::CreateFromDirectory(
        $stageDir,
        $zipPath,
        [IO.Compression.CompressionLevel]::Optimal,
        $false
    )

    $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $entryNames = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
        $requiredSuffixes = @(
            "/setup.bat",
            "/setup_desktop_overlay.bat",
            "/start_all.bat",
            "/stop_all.bat",
            "/README.md",
            "/LICENSE",
            "/DISTRIBUTION_KO.md",
            "/data/sessions/.gitkeep"
        )
        foreach ($suffix in $requiredSuffixes) {
            if (-not ($entryNames | Where-Object { $_.EndsWith($suffix, [StringComparison]::OrdinalIgnoreCase) })) {
                throw "Required ZIP entry is missing: $suffix"
            }
        }
        if ($entryNames | Where-Object {
            $_ -match '(^|/)(\.env|\.venv[^/]*|models|\.run|\.runtime|node_modules|work|tests|__pycache__)(/|$)' -or
            $_ -match '\.(pyc|pyo|log)$'
        }) {
            throw "The ZIP contains a forbidden secret, model, environment, test, or runtime artifact."
        }
    }
    finally {
        $archive.Dispose()
    }

    $sizeMiB = [Math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 2)
    Write-Output "Lite release created: $zipPath"
    Write-Output "ZIP size: $sizeMiB MiB"
}
finally {
    if (Test-Path -LiteralPath $stageDir) {
        Assert-UnderDirectory -Path $stageDir -Parent $distDir
        Remove-Item -LiteralPath $stageDir -Recurse -Force
    }
}
