param(
    [string]$Script = 'build_vitis_clean_validation.py'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vitisRoot = 'C:\AMDDesignTools\2025.2\Vitis'
$vivadoRoot = 'C:\AMDDesignTools\2025.2\Vivado'
$env:XILINX_LOCAL_USER_DATA = Join-Path $root 'build\xilinx_user_data'
$env:DTC = Join-Path $vivadoRoot 'bin\dtc.exe'
$env:LOPPER_DTC = $env:DTC
$env:Path = "$vitisRoot\bin;$vivadoRoot\bin;$env:Path"
New-Item -ItemType Directory -Force -Path $env:XILINX_LOCAL_USER_DATA | Out-Null

$log = Join-Path $root 'build\fpga_validation\vitis_clean_validation_wrapper.log'
& "$vitisRoot\bin\vitis.bat" -s (Join-Path $root "scripts\$Script") 2>&1 |
    Tee-Object -FilePath $log
exit $LASTEXITCODE
