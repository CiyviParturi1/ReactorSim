# Chapter 7 physical ZedBoard campaign

Run these commands from the repository root after programming the validated
100 MHz image and downloading `pk_app_clean.elf`. The capture tool opens the
same UART as the GUI, so do not run it and the GUI at the same time.

Create the dated evidence directory before starting the board session:

```powershell
python experiments\hardware_campaign.py init `
  --results-dir experiments\results\chapter7_fpga_20260713 `
  --board-serial <ZedBoard-serial> --port COM7 --baud 115200
```

The resulting `metadata.json` contains the Git revision, 100 MHz target,
board identity, tool versions, artifact paths, sizes, modification times, and
SHA-256 hashes for the bitstream, XSA, and ELF. Check that its commit is the
intended revision before programming.

## Capture deterministic UART scenarios

Schedules contain commands triggered by simulated time, avoiding a dependence
on hardware compression. A schedule event has exactly one of `at_sim_time_s`
or `at_wall_s`, plus `command` and optional `label`.

```powershell
python experiments\hardware_campaign.py capture `
  --results-dir experiments\results\chapter7_fpga_20260713 `
  --test-name rod_withdrawal --schedule experiments\hardware\rod_withdrawal.json `
  --until-sim-time-s 180 --max-wall-s 240
```

Each test directory contains `uart_raw.txt`, a 23-column `telemetry.csv`,
`command_timeline.csv`, malformed-line evidence, `capture.json`, and
`telemetry_validation.json`. The validation reports frame interval and
per-substep minimum/mean/median/p95/maximum, achieved compression, estimated
missed 100 ms frames, invalid engine state, non-finite values, malformed rows,
and simulation-time reversals.

For a manual GUI or GPIO action, keep a screenshot/photo and append the action
and observed simulated time to `command_timeline.csv`; the following UART
state transition should provide the independently captured result. GPIO actions
must be rising edges: SW0 withdrawal, SW1 insertion, SW7 SCRAM.

Run M0, M1, and M2 as separate 1,000-frame captures (`--max-wall-s 130` is
normally sufficient). The reported `achieved_factor` is measured by the ARM,
not assumed from the requested mode. For the 36-hour xenon run, reset to C0 and
full power, issue SCRAM, select M2, and capture through simulated time
129,610 s (36 h after the 10 s SCRAM event).

## PC–FPGA parity

After recording an identical deterministic PC reference CSV, align it with the
captured FPGA telemetry by simulated time:

```powershell
python experiments\hardware_campaign.py parity `
  --fpga-csv experiments\results\chapter7_fpga_20260713\rod_withdrawal\telemetry.csv `
  --pc-csv experiments\results\chapter7_pc_20260711\rod_withdrawal.csv `
  --output experiments\results\chapter7_fpga_20260713\rod_withdrawal_parity.json
```

The report includes RMSE and maximum absolute difference for N, fuel and
coolant temperature, iodine, xenon, reactivity, decay heat, and rod position.
Its default scaled tolerance is the existing PC/HLS `2e-5` tolerance; compare
the maximum errors with the six-decimal UART quantization allowance.

After all raw evidence and parity reports have been added, generate the final
Chapter 7 Markdown and JSON summary (including the physical acceptance matrix,
timing/compression table, UART reliability data, parity report count, and an
iodine-xenon graph when a test directory is named `xenon...`):

```powershell
python experiments\hardware_campaign.py summary `
  --results-dir experiments\results\chapter7_fpga_20260713
```
