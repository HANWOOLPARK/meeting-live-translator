param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$PythonPath,

    [switch]$ForceModelRebuild
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$python = [IO.Path]::GetFullPath($PythonPath)
$runtimeDir = Join-Path $root ".venv-translation"
$runtimePython = Join-Path $runtimeDir "Scripts\python.exe"
$buildDir = Join-Path $root ".venv-translation-build"
$buildPython = Join-Path $buildDir "Scripts\python.exe"
$converter = Join-Path $buildDir "Scripts\ct2-transformers-converter.exe"
$cacheDir = Join-Path $root ".model-install-cache"
$modelParent = Join-Path $root "models\translation"
$modelDir = Join-Path $modelParent "m2m100_418m-int8"
$temporaryModelDir = Join-Path $modelParent ".m2m100_418m-int8.installing"
$runtimeRequirements = Join-Path $root "backend\requirements-local-translation.txt"
$buildRequirements = Join-Path $root "backend\requirements-local-translation-build.txt"
$modelId = "facebook/m2m100_418M"
$modelRevision = "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636"
$expectedModelHash = "590e9c7e229e84de8affe7b15487660a286d3d76e44a4ca10e33099b198d9a76"
$conversionStarted = $false

function Assert-ExactOwnedPath {
    param([string]$Path, [string]$Expected)
    $actualFull = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $expectedFull = [IO.Path]::GetFullPath($Expected).TrimEnd('\')
    if (-not $actualFull.Equals($expectedFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a filesystem operation outside the expected project path: $actualFull"
    }
    if (-not $actualFull.StartsWith($root + "\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a filesystem operation outside the project root: $actualFull"
    }
}

function Remove-ExactOwnedTree {
    param([string]$Path, [string]$Expected)
    Assert-ExactOwnedPath -Path $Path -Expected $Expected
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)] [string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)] [string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath"
    }
}

function Test-ModelFiles {
    param([string]$Path)
    $required = @(
        "model.bin",
        "config.json",
        "shared_vocabulary.json",
        "sentencepiece.bpe.model",
        "vocab.json",
        "tokenizer_config.json"
    )
    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path $name) -PathType Leaf)) {
            return $false
        }
    }
    return $true
}

if (-not (Test-Path -LiteralPath (Join-Path $root "backend\requirements.txt") -PathType Leaf)) {
    throw "The selected directory is not a Meeting Live Translator project root."
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python executable was not found: $python"
}
if (-not (Test-Path -LiteralPath $runtimeRequirements -PathType Leaf)) {
    throw "Runtime requirements file was not found."
}
if (-not (Test-Path -LiteralPath $buildRequirements -PathType Leaf)) {
    throw "Build requirements file was not found."
}

