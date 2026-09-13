param(
    [string]$ResultsDirectory = "experiments\results\benchmark_validation_20260907"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not [System.IO.Path]::IsPathRooted($ResultsDirectory)) {
    $ResultsDirectory = Join-Path $root $ResultsDirectory
}
New-Item -ItemType Directory -Force -Path $ResultsDirectory | Out-Null

$buildDirectory = Join-Path $root "build\validation-figures"
New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null
$dopplerExecutable = Join-Path $buildDirectory "cats_doppler_feedback_benchmark.exe"
$poisonExecutable = Join-Path $buildDirectory "poison_analytic_regression.exe"

try {
    & g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror tests\cats_doppler_feedback_benchmark.cpp -o $dopplerExecutable
    if ($LASTEXITCODE -ne 0) { throw "CATS Doppler benchmark compilation failed" }
    & g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror tests\poison_analytic_regression.cpp -o $poisonExecutable
    if ($LASTEXITCODE -ne 0) { throw "Analytic poison regression compilation failed" }

    & $dopplerExecutable --csv (Join-Path $ResultsDirectory "cats_doppler_feedback.csv") `
        --trace (Join-Path $ResultsDirectory "cats_doppler_feedback_trace.csv")
    if ($LASTEXITCODE -ne 0) { throw "CATS Doppler benchmark failed" }
    & $poisonExecutable --csv (Join-Path $ResultsDirectory "poison_analytic.csv")
    if ($LASTEXITCODE -ne 0) { throw "Analytic poison regression failed" }

    & python experiments\plot_benchmark_report.py --input $ResultsDirectory
    if ($LASTEXITCODE -ne 0) { throw "Report plotting failed" }

    Write-Host "Validation figures: $(Join-Path $ResultsDirectory 'figures')"
}
finally {
    if (Test-Path $buildDirectory) {
        Remove-Item -LiteralPath $buildDirectory -Recurse -Force
    }
}
