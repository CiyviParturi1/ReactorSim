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
the real-time plotter.

## Version-control policy

Commit source code, tests, constraints, block-design files, IP configuration,
project/component metadata, and reconstruction scripts. Do not commit generated
HLS output, Vivado runs, checkpoints, bitstreams, hardware exports, Vitis build
directories, logs, or local IDE state.