Push-Location $root
try {
    Write-Output "[Local 1/5] Verifying Python 3.11..."
    Invoke-Native $python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"

    if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
        Write-Output "[Local 2/5] Creating isolated .venv-translation..."
        Invoke-Native $python -m venv $runtimeDir
    }
    else {
        Write-Output "[Local 2/5] Reusing isolated .venv-translation..."
    }
    Invoke-Native $runtimePython -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
    Invoke-Native $runtimePython -m pip install --upgrade pip
    Invoke-Native $runtimePython -m pip install -r $runtimeRequirements
    Invoke-Native $runtimePython -c "import importlib.util; assert importlib.util.find_spec('torch') is None, 'Torch must not be installed in .venv-translation'; import ctranslate2, transformers, sentencepiece, psutil; print('Isolated runtime imports: OK')"

    $modelReady = (Test-ModelFiles -Path $modelDir) -and (-not $ForceModelRebuild)
    if ($modelReady) {
        Write-Output "[Local 3/5] Existing M2M100 int8 model found. Download skipped."
    }
    else {
        $driveRoot = [IO.Path]::GetPathRoot($root)
        $availableBytes = ([IO.DriveInfo]::new($driveRoot)).AvailableFreeSpace
        $requiredBytes = 6GB
        if ($availableBytes -lt $requiredBytes) {
            $availableGiB = [Math]::Round($availableBytes / 1GB, 1)
            throw "At least 6 GiB of free disk space is required during model conversion. Available: $availableGiB GiB."
        }

        $conversionStarted = $true
        Remove-ExactOwnedTree -Path $temporaryModelDir -Expected (Join-Path $root "models\translation\.m2m100_418m-int8.installing")
        Remove-ExactOwnedTree -Path $buildDir -Expected (Join-Path $root ".venv-translation-build")
        Remove-ExactOwnedTree -Path $cacheDir -Expected (Join-Path $root ".model-install-cache")
        New-Item -ItemType Directory -Path $modelParent -Force | Out-Null

        Write-Output "[Local 3/5] Creating a temporary conversion environment..."
        Invoke-Native $python -m venv $buildDir
        Invoke-Native $buildPython -m pip install --upgrade pip
        Invoke-Native $buildPython -m pip install -r $buildRequirements

        $env:HF_HOME = $cacheDir
        $env:HF_HUB_DISABLE_TELEMETRY = "1"
        $env:TRANSFORMERS_VERBOSITY = "error"
        Write-Output "Downloading the pinned M2M100 source and converting it to CTranslate2 int8."
        Write-Output "This one-time step can take several minutes and temporarily use about 6 GiB."
        Invoke-Native $converter `
            --model $modelId `
            --revision $modelRevision `
            --output_dir $temporaryModelDir `
            --quantization int8 `
            --copy_files sentencepiece.bpe.model tokenizer_config.json special_tokens_map.json vocab.json generation_config.json

        if (-not (Test-ModelFiles -Path $temporaryModelDir)) {
            throw "The converted model is missing required runtime files."
        }
        $actualHash = (Get-FileHash -LiteralPath (Join-Path $temporaryModelDir "model.bin") -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedModelHash) {
            throw "The converted model hash did not match the verified product model."
        }

        $provenance = [ordered]@{
            model_id = $modelId
            source_revision = $modelRevision
            license_metadata = "mit"
            converter = "ctranslate2 4.8.1"
            transformers = "4.57.6"
            torch = "2.13.0"
            quantization = "int8"
            model_bin_sha256 = $actualHash
            source_url = "https://huggingface.co/facebook/m2m100_418M/tree/$modelRevision"
            installed_at_utc = [DateTime]::UtcNow.ToString("o")
        }
        [IO.File]::WriteAllText(
            (Join-Path $temporaryModelDir "CONVERSION_PROVENANCE.json"),
            ($provenance | ConvertTo-Json -Depth 4),
            [Text.UTF8Encoding]::new($false)
        )

        if (Test-Path -LiteralPath $modelDir) {
            Remove-ExactOwnedTree -Path $modelDir -Expected (Join-Path $root "models\translation\m2m100_418m-int8")
        }
        Move-Item -LiteralPath $temporaryModelDir -Destination $modelDir
        Write-Output "M2M100 int8 model installation completed."
    }

    Write-Output "[Local 4/5] Loading the installed model through the product Worker runtime..."
    $modelExpression = [Management.Automation.Language.CodeGeneration]::EscapeSingleQuotedStringContent($modelDir)
    $smokeCode = "from pathlib import Path; from scripts.local_translation_worker import M2M100Runtime; r=M2M100Runtime(Path(r'$modelExpression')); out=r.translate('Hello world.', 'en', []); assert out.get('translation'); print('Local translation smoke test: OK')"
    Invoke-Native $runtimePython -c $smokeCode

    Write-Output "[Local 5/5] Local translation is ready."
    Write-Output "Runtime: $runtimeDir"
    Write-Output "Model:   $modelDir"
}
finally {
    Pop-Location
    if ($conversionStarted) {
        Write-Output "Cleaning temporary model-download and conversion files..."
        Remove-ExactOwnedTree -Path $temporaryModelDir -Expected (Join-Path $root "models\translation\.m2m100_418m-int8.installing")
        Remove-ExactOwnedTree -Path $buildDir -Expected (Join-Path $root ".venv-translation-build")
        Remove-ExactOwnedTree -Path $cacheDir -Expected (Join-Path $root ".model-install-cache")
    }
}
