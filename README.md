# FPGA Point-Kinetics Reactor Simulator

> **Development status:** Hardware-validated release candidate. The PC and FPGA
> implementations share one physics core and pass the documented native, HLS,
> Vivado, Vitis, and recorded physical-ZedBoard checks. Manual GUI/GPIO and
> extended endurance evidence remain useful release work.

This repository contains a point-kinetics reactor simulation targeting a
ZedBoard (`xc7z020clg484-1`). The simulation core is implemented as Vitis HLS
IP, integrated into a Vivado block design, and controlled by a standalone
Vitis application. A PC implementation is included for development and
visualization without FPGA hardware.

## Intended use and validation claim

This project represents a simplified, zero-dimensional nuclear-reactor
kinetics and control-response simulator for introductory control-system
research, numerical-method demonstrations, and student intuition training. It
captures the qualitative coupling between neutron power, six delayed-neutron
precursor groups, lumped fuel and coolant temperatures, reduced decay heat,
iodine/xenon poisoning, control-rod motion, and SCRAM insertion.

The project is suitable for:

- learning how reactivity, delayed neutrons, temperature feedback, xenon, and
  control rods interact;
- comparing the same numerical model on a PC and FPGA;
- experimenting with basic supervisory controls inside the documented
  operating envelope.

It is not a plant simulator, safety-analysis code, operator-training
qualification tool, or a substitute for validated neutronics and
thermal-hydraulics software. Numerical agreement between PC, HLS, and FPGA
builds demonstrates implementation consistency; it does not validate the
model against a particular reactor.

## Validated ZedBoard results

The physical campaign was run on a 100 MHz ZedBoard design using COM7 at
115200 baud. The committed [Chapter 7 evidence summary](experiments/results/chapter7_fpga_20260713/summary.md)
is derived from the preserved raw UART logs and records the tested source,
bitstream, XSA, ELF, tool versions, and SHA-256 artifact identities.

| Physical result | Measured outcome |
| --- | --- |
| M0 timing | 1,051 frames; ARM-reported 1.00086x and host-observed 1.00647x; no missed frames |
| M1 timing | 1,051 frames; steady ARM-reported 10.0086x |
| M2 timing | 1,050 frames; steady ARM-reported 1000.305x; one recorded 100 ms-frame miss |
| Reset and safety | Stable 0.1, 0.5, 1.0, and 1.5 power resets; UART command, SCRAM latch, clear-SCRAM, and three preset tests passed |
| Rod transients | Withdrawal and insertion were recorded through 180 simulated seconds with finite, valid engine state |
| Iodine-xenon transient | 36.03 simulated hours after SCRAM; Xe peak 1.503229 at 7.38914 h and peak worth -1.437857 dollars |
| PC-FPGA parity | Six reports pass the established scaled tolerance: three presets, rod withdrawal, rod insertion, and the 36-hour xenon case |

The campaign observed no malformed rows, non-finite values, engine-state
failures, or serial disconnects in the retained automated captures. Intentional
reset and preset commands restart simulated time and are recorded as such in
the acceptance matrix. The [hardware xenon graph](experiments/results/chapter7_fpga_20260713/figures/hardware_xenon.png)
and individual parity reports are included with the results.

## Accident-character demonstrations

The reproducible PC presentation campaign includes simplified Chernobyl-style
and TMI-style scenarios, each compared with the modern PWR-SMR-like preset.
The scenarios reproduce the intended timing and qualitative response; they are
not scientific accident reconstructions or safety analyses.

- [Campaign report](experiments/results/accident_pc_20260715/summary.md)
- [Chernobyl-style comparison graph](experiments/results/accident_pc_20260715/figures/chernobyl_comparison.png)
- [TMI-style comparison graph](experiments/results/accident_pc_20260715/figures/tmi_comparison.png)

Run `experiments/run_accident_campaign.ps1` to rebuild the raw traces, validate
the schedules, regenerate both graphs, run the native regression suites, and
write metadata plus SHA-256 checksums. Equivalent FPGA schedules are planned
after the accident-stage controls are exposed through the shared HLS/AXI path.

## Repository layout

- [`docs/architecture.md`](docs/architecture.md) — runtime, FPGA, build, and
  verification architecture diagrams.
- `hls/point_kinetics_hls/` — HLS source, testbench, and component configuration.
- `vivado/` — Vivado project metadata, block design, IP configuration, and constraints.
- `vitis/pk_app/src/` — standalone Zynq application source.
- `pc_sim/` — C++ PC simulator and Python launcher/plotter.
- `common/point_kinetics_config.h` — constants shared by C++, HLS, and ARM.
- `common/point_kinetics_core.h` — canonical allocation-free physics core used
  by the PC simulator and HLS top function.
