# Chapter 7 reproducible campaign

This directory contains the non-interactive PC-side campaign for Chapter 7. It
uses the canonical shared physics core in `common/point_kinetics_core.h`, saves
raw CSV files before analysis, captures the host/compiler/source metadata, and
generates a Markdown summary plus figures.

Run it from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\experiments\run_campaign.ps1
```

An output directory is created under `experiments/results/`. To choose a stable
directory name, pass `-ResultsDirectory`, for example:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\experiments\run_campaign.ps1 `
  -ResultsDirectory experiments\results\chapter7_pc_20260711
```

The campaign currently executes:

* four PWR-SMR-like steady-state powers for 300 simulated seconds;
* rod withdrawal and insertion transients;
* fast and 7200-second SCRAM/decay-heat responses;
* a 36-hour post-SCRAM iodine-xenon run using the XENON batching policy;
* the same `5e-4` reactivity insertion across all three qualitative presets;
* double-precision RK4 comparison and timestep convergence at the requested steps;
* 1000 raw physics-kernel timing frames for REALTIME, TRAINING, and XENON modes.

The performance factor is labelled **kernel throughput factor**. It measures
raw physics-kernel work divided by kernel wall time; it is not the complete
simulator compression factor. The interpretation is that the PC kernel can
sustain the requested 1x, 10x, and 1000x modes when the 100 ms deadline is not
missed.

The driver also captures the existing native HLS smoke, PC/core-HLS parity, and
independent physics regression output in `native_tests.txt`. The parity suite
prints maximum absolute differences for `N`, all six precursor groups, `Tf`,
`Tc`, iodine, xenon, total reactivity, and decay heat.

The generated `metadata.json` records the Git revision, branch, PC, operating
system, compiler flags, numerical settings, target FPGA clock, and hardware
status. `summary.md` and `summary.json` are derived products; the CSV files are
the primary evidence.

The following claims remain deliberately out of scope until the board and AMD
tools are available: measured FPGA execution time, achieved FPGA compression,
UART reliability, GUI hardware operation, RTL co-simulation, and PC-FPGA parity.
PC/core-HLS parity is still covered by the existing native test, but it is
implementation consistency rather than independent physical validation.

## Accident-character presentation campaign

The deterministic presentation campaign compares the RBMK-like and
loss-of-cooling presets with the modern PWR-SMR-like preset. Run it from the
repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\experiments\run_accident_campaign.ps1
```

To reproduce a named result directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\experiments\run_accident_campaign.ps1 `
  -ResultsDirectory experiments\results\accident_pc_YYYYMMDD
```

The campaign generates four raw CSV traces, a machine-readable scenario
definition, metadata, automated consistency checks, SHA-256 checksums, a
Markdown/JSON summary, and Chernobyl-style and TMI-style comparison graphs.
All checks must pass or the campaign exits with an error.

These are deliberately qualitative presentation surrogates. The Chernobyl
schedule imposes its AZ-5/shutdown-effect timing. The TMI schedule represents
coolant loss and core uncovery by staged heat-transfer parameters because the
shared model does not solve pressure, coolant inventory, boiling, or core level.

The three-preset section is titled `სამი რეაქტორული წინასწარი კონფიგურაციის
პასუხი ერთნაირ რეაქტიულობის ზემოქმედებაზე`. Its comparison includes both the
feedback-coefficient differences and the different active cooling-removal
conditions of the presets.
