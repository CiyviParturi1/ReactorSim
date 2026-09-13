# Build and run the native regression suites from the repository root.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $root "build\native-tests"
$commonFlags = @(
    "-std=c++17",
    "-O2",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror"
)

function Invoke-NativeTarget {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$OutputName,
        [Parameter(Mandatory)] [string[]]$Sources,
        [string[]]$ExtraFlags = @(),
        [switch]$BuildOnly
    )

    $output = Join-Path $buildDir "$OutputName.exe"
    Write-Host "==> $Name"
    & g++ @commonFlags @ExtraFlags @Sources -o $output
    if ($LASTEXITCODE -ne 0) {
        throw "Compile failed: $Name"
    }

    if (!$BuildOnly) {
        & $output
        if ($LASTEXITCODE -ne 0) {
            throw "Test failed: $Name"
        }
    }
}

Set-Location $root
New-Item -ItemType Directory -Force $buildDir | Out-Null

try {
    $hlsSource = "hls\point_kinetics_hls\point_kinetics.cpp"
    $ignoreHlsPragmas = @("-Wno-unknown-pragmas")

    Invoke-NativeTarget "HLS smoke test" "hls_smoke" `
        @($hlsSource, "hls\point_kinetics_hls\tb_point_kinetics.cpp") $ignoreHlsPragmas
    Invoke-NativeTarget "PC/HLS parity" "pc_hls_parity" `
        @($hlsSource, "tests\pc_hls_parity.cpp") $ignoreHlsPragmas
    Invoke-NativeTarget "PC/HLS fixed-seed fuzz parity" "pc_hls_fuzz_parity" `
        @($hlsSource, "tests\pc_hls_fuzz_parity.cpp") $ignoreHlsPragmas
    Invoke-NativeTarget "Physics regression" "physics_regression" `
        @("tests\physics_regression.cpp")
    Invoke-NativeTarget "CATS adiabatic Doppler-feedback benchmark" "cats_doppler_feedback" `
        @("tests\cats_doppler_feedback_benchmark.cpp")
    Invoke-NativeTarget "Analytic iodine-xenon regression" "poison_analytic" `
        @("tests\poison_analytic_regression.cpp")
    Invoke-NativeTarget "ARM CSV formatting regression" "arm_csv_format" `
        @("tests\arm_csv_format_regression.cpp")
    Invoke-NativeTarget "PC solver build" "pc_solver" `
        @("pc_sim\pc_solver.cpp") -BuildOnly

    Write-Host "All native suites passed."
}
finally {
    if (Test-Path $buildDir) {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }
}