- `common/point_kinetics_c.h` — C helpers for ARM telemetry that mirror the
  core plant coefficients and critical-rod formulas.
- `tests/` — native PC-to-HLS parity and regression scenarios.
- `scripts/refresh_hls_ip.tcl` — refreshes the packaged HLS IP in Vivado.
- `scripts/build_vivado_bitstream.tcl` — builds the bitstream, enforces setup
  and hold timing, and exports the XSA.
- `scripts/build_vitis.py` — rebuilds the Vitis platform and ARM application
  from the exported XSA.
- `scripts/export_vivado_project.tcl` — exports and sanitizes the current Vivado project.
- `scripts/recreate_vivado_project.tcl` — recreates the Vivado project from versioned sources.

Generated synthesis runs, implementation runs, HLS output, bitstreams, XSA
files, IDE state, and build products are excluded by `.gitignore`.

## Requirements

- AMD Vivado and Vitis 2025.2
- ZedBoard board definition: `avnet.com:zedboard:part0:1.4`
- Python 3, Matplotlib, and a C++17 compiler for the PC simulator
  (`pip install -r requirements.txt`)
- PySerial when using the plotter directly with FPGA UART output

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
v++ --compile --mode hls --config hls_config.cfg --work_dir point_kinetics_hls
cd ..\..
vivado -mode batch -source scripts\refresh_hls_ip.tcl
```

`vitis-run --package` alone can package an existing synthesis result; it is not
a substitute for the `v++ --compile --mode hls` step above.

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

## Build the FPGA image and ARM application

From the repository root, build and export a timing-verified hardware platform:

```powershell
vivado -mode batch -source scripts\build_vivado_bitstream.tcl
```

This writes the bitstream and reports under `build\hardware` and exports
`build\hardware\pk.xsa`. Rebuild the Vitis platform and standalone application
from that exact XSA:

```powershell
vitis -s scripts\build_vitis.py
```

The second command prevents the ARM executable from being built against a
stale register map or hardware export.

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

The launcher builds `pc_sim/pc_solver.cpp` with a C++17 compiler and starts
the real-time plotter. A failed build aborts the launch instead of falling back
to a stale executable.

## Model and timing policy

The PC simulator, native tests, HLS top, and Vitis application use the same
named timing policy:

| Mode | Requested simulated/wall factor | Physics step |
| --- | ---: | ---: |
| REALTIME | 1x | 0.0001 s |
| TRAINING | 10x | 0.001 s |
| XENON | 1000x | 0.002 s (stability limit) |

Custom factors use `min(0.0001 * factor, 0.002)` seconds per physics step.
Each 100 ms output frame is capped at 100,000 substeps. The application targets
10 Hz telemetry; CSV field 10 (zero-based index 9) reports measured achieved
compression, so HLS or UART overruns are visible rather than silently reported
as nominal speed. If a custom request exceeds that budget, the same field
reports the achieved factor rather than the unattainable requested factor. PC
pacing uses a steady-clock deadline and sleeps only for the part of the 100 ms
frame left after computation.

Thermal power is `0.934 * neutron_power + decay_heat`. Three continuously
evolved decay groups contribute 0.066 at unit-power equilibrium, making total
thermal power exactly 1.0 initially. Their state is continuous across SCRAM
and decays as fission power falls. The reduced groups use 10 s, 300 s, and
15,000 s half-lives, retaining approximately 1.43% decay heat two hours after
an instantaneous shutdown. The thermal and feedback equations remain a lumped
educational model, rod worth follows a sinusoidal S-curve whose differential
worth peaks mid-bank, and full rod travel takes 100 simulated seconds.

### Control Rod Worth Calibration
- **Shape:** Integral worth is $\rho(x) = \rho_{\min} + (\rho_{\max} -
  \rho_{\min})\,(x - \sin 2\pi x / 2\pi)$ for normalized position $x$. The
  endpoints equal the linear baselines below; differential worth is zero at
  both travel ends and peaks mid-bank.
- **Baselines:** The educational full-bank limits are `rho_rod_min = -0.020f`
  and `rho_rod_max = +0.0066667f` in Modes 0 and 2. This range can balance the
  complete modeled differential xenon worth at every supported reset power.
- **Equilibrium:** At full power and reference temperatures, the zero-feedback
  critical position is about **63% withdrawn** in Modes 0 and 2 and about
  **77% withdrawn** in the RBMK-like Mode 1. The displayed critical position
  also includes current xenon and temperature feedback, so it varies during
  transients and at other equilibrium power levels.

### External Neutron Source
- Every reset starts with the source off (`source_q = 0`). The operator can
  apply a constant external neutron source with the `S <value>` UART/GUI
  command, clamped to $[0,\ 0.01]$.
- A subcritical configuration then settles at the source-driven equilibrium
  $n = \Lambda Q / |\rho|$: indicated power rises hyperbolically as rods are
  withdrawn toward criticality. This supports subcritical-multiplication,
  source-range-monitoring, and 1/M critical-position demonstrations.

### Safety Latching (SCRAM & Reset Trip)
- **SCRAM:** Applies a permanent, latched emergency shutdown state (`scram_active = true`), adding a safety reactivity penalty of $-10.95\$$ (`-0.07665f`).
- **Safety Interlock:** Normal regulating rod controls are disabled/blocked while `scram_active` is true.
- **Trip Reset:** The operator must issue a Reset Trip command/button (`K`/`k` or GUI "Clear SCRAM") to clear the interlock, after which rods may be slowly withdrawn again to restart the reactor.
- **Numerical Trip:** If a state reaches the semi-implicit solver's
  positive-reactivity pole, the core latches a numerical fault, inserts
  shutdown reactivity, and reports engine status `0`. Other non-finite or
  out-of-range state checks also latch engine status `0`; their output is
  invalid and requires a full power reset. Clearing SCRAM alone cannot clear a
  numerical fault.

### Normalized & Batched Poison Updates
- **Normalized Ratios:** Iodine-135 and Xenon-135 are tracked relative to their
  full-power reference inventories. This keeps coefficients well scaled; the
  GUI plots these ratios directly rather than renormalizing them to the first
  received sample.
- **Semi-analytical batching:** Poisons are integrated over each output frame
  using average power and stable exponential factors. Iodine is updated
  analytically for constant average power. Xenon then uses the updated iodine
  value over the batch, making the pair an operator-split approximation rather
  than the exact coupled iodine-xenon solution. A small-argument series and
  compensated accumulation prevent cancellation and sub-ULP update loss.

Current poison parameters are:

| Parameter | Value |
| --- | ---: |
| Iodine yield, $\gamma_I$ | 0.061 |
| Direct xenon yield, $\gamma_{Xe}$ | 0.003 |
| Iodine decay constant, $\lambda_I$ | $2.87\times10^{-5}\ \mathrm{s^{-1}}$ |
| Xenon decay constant, $\lambda_{Xe}$ | $2.09\times10^{-5}\ \mathrm{s^{-1}}$ |
| Normalized xenon-burnout coefficient | $5.0\times10^{-5}\ \mathrm{s^{-1}}$ |
| Full-power xenon reactivity worth | -0.020 |

## Mathematical Model and Numerical Solver

The simulation core solves a coupled system of differential equations describing point kinetics, heat transfer, decay heat, and Xenon/Iodine poisons.

### 1. Coupled Differential Equations

#### Point Kinetics (Neutron Power & Precursors)
Prompt neutron power $n(t)$ and 6 delayed neutron precursor groups $C_i(t)$:
$$\frac{dn}{dt} = \frac{\rho(t) - \beta}{L} n(t) + \sum_{i=1}^6 \lambda_i C_i(t) + Q$$
$$\frac{dC_i}{dt} = \frac{\beta_i}{L} n(t) - \lambda_i C_i(t)$$

$Q$ is the external neutron source: zero after every reset and
operator-commandable within $[0, 0.01]$ (see *External Neutron Source* above).

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
Because prompt point-kinetics equations are stiff relative to the thermal and
poison equations, a **semi-implicit Euler discretization** is used:
- Precursors are integrated explicitly:
  $$C_i(t + h) = C_i(t) + h \left[ \frac{\beta_i}{L} n(t) - \lambda_i C_i(t) \right]$$
- Prompt power is solved semi-implicitly:
  $$n_{k+1} = \frac{n_k + h \left[ \sum_{i=1}^6 \lambda_i C_{i,k} + Q \right]}{1 - h \frac{\rho_k - \beta}{L}}$$
  Reactivity $\rho_k$ is evaluated once for the step after applying control-rod
  motion and is held constant during that step.
This formulation is stable for the configured negative-reactivity envelope and
approximates prompt-jump kinetics without requiring a prompt-lifetime timestep.
Positive-reactivity accuracy is verified against an independent
double-precision RK4 regression over the supported training envelope.

#### Thermal & Decay Heat Solver (Explicit Euler)
Thermal temperatures ($T_f, T_c$) and decay groups ($D_j$) are integrated using standard **explicit Euler integration**:
$$T_f(t + h) = T_f(t) + h \frac{dT_f}{dt}$$
$$T_c(t + h) = T_c(t) + h \frac{dT_c}{dt}$$
$$D_j(t + h) = D_j(t) + h \frac{dD_j}{dt}$$

#### Poison Solver (Semi-analytical Exponential Batch Update)
To avoid accumulated first-order Euler error and loss of small floating-point
updates, iodine and xenon ratios are updated over each output frame interval
$\Delta t = h \cdot \text{substeps}$ using average neutron power:
- **Iodine-135:**
  $$I_{\text{norm}}(t + \Delta t) = I_{\text{norm}}(t) + (n_{\text{avg}} - I_{\text{norm}}(t)) \left( 1 - e^{-\lambda_I \Delta t} \right)$$
- **Xenon-135:**
  $$Xe_{\text{norm}}(t + \Delta t) = Xe_{\text{norm}}(t) + (Xe_{\text{eq, norm}} - Xe_{\text{norm}}(t)) \left( 1 - e^{-\text{sink} \cdot \Delta t} \right)$$
  where:
  - $\text{sink} = \lambda_{Xe} + \sigma_a n_{\text{avg}}$
  - $Xe_{\text{eq, norm}} = \frac{\gamma_{Xe} \Sigma_f n_{\text{avg}} + \lambda_I I_{\text{ref}} I_{\text{norm}}(t + \Delta t)}{\text{sink} \cdot Xe_{\text{ref}}}$

The xenon update treats the newly calculated iodine value as constant over the
batch. This is more accurate and stable than the former explicit-Euler poison
update for the accelerated training modes, but it is not the exact coupled
iodine-xenon solution.

## Native regression tests

From the repository root, run the native suites with:

```powershell
.\scripts\run_native_tests.ps1
```

Or build them individually with strict warnings:

```powershell
g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -Wno-unknown-pragmas hls\point_kinetics_hls\point_kinetics.cpp hls\point_kinetics_hls\tb_point_kinetics.cpp -o hls\point_kinetics_hls\tb_point_kinetics_test.exe
.\hls\point_kinetics_hls\tb_point_kinetics_test.exe

