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

### Control Rod Worth Calibration
- **Baselines:** Regulating rod limits are set to `rho_rod_min = -0.00735f` ($-1.05\$$) and `rho_rod_max = 0.00245f` ($+0.35\$$) under Mode 0 and Mode 2.
- **Equilibrium:** The critical rod position is located at exactly **75% withdrawn** (`0.75`). Below 75% power slowly decreases, and above 75% power increases until temperature feedback stabilizes it.

### Safety Latching (SCRAM & Reset Trip)
- **SCRAM:** Applies a permanent, latched emergency shutdown state (`scram_active = true`), adding a safety reactivity penalty of $-10.95\$$ (`-0.07665f`).
- **Safety Interlock:** Normal regulating rod controls are disabled/blocked while `scram_active` is true.
- **Trip Reset:** The operator must issue a Reset Trip command/button (`K`/`k` or GUI "Clear SCRAM") to clear the interlock, after which rods may be slowly withdrawn again to restart the reactor.

### Normalized & Batched Poison Updates
- **Normalized Ratios:** Iodine-135 and Xenon-135 are tracked as normalized ratios around $1.0$ (instead of absolute atom concentrations of $\approx 2 \times 10^7$) to prevent 32-bit floating-point underflow.
- **Analytical Batching:** Poisons are integrated analytically over each output frame using average power and exponential factors (`expf`), eliminating numerical integration drift and precision freezes.

## Mathematical Model and Numerical Solver

The simulation core solves a coupled system of differential equations describing point kinetics, heat transfer, decay heat, and Xenon/Iodine poisons.

### 1. Coupled Differential Equations

#### Point Kinetics (Neutron Power & Precursors)
Prompt neutron power $n(t)$ and 6 delayed neutron precursor groups $C_i(t)$:
$$\frac{dn}{dt} = \frac{\rho(t) - \beta}{L} n(t) + \sum_{i=1}^6 \lambda_i C_i(t) + Q$$
$$\frac{dC_i}{dt} = \frac{\beta_i}{L} n(t) - \lambda_i C_i(t)$$

#### Thermal Hydraulics (Two-Node Heat Transfer)
Lumped fuel temperature $T_f(t)$ and coolant temperature $T_c(t)$:
$$\frac{dT_f}{dt} = K_{\text{heat}} P_{\text{th}}(t) - \gamma (T_f(t) - T_c(t))$$
$$\frac{dT_c}{dt} = \gamma (T_f(t) - T_c(t)) - \gamma_c (T_c(t) - T_m)$$
where:
- $P_{\text{th}}(t) = (1 - f_{\text{decay}}) n(t) + H_{\text{decay}}(t)$ is the total thermal power.
- $H_{\text{decay}}(t) = \sum_{j=1}^3 D_j(t)$ is the decay heat contribution.

#### Decay Heat (Three Groups)
Continuous decay heat groups $D_j(t)$:
$$\frac{dD_j}{dt} = \lambda_{\text{decay}, j} \left( f_j n(t) - D_j(t) \right)$$

#### Xenon-135 and Iodine-135 Poisons (Normalized)
Normalized Iodine ratio $I_{\text{norm}}(t)$ and Xenon ratio $Xe_{\text{norm}}(t)$:
$$\frac{dI_{\text{norm}}}{dt} = \lambda_I \left( n(t) - I_{\text{norm}}(t) \right)$$
$$\frac{dXe_{\text{norm}}}{dt} = \frac{\gamma_{Xe} \Sigma_f n(t) + \lambda_I I_{\text{ref}} I_{\text{norm}}(t)}{Xe_{\text{ref}}} - (\lambda_{Xe} + \sigma_a n(t)) Xe_{\text{norm}}(t)$$

---

### 2. Numerical Discretization and Solver Methods

To run efficiently on FPGA hardware without sacrificing numerical stability, different integration methods are used:

#### Point Kinetics Solver (Semi-Implicit Euler)
Because prompt point-kinetics equations are highly stiff (due to prompt lifetime $L \approx 2 \times 10^{-5}$ seconds), standard explicit Euler would require sub-nanosecond timesteps. Instead, a **semi-implicit Euler discretization** is used:
- Precursors are integrated explicitly:
  $$C_i(t + h) = C_i(t) + h \left[ \frac{\beta_i}{L} n(t) - \lambda_i C_i(t) \right]$$
- Prompt power is solved semi-implicitly:
  $$n(t + h) = \frac{n(t) + h \left[ \sum_{i=1}^6 \lambda_i C_i(t) + Q \right]}{1 - h \frac{\rho(t + h) - \beta}{L}}$$
This formulation is unconditionally stable for negative reactivity insertions and preserves prompt-jump kinetics.

#### Thermal & Decay Heat Solver (Explicit Euler)
Thermal temperatures ($T_f, T_c$) and decay groups ($D_j$) are integrated using standard **explicit Euler integration**:
$$T_f(t + h) = T_f(t) + h \frac{dT_f}{dt}$$
$$T_c(t + h) = T_c(t) + h \frac{dT_c}{dt}$$
$$D_j(t + h) = D_j(t) + h \frac{dD_j}{dt}$$

#### Poison Solver (Analytical Exponential Batch Update)
To prevent floating-point underflow at long timescales during shutdowns, Iodine and Xenon ratios are updated analytically over each output frame interval $\Delta t = h \cdot \text{substeps}$:
- **Iodine-135:**
  $$I_{\text{norm}}(t + \Delta t) = I_{\text{norm}}(t) + (n_{\text{avg}} - I_{\text{norm}}(t)) \left( 1 - e^{-\lambda_I \Delta t} \right)$$
- **Xenon-135:**
  $$Xe_{\text{norm}}(t + \Delta t) = Xe_{\text{norm}}(t) + (Xe_{\text{eq, norm}} - Xe_{\text{norm}}(t)) \left( 1 - e^{-\text{sink} \cdot \Delta t} \right)$$
  where:
  - $\text{sink} = \lambda_{Xe} + \sigma_a n_{\text{avg}}$
  - $Xe_{\text{eq, norm}} = \frac{\gamma_{Xe} \Sigma_f n_{\text{avg}} + \lambda_I I_{\text{ref}} I_{\text{norm}}(t + \Delta t)}{\text{sink} \cdot Xe_{\text{ref}}}$

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
