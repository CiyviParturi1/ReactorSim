# FPGA point-kinetics reactor simulator

This project runs one point-kinetics model on a PC and a ZedBoard. The model
couples neutron power, six delayed-neutron groups, fuel and coolant
temperatures, decay heat, iodine-xenon poisoning, control rods, and SCRAM.

The implementation is small. A shared, allocation-free C++ core
contains the reactor state and numerical update. The PC program calls it
directly. Vitis HLS turns the same update into an AXI4-Lite peripheral for the
Zynq-7000.

This is an educational simulator. It is useful for control experiments,
numerical-method demonstrations, and comparisons between PC and FPGA results.
It is not safety-analysis code, a plant simulator, or an operator-training
system.

## Start on a PC

Install Python packages and launch the simulator from the repository root:

```powershell
python -m pip install -r requirements.txt
python pc_sim\pc_sim_launcher.py
```

The launcher compiles `pc_solver.cpp`, starts the solver, and connects it to
the Matplotlib dashboard. It stops if the build fails, so an old executable
cannot hide a compiler error.

The dashboard can also read ZedBoard telemetry over UART. Run the plotter
directly to choose a serial port:

```powershell
python pc_sim\plot_realtime.py --source serial --port COM7 --baud 115200
```

## Repository map

| Path | Purpose |
| --- | --- |
| `common/point_kinetics_core.h` | Reactor state, feedback, controls, and numerical update |
| `common/point_kinetics_config.h` | Constants shared by PC, HLS, and ARM builds |
| `hls/point_kinetics_hls/` | HLS wrapper, testbench, and component configuration |
| `pc_sim/` | PC solver, launcher, and live dashboard |
| `vitis/pk_app/src/` | Standalone Cortex-A9 application |
| `vivado/` | Block design, IP configuration, constraints, and project metadata |
| `tests/` | Native physics, parity, fuzz, and telemetry regressions |
| `experiments/` | Repeatable campaigns, analysis scripts, and retained results |
| `scripts/` | FPGA rebuild and validation commands |
| [`docs/architecture.md`](docs/architecture.md) | Runtime and build diagrams |

The PC and FPGA paths both execute `pk::ReactorState`. The ARM application
handles timing, commands, and telemetry; it does not contain a second physics
solver.

## Model

The core uses simple methods chosen for predictable FPGA cost:

- semi-implicit Euler for stiff prompt neutron power;
- explicit precursor, thermal, and three-group decay-heat updates;
- one exponential iodine-xenon batch update per output frame;
- a sinusoidal integral rod-worth curve with zero differential worth at both
  travel limits.

Thermal power is `0.934 * neutron_power + decay_heat`. The three decay groups
sum to 0.066 at full-power equilibrium. Every reset starts with the external
source off. The operator may set it between 0 and 0.01 neutron-power units per
second.

The presets are qualitative contrasts:

| Mode | Description | Requested time factor | Physics step |
| --- | --- | ---: | ---: |
| M0 | PWR-SMR-like | 1x | 0.0001 s |
| M1 | RBMK-like | 10x | 0.001 s |
| M2 | Loss of cooling | 1000x | 0.002 s |

Custom factors use `min(0.0001 * factor, 0.002)` seconds per step. A 100 ms
output frame has a 100,000-step limit. Telemetry reports the achieved factor,
so a missed deadline cannot appear as successful time compression.

SCRAM latches a reactivity penalty of `-0.07665`. Rod commands remain blocked
until the operator clears the trip. A non-finite state or a step near the
semi-implicit pole latches a numerical fault and marks the engine output
invalid.

The full parameter set and equations live next to the implementation in
[`point_kinetics_config.h`](common/point_kinetics_config.h) and
[`point_kinetics_core.h`](common/point_kinetics_core.h).

## Controls

The PC and UART paths accept the same commands:

| Command | Action |
| --- | --- |
| `+`, `-` | Move the rod target by 0.01 |
| `W <0..1>` | Set the normalized rod target |
| `R` | SCRAM |
| `K` | Clear the SCRAM trip |
| `P <power>` | Reset at a power fraction |
| `C0`, `C1`, `C2` | Select a plant preset and reset |
| `M0`, `M1`, `M2` | Select a timing mode |
| `T <factor>` | Set a custom time factor |
| `S <0..0.01>` | Set the external neutron source |

In the dashboard, `E` saves a quick CSV and PNG capture, `S` opens Save As,
`L` loads a saved session, and `O` overlays a CSV reference trace.

## Tests

Run every native suite with one command:

```powershell
.\scripts\run_native_tests.ps1
```

The runner builds in `build/native-tests` and removes its executables when it
finishes. It checks:

- HLS smoke behavior and PC-to-HLS state parity;
- 10,000 fixed-seed command frames across the PC and HLS interfaces;
- equilibrium, clock precision, decay heat, poison behavior, and an
  independent double-precision RK4 comparison;
- the published CATS Thermal Reactor IV adiabatic Doppler transient;
- iodine-xenon batches against the analytic constant-power solution;
- ARM CSV output for finite values, NaN, infinity, and large values;
- strict compilation of the PC solver.

For the long HLS clock test, define `POINT_KINETICS_LONG_TEST` when compiling
the HLS testbench.

## FPGA build

The hardware build requires AMD Vivado and Vitis 2025.2, plus the ZedBoard
board definition `avnet.com:zedboard:part0:1.4`.

First package the HLS IP:

```powershell
cd hls\point_kinetics_hls
v++ --compile --mode hls --config hls_config.cfg --work_dir point_kinetics_hls
cd ..\..
vivado -mode batch -source scripts\refresh_hls_ip.tcl
```

Then build the bitstream, export the hardware platform, and build the ARM
application:

```powershell
vivado -mode batch -source scripts\build_vivado_bitstream.tcl
vitis -s scripts\build_vitis.py
```

The Vitis build reads `build/hardware/pk.xsa`. This prevents the application
from using a stale register map.

To reconstruct the Vivado project in an empty directory:

```powershell
New-Item -ItemType Directory -Force build\vivado | Out-Null
Set-Location build\vivado
vivado -mode batch -source ..\..\scripts\recreate_vivado_project.tcl
```

Set `PK_BOARD_REPO` first if Vivado cannot find the board files through
`APPDATA`.

## Validation record

The retained ZedBoard campaign used a 100 MHz design and 115200-baud UART.
It covers three timing modes, reset and command acceptance, rod transients,
36 hours of simulated post-SCRAM xenon behavior, and six PC-to-FPGA parity
cases. The campaign found no malformed rows, non-finite values, or serial
disconnects. One 100 ms frame miss was recorded in the 1000x timing run.

The exact measurements, artifact hashes, and limitations are in the
[physical campaign summary](experiments/results/chapter7_fpga_20260713/summary.md).
The [PC campaign](experiments/README.md) and
[accident-character demonstrations](experiments/results/accident_pc_20260715/summary.md)
have their own reproduction commands.

Raw PC traces can be regenerated from source. Raw UART captures cannot. They
record what the physical board emitted and support the validation and parity
reports, so they remain under `experiments/results/` with the figures.

## Repository hygiene

Git keeps sources, project metadata, tests, compact reports, figures, and
physical-board evidence. It ignores compiler output, HLS work directories,
Vivado runs, Vitis workspaces, bitstreams, hardware exports, logs, journals,
IDE state, and Python caches.

Do not commit a generated executable or tool workspace. Run the tests or FPGA
build to recreate it. Do not delete a dated result directory unless its data
can be reproduced without the original hardware session.

## Limits

The model has no spatial flux, coolant pressure or inventory, boiling, void
fraction, cladding temperature, core uncovering, chemistry, protection-system
logic, or plant-specific control-bank calibration. Agreement between the PC,
HLS, and FPGA implementations proves implementation consistency. It does not
validate the model against a real reactor.
