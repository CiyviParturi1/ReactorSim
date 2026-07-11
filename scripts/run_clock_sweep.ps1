param(
    [double[]]$Periods = @(8, 7, 6, 5)
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vivado = 'C:\AMDDesignTools\2025.2\Vivado\bin\vivado.bat'
$env:XILINX_LOCAL_USER_DATA = Join-Path $root 'build\xilinx_user_data'
New-Item -ItemType Directory -Force -Path $env:XILINX_LOCAL_USER_DATA | Out-Null

foreach ($period in $Periods) {
    $env:PK_SWEEP_PERIOD = [string]$period
    $log = Join-Path $root ("build\fpga_validation\clock_sweep_{0}ns.log" -f $period)
    & $vivado -mode batch -source (Join-Path $root 'scripts\clock_sweep.tcl') 2>&1 |
        Tee-Object -FilePath $log
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Vivado failed while evaluating ${period} ns; stopping the sweep."
        break
    }
    $metrics = Join-Path $root ("build\fpga_validation\clock_sweep_{0}ns\metrics.txt" -f $period)
    if (!(Test-Path $metrics) -or ((Get-Content $metrics -Raw) -notmatch 'timing_closed=(True|1)')) {
        Write-Host "Timing closure failed at ${period} ns; stopping the sweep."
        break
    }
}