g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -Wno-unknown-pragmas hls\point_kinetics_hls\point_kinetics.cpp tests\pc_hls_parity.cpp -o tests\pc_hls_parity.exe
.\tests\pc_hls_parity.exe

g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror tests\physics_regression.cpp -o tests\physics_regression.exe
.\tests\physics_regression.exe
```

The parity suite covers equilibrium, rod movement, SCRAM and continuous decay
heat, reset, all plant presets, non-finite controls, and core/HLS state parity.
The independent physics suite covers low-power equilibrium reachability,
long-duration clock precision, poison precision, the two-hour decay-heat
target, and a transient comparison against a double-precision RK4 solver.

For the extended HLS clock-precision test:

```powershell
g++ -std=c++17 -O2 -DPOINT_KINETICS_LONG_TEST -Wall -Wextra -Wpedantic -Werror -Wno-unknown-pragmas hls\point_kinetics_hls\point_kinetics.cpp hls\point_kinetics_hls\tb_point_kinetics.cpp -o tests\point_kinetics_long.exe
.\tests\point_kinetics_long.exe
```

Also compile the PC front end and Python scripts before release:

```powershell
g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror pc_sim\pc_solver.cpp -o tests\pc_solver_build_test.exe
python -m py_compile pc_sim\plot_realtime.py pc_sim\pc_sim_launcher.py scripts\build_vitis.py
```

## Model scope

This is an intuition trainer and FPGA numerical-method demonstrator, not a
safety-analysis or operator-licensing simulator. The PWR-SMR, RBMK-like, and
cooling-loss presets are qualitative contrasts. They do not model spatial
flux, xenon oscillations, coolant pressure or inventory, boiling and void
fraction, cladding temperature, core uncovering, chemistry, protection-system
logic, or plant-specific control-bank worth. Results outside the tested
training envelope must be treated as invalid rather than as plant predictions.

## Remaining validation and release work

The automated physical acceptance campaign is complete. Before describing the
complete PC/FPGA product as operationally polished, retain or add:

1. manual GPIO switch evidence for SW0, SW1, and SW7;
2. GUI-button equivalence screenshots and a 30-60 minute GUI/UART endurance
   run; and
3. documented provenance and intended qualitative outcomes for each
   educational parameter set.

A fully coupled analytical iodine-xenon update and calibration against a
specific reactor are optional future fidelity improvements. They are not
required for the stated qualitative educational scope, but plant-specific
claims would require both.

## Version-control policy

Commit source code, tests, constraints, block-design files, IP configuration,
project/component metadata, reconstruction scripts, and compact reproducible
physical-test evidence (raw UART logs, metadata, validation summaries, parity
reports, and figures). Do not commit generated HLS output, Vivado runs,
checkpoints, bitstreams, hardware exports, Vitis build directories, local IDE
state, or regenerable derived CSV traces.
