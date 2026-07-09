# Run the documented native regression suites from the repository root.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Suite {
    param(
        [string]$Name,
        [string]$Compile,
        [string]$Exe
    )
    Write-Host "==> $Name"
    Invoke-Expression $Compile
    if ($LASTEXITCODE -ne 0) {
        throw "Compile failed: $Name"
    }
    & $Exe
    if ($LASTEXITCODE -ne 0) {
        throw "Test failed: $Name"
    }
}

Invoke-Suite -Name "HLS smoke test" `
    -Compile "g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -Wno-unknown-pragmas hls\point_kinetics_hls\point_kinetics.cpp hls\point_kinetics_hls\tb_point_kinetics.cpp -o hls\point_kinetics_hls\tb_point_kinetics_test.exe" `
    -Exe ".\hls\point_kinetics_hls\tb_point_kinetics_test.exe"

Invoke-Suite -Name "PC/HLS parity" `
    -Compile "g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -Wno-unknown-pragmas hls\point_kinetics_hls\point_kinetics.cpp tests\pc_hls_parity.cpp -o tests\pc_hls_parity.exe" `
    -Exe ".\tests\pc_hls_parity.exe"

Invoke-Suite -Name "Physics regression" `
    -Compile "g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror tests\physics_regression.cpp -o tests\physics_regression.exe" `
    -Exe ".\tests\physics_regression.exe"

Write-Host "==> PC solver build"
g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror pc_sim\pc_solver.cpp -o tests\pc_solver_build_test.exe
if ($LASTEXITCODE -ne 0) {
    throw "Compile failed: PC solver build"
}

Write-Host "All native suites passed."
