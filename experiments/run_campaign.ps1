param(
    [string]$ResultsDirectory,
    [switch]$SkipBuild,
    [switch]$SkipRun,
    [switch]$SkipAnalysis,
    [switch]$SkipNativeTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ([string]::IsNullOrWhiteSpace($ResultsDirectory)) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $ResultsDirectory = Join-Path $root "experiments\results\campaign_$stamp"
} elseif (-not [System.IO.Path]::IsPathRooted($ResultsDirectory)) {
    $ResultsDirectory = Join-Path $root $ResultsDirectory
}

New-Item -ItemType Directory -Force -Path $ResultsDirectory | Out-Null
$executable = Join-Path $root "experiments\run_pc_campaign.exe"

if (-not $SkipBuild) {
    Write-Host "==> Build reproducible PC campaign runner"
    & g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror -Wno-unknown-pragmas `
        experiments\run_pc_campaign.cpp -o $executable
    if ($LASTEXITCODE -ne 0) {
        throw "Campaign runner compilation failed"
    }
}

$safeRoot = (Resolve-Path $root).Path.Replace('\', '/')
$commit = (& git -c "safe.directory=$safeRoot" rev-parse HEAD 2>$null).Trim()
$branch = (& git -c "safe.directory=$safeRoot" branch --show-current 2>$null).Trim()
$statusLines = @(& git -c "safe.directory=$safeRoot" status --short 2>$null)
$compiler = (& g++ --version | Select-Object -First 1).Trim()
$osCaption = [Environment]::OSVersion.VersionString
$osVersion = [Environment]::OSVersion.Version.ToString()
$cpu = $env:PROCESSOR_IDENTIFIER
$logicalProcessors = $env:NUMBER_OF_PROCESSORS
$physicalMemoryGb = $null
try {
    $osInfo = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    $osCaption = $osInfo.Caption
    $osVersion = $osInfo.Version
    $cpuInfo = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
    $cpu = $cpuInfo.Name
    $computerInfo = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    $logicalProcessors = $computerInfo.NumberOfLogicalProcessors
    $physicalMemoryGb = [math]::Round($computerInfo.TotalPhysicalMemory / 1GB, 2)
} catch {
    Write-Warning "WMI host details unavailable; recording environment fallbacks."
}
$vivado = Get-Command vivado -ErrorAction SilentlyContinue
$vitis = Get-Command v++ -ErrorAction SilentlyContinue

$metadata = [ordered]@{
    generated_utc = [DateTime]::UtcNow.ToString("o")
    source_commit = $commit
    source_branch = $branch
    source_tree_dirty = ($statusLines.Count -gt 0)
    source_tree_status = ($statusLines -join "`n")
    working_directory = $root
    host = [ordered]@{
        computer_name = $env:COMPUTERNAME
        operating_system = $osCaption
        operating_system_version = $osVersion
        cpu = $cpu
        logical_processors = $logicalProcessors
        physical_memory_gb = $physicalMemoryGb
    }
    compiler = [ordered]@{
        executable = "g++"
        version = $compiler
        flags = "-std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror -Wno-unknown-pragmas"
    }
    campaign = [ordered]@{
        arithmetic = "IEEE-754 single-precision float for the PC core"
        output_frame_s = 0.1
        timesteps_s = @(0.0001, 0.0005, 0.001, 0.002)
        steady_duration_s = 300
        scram_fast_duration_s = 70
        scram_long_duration_s = 7210
        xenon_duration_h_after_scram = 36
        performance_frames_per_mode = 1000
        project_defined_steady_power_drift_tolerance = 0.001
        project_defined_steady_reactivity_tolerance = 0.00001
    }
    hardware = [ordered]@{
        board = "ZedBoard XC7Z020-1"
        target_clock_ns = 10
        uart = "pending hardware measurement"
        vivado_available_on_path = [bool]$vivado
        vitis_available_on_path = [bool]$vitis
        hardware_execution = "pending hardware testing"
    }
}
$metadata | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $ResultsDirectory "metadata.json")

if (-not $SkipRun) {
    Write-Host "==> Run PC campaign"
    & $executable --output-dir $ResultsDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "PC campaign failed"
    }
}

if (-not $SkipNativeTests) {
    Write-Host "==> Run native regression and PC/HLS parity suites"
    & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_native_tests.ps1 *>&1 |
        Tee-Object -FilePath (Join-Path $ResultsDirectory "native_tests.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Native regression/parity suite failed"
    }
}

if (-not $SkipAnalysis) {
    Write-Host "==> Analyse raw CSV results"
    & python experiments\analyse_results.py --input $ResultsDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Campaign analysis failed"
    }
}

Write-Host "Campaign results: $ResultsDirectory"
