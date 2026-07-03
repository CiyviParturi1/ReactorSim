# FPGA Point-Kinetics Reactor Simulator

> **Development status:** This project is under active development. Interfaces,
> hardware behavior, and build instructions may change.

This repository contains a point-kinetics reactor simulation targeting a
ZedBoard (`xc7z020clg484-1`). The simulation core is implemented as Vitis HLS
IP, integrated into a Vivado block design, and controlled by a standalone
Vitis application. A PC implementation is included for development and
visualization without FPGA hardware.

## Repository layout

- `hls/point_kinetics_hls/` — HLS source, testbench, and component configuration.
- `vivado/` — Vivado project metadata, block design, IP configuration, and constraints.
- `vitis/pk_app/src/` — standalone Zynq application source.
- `pc_sim/` — C++ PC simulator and Python launcher/plotter.
- `common/point_kinetics_core.h` — canonical allocation-free physics core used
  by the PC simulator and HLS top function.
- `tests/` — native PC-to-HLS parity and regression scenarios.
- `scripts/export_vivado_project.tcl` — exports and sanitizes the current Vivado project.
- `scripts/recreate_vivado_project.tcl` — recreates the Vivado project from versioned sources.

Generated synthesis runs, implementation runs, HLS output, bitstreams, XSA
files, IDE state, and build products are excluded by `.gitignore`.

## Requirements

- AMD Vivado and Vitis 2025.2
- ZedBoard board definition: `avnet.com:zedboard:part0:1.4`
- Python 3 and a C++17 compiler for the PC simulator

The reconstruction script normally finds the Windows board store through
`APPDATA`. If the board files are elsewhere, set `PK_BOARD_REPO` to the
directory containing the board repository before running Vivado:

```powershell
$env:PK_BOARD_REPO = "C:\path\to\xilinx_board_store"
```

## Recreate the Vivado project after cloning

The Vivado block design uses the packaged point-kinetics HLS IP. Package that
IP first:

```powershell
cd hls\point_kinetics_hls
vitis-run --mode hls --config hls_config.cfg --package
cd ..\..
```

Create the reconstructed project in an empty, ignored build directory:

```powershell
New-Item -ItemType Directory -Force build\vivado | Out-Null
cd build\vivado
vivado -mode batch -source ..\..\scripts\recreate_vivado_project.tcl
```

The resulting project is `build/vivado/pk/pk.xpr`. The script restores the
block design, constraints, HLS IP repository, wrapper, and Vivado run
configuration. It does not automatically launch synthesis or implementation.

For ordinary development, continue using the existing `vivado/pk.xpr`; the
reconstruction command is mainly for a fresh clone or a clean-room test.

## Refresh the exported Vivado script

From the repository root:

```powershell
vivado -mode batch -source scripts\export_vivado_project.tcl
```

The exporter updates `scripts/recreate_vivado_project.tcl` and removes
machine-specific paths and generated checkpoints from it.

You do **not** need to run this before every commit. Run it when a commit
changes the Vivado project structure, including:

- the block design or its IP configuration;
- source or constraint files added to or removed from the project;
- the target part, board, filesets, run settings, or IP repository paths;
- the HLS IP interface when that requires updating the block design.

Do not run it for changes limited to C/C++, Python, application logic, comments,
or documentation. Before committing a structural Vivado change, refresh the
script and review its diff:

```powershell
vivado -mode batch -source scripts\export_vivado_project.tcl
git diff -- scripts\recreate_vivado_project.tcl
```

Commit the updated project sources and reconstruction script together.

## Run the PC simulator

From the repository root:

```powershell
python pc_sim\pc_sim_launcher.py
```

The launcher builds `pc_sim/taylor_solver.cpp` with a C++17 compiler and starts
the real-time plotter. A failed build aborts the launch instead of falling back
to a stale executable.

## Model and timing policy

The PC simulator, native tests, HLS top, and Vitis application use the same
named timing policy:

| Mode | Simulated/wall factor | Physics step |
| --- | ---: | ---: |
| REALTIME | 1x | 0.00001 s |
| TRAINING | 10x | 0.0001 s |
| XENON | 1000x | 0.002 s (stability limit) |

Custom factors use `min(0.00001 * factor, 0.002)` seconds per physics step.
Each 10 ms output frame is capped at 100,000 substeps. If a custom request
exceeds that budget, output column 9 reports the achieved factor rather than
the unattainable requested factor. PC pacing uses a steady-clock deadline and
sleeps only for the part of the 10 ms frame left after computation.

Thermal power is `0.934 * neutron_power + decay_heat`. Three continuously
evolved decay groups contribute 0.066 at unit-power equilibrium, making total
thermal power exactly 1.0 initially. Their state is continuous across SCRAM
and decays as fission power falls. The thermal and feedback equations remain a
lumped educational model, rod worth is linear, and full rod travel takes 100
simulated seconds.

## Native regression tests

From the repository root, build with strict warnings and run both suites:

```powershell
g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -Wno-unknown-pragmas hls\point_kinetics_hls\point_kinetics.cpp hls\point_kinetics_hls\tb_point_kinetics.cpp -o hls\point_kinetics_hls\tb_point_kinetics_test.exe
.\hls\point_kinetics_hls\tb_point_kinetics_test.exe

g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -Wno-unknown-pragmas hls\point_kinetics_hls\point_kinetics.cpp tests\pc_hls_parity.cpp -o tests\pc_hls_parity.exe
.\tests\pc_hls_parity.exe
```

The parity suite covers equilibrium, rod movement, SCRAM and continuous decay
heat, reset, all plant presets, non-finite controls, and core/HLS state parity.

## Version-control policy

Commit source code, tests, constraints, block-design files, IP configuration,
project/component metadata, and reconstruction scripts. Do not commit generated
HLS output, Vivado runs, checkpoints, bitstreams, hardware exports, Vitis build
directories, logs, or local IDE state.
