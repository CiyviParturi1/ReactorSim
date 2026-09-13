# Chapter 7 physical ZedBoard results

Recorded UART data in this directory produced this report.

## Physical acceptance matrix

| test | rows | latest_epoch_rows | restarts | DATA_START | 23_fields | finite | monotonic_time | engine_valid | malformed | missed_frames |
|---|---|---|---|---|---|---|---|---|---|---|
| m0_1000_frames | 1051 | 1051 | 0 | False | True | True | True | True | 0 | 0 |
| m1_1000_frames | 1051 | 1051 | 0 | False | True | True | True | True | 0 | 0 |
| m2_1000_frames | 1050 | 1050 | 0 | False | True | True | True | True | 0 | 1 |
| preset_0_parity | 60 | 59 | 1 | False | True | True | False | True | 0 | 0 |
| preset_1_parity | 60 | 59 | 1 | False | True | True | False | True | 0 | 0 |
| preset_2_parity | 60 | 59 | 1 | False | True | True | False | True | 0 | 0 |
| reset_power_acceptance | 1231 | 310 | 5 | False | True | True | False | True | 0 | 0 |
| rod_insertion | 1801 | 1800 | 1 | False | True | True | False | True | 0 | 0 |
| rod_withdrawal | 1803 | 1800 | 2 | False | True | True | False | True | 0 | 0 |
| uart_command_acceptance | 250 | 30 | 6 | False | True | True | False | True | 0 | 0 |
| xenon_36h | 1327 | 1323 | 2 | False | True | True | False | True | 0 | 1 |


## Measured FPGA execution and compression

| test | frames | achieved_factor_mean | host_observed_factor_mean | substep_min_s | substep_mean_s | substep_median_s | substep_p95_s | substep_max_s | frame_p95_s | missed_frames |
|---|---|---|---|---|---|---|---|---|---|---|
| m0_1000_frames | 1051 | 1.0008560770694577 | 1.0064724728772056 | 1.113e-06 | 1.113e-06 | 1.113e-06 | 1.113e-06 | 1.113e-06 | 0.10999999999999943 | 0 |
| m1_1000_frames | 1051 | 9.999985090390105 | 10.06428048350412 | 1.113e-06 | 1.113e-06 | 1.113e-06 | 1.113e-06 | 1.113e-06 | 0.10999999999999943 | 0 |
| m2_1000_frames | 1050 | 999.3627278657143 | 1005.6539261233806 | 1.11e-06 | 1.110002857142857e-06 | 1.11e-06 | 1.11e-06 | 1.113e-06 | 0.10999999999999943 | 1 |
| preset_0_parity | 60 | 1.0008422711864406 | 1.0067902787240668 | 1.113e-06 | 1.1130169491525423e-06 | 1.113e-06 | 1.113e-06 | 1.114e-06 | 0.11000000000000032 | 0 |
| preset_1_parity | 60 | 1.000841559322034 | 1.0068437053861465 | 1.113e-06 | 1.1130169491525423e-06 | 1.113e-06 | 1.113e-06 | 1.114e-06 | 0.11000000000000032 | 0 |
| preset_2_parity | 60 | 1.0008409491525423 | 1.0118123849595497 | 1.113e-06 | 1.1130169491525423e-06 | 1.113e-06 | 1.113e-06 | 1.114e-06 | 0.10999999999999999 | 0 |
| reset_power_acceptance | 1231 | 1.0008528580645162 | 1.0060930311197496 | 1.113e-06 | 1.1130032258064515e-06 | 1.113e-06 | 1.113e-06 | 1.114e-06 | 0.10999999999999943 | 0 |
| rod_insertion | 1801 | 1.0008551511111112 | 1.0064584663550449 | 1.113e-06 | 1.1130005555555555e-06 | 1.113e-06 | 1.113e-06 | 1.114e-06 | 0.10999999999999943 | 0 |
| rod_withdrawal | 1803 | 1.0008552183333332 | 1.006492731820884 | 1.113e-06 | 1.1130005555555555e-06 | 1.113e-06 | 1.113e-06 | 1.114e-06 | 0.10999999999999943 | 0 |
| uart_command_acceptance | 250 | 1.0008284333333333 | 1.0032510584450138 | 1.113e-06 | 1.1130333333333334e-06 | 1.113e-06 | 1.113e-06 | 1.114e-06 | 0.10900000000000176 | 0 |
| xenon_36h | 1327 | 980.6666175404384 | 986.7522922560659 | 1.11e-06 | 1.1100597127739985e-06 | 1.11e-06 | 1.11e-06 | 1.114e-06 | 0.10999999999999943 | 1 |


## Hardware iodine-xenon run

| duration_after_scram_h | iodine_at_xenon_peak | maximum_xenon_ratio | xenon_peak_time_h | maximum_xenon_worth_dollars | return_within_1pct_h | maximum_critical_rod_position |
|---|---|---|---|---|---|---|
| 36.02803038194445 | 0.466073 | 1.503229 | 7.389139323055556 | -1.4378571428571427 | 20.805805989722224 | 0.857886 |


## PC-to-FPGA parity

Recorded parity reports: 6.

| report | pass | points | worst_rmse | worst_max_abs |
|---|---|---|---|---|
| preset_0_parity | True | 50 | 5.96000000463448e-08 | 5.96000000463448e-08 |
| preset_1_parity | True | 50 | 4.154999999617104e-07 | 5.885117388970684e-07 |
| preset_2_parity | True | 50 | 8.590192101779053e-07 | 2.4963768510133377e-06 |
| rod_insertion_parity | True | 1800 | 9.521341531726376e-06 | 6.246952136734762e-05 |
| rod_withdrawal_parity | True | 1800 | 4.69731657848477e-05 | 0.00012331075947713543 |
| xenon_36h_parity | True | 1323 | 1.2587451427539938e-05 | 1.6740238492740644e-05 |


Hardware xenon graph: `figures/hardware_xenon.png`.
