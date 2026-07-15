param(
    [string]$ResultsDirectory,
    [switch]$SkipNativeTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ([string]::IsNullOrWhiteSpace($ResultsDirectory)) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $ResultsDirectory = Join-Path $root "experiments\results\accident_pc_$stamp"
} elseif (-not [System.IO.Path]::IsPathRooted($ResultsDirectory)) {
    $ResultsDirectory = Join-Path $root $ResultsDirectory
}

New-Item -ItemType Directory -Force -Path $ResultsDirectory | Out-Null
$executable = Join-Path $root "experiments\run_accident_scenarios.exe"

Write-Host "==> Build accident-scenario runner"
& g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror `
    experiments\run_accident_scenarios.cpp -o $executable
if ($LASTEXITCODE -ne 0) {
    throw "Accident-scenario runner compilation failed"
}

$safeRoot = (Resolve-Path $root).Path.Replace('\', '/')
$baseCommit = (& git -c "safe.directory=$safeRoot" rev-parse HEAD).Trim()
$branch = (& git -c "safe.directory=$safeRoot" branch --show-current).Trim()
$statusLines = @(& git -c "safe.directory=$safeRoot" status --short)
$compiler = (& g++ --version | Select-Object -First 1).Trim()
$pythonVersion = (& python --version 2>&1).Trim()
$sourceFiles = [ordered]@{}
@(
    "common/point_kinetics_config.h",
    "common/point_kinetics_core.h",
    "experiments/run_accident_scenarios.cpp",
    "experiments/analyse_accident_scenarios.py",
    "experiments/run_accident_campaign.ps1"
) | ForEach-Object {
    $path = Join-Path $root $_
    $sourceFiles[$_] = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
}

$metadata = [ordered]@{
    generated_utc = [DateTime]::UtcNow.ToString("o")
    generated_local = (Get-Date).ToString("o")
    campaign = "PC accident-character presentation surrogates"
    source_base_commit = $baseCommit
    source_branch = $branch
    working_tree_dirty = ($statusLines.Count -gt 0)
    working_tree_status_before_campaign = ($statusLines -join "`n")
    source_file_sha256 = $sourceFiles
    compiler = [ordered]@{
        executable = "g++"
        version = $compiler
        flags = "-std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror"
    }
    python = $pythonVersion
    host = [ordered]@{
        computer_name = $env:COMPUTERNAME
        operating_system = [Environment]::OSVersion.VersionString
        processor = $env:PROCESSOR_IDENTIFIER
    }
    interpretation = "Presentation-level qualitative scenarios; not scientific accident reconstruction or safety analysis."
}
$metadata | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $ResultsDirectory "metadata.json")

Write-Host "==> Run deterministic PC scenarios"
& $executable --output-dir $ResultsDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Accident-scenario campaign failed"
}

Write-Host "==> Analyse traces and generate graphs"
& python experiments\analyse_accident_scenarios.py $ResultsDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Accident-scenario analysis failed"
}

if (-not $SkipNativeTests) {
    Write-Host "==> Run native regression suites"
    & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_native_tests.ps1 *>&1 |
        Tee-Object -FilePath (Join-Path $ResultsDirectory "native_tests.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Native regression suite failed"
    }
}

Write-Host "==> Write SHA-256 manifest"
$resolvedResults = (Resolve-Path $ResultsDirectory).Path
$manifest = Get-ChildItem -Path $resolvedResults -Recurse -File |
    Where-Object { $_.Name -ne "checksums.sha256" } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($resolvedResults.Length + 1).Replace('\', '/')
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        "$hash  $relative"
    }
$manifest | Set-Content -Encoding ASCII (Join-Path $ResultsDirectory "checksums.sha256")

Write-Host "Accident campaign results: $ResultsDirectory"
