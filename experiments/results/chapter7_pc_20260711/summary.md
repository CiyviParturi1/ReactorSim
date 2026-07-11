# Chapter 7 PC campaign results

All values below were computed from the raw CSV files in this directory. The PC campaign does not establish FPGA hardware execution, UART reliability, GUI hardware operation, or PC-FPGA parity.

## Steady-state tests

| file | initial_power | max_power_drift_fraction | max_abs_rho | max_fuel_temperature_drift | max_coolant_temperature_drift |
|---|---|---|---|---|---|
| steady_power_0_10.csv | 0.1000000015 | 5.960999911138885e-07 | 9.313225746e-10 | 3.049999997983832e-05 | 3.049999997983832e-05 |
| steady_power_0_50.csv | 0.5 | 0.0 | 4.656612873e-10 | 0.0 | 0.0 |
| steady_power_1_00.csv | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| steady_power_1_50.csv | 1.5 | 0.0 | 6.98491931e-10 | 0.0 | 0.0 |


## Rod transients

| file | peak_power | time_to_peak_s | min_power | max_fuel_temperature | max_coolant_temperature | final_power |
|---|---|---|---|---|---|---|
| rod_withdrawal.csv | 1.435726047 | 29.90000153 | 0.864507854 | 597.5249023 | 298.4734497 | 1.001561522 |
| rod_insertion.csv | 1.201619983 | 91.40000153 | 0.7088071108 | 545.3863525 | 293.2269897 | 0.9988888502 |


## SCRAM and decay heat

| time_after_scram_s | neutron_power | decay_heat | thermal_power | Tf | Tc |
|---|---|---|---|---|---|
| 0.1 | 0.06505672634 | 0.06583776325 | 0.1266007423 | 542.1486206 | 292.9983826 |
| 1.0 | 0.05081297085 | 0.06437946856 | 0.1118387878 | 534.3823242 | 292.8484192 |
| 10.0 | 0.01823722571 | 0.05339895189 | 0.0704325214 | 466.8731689 | 287.0750122 |
| 60.0 | 0.00390722556 | 0.03879965469 | 0.04244900495 | 310.1142883 | 269.8728333 |
| 600.0 | 1.517028977e-06 | 0.02471639216 | 0.02471780963 | 271.9803162 | 265.7040405 |
| 3600.0 | 4.691667877e-23 | 0.01694077253 | 0.01694077253 | 269.7157593 | 265.4750366 |
| 7200.0 | 7.258726045e-43 | 0.0143401688 | 0.0143401688 | 268.9917603 | 265.4020996 |


## Iodine-xenon transient

| duration_after_scram_h | iodine_max | iodine_max_time_after_scram_s | xenon_max | xenon_max_time_after_scram_s | most_negative_xenon_rho | xenon_return_within_1pct_time_after_scram_s | maximum_critical_rod_position |
|---|---|---|---|---|---|---|---|
| 36.00000216666667 | 1.0 | 0.0 | 1.503221393 | 26600.00195 | -0.01006442774 | 74900.0 | 0.8578808308 |


## Three-preset comparison

| file | peak_power | time_to_peak_s | max_fuel_temperature | max_coolant_temperature | final_power |
|---|---|---|---|---|---|
| preset_0.csv | 1.143623352 | 29.70000076 | 563.0895386 | 295.0187073 | 1.000529885 |
| preset_1.csv | 1.633655071 | 80.0 | 685.1364136 | 322.7713623 | 1.240664721 |
| preset_2.csv | 1.0 | 0.0 | 561.7976685 | 457.663208 | 0.2319813371 |


## RK4 and timestep convergence

| h_s | n_rmse | n_max_abs | n_max_relative | Tf_rmse | Tf_max_abs | Tc_rmse | Tc_max_abs |
|---|---|---|---|---|---|---|---|
| 9.99999974738e-05 | 1.958420735990294e-05 | 0.000571032396396 | 0.0004673260564382969 | 0.0005108042766293709 | 0.000619591543114 | 4.589836197864454e-05 | 7.04871564494e-05 |
| 0.000500000023749 | 9.847252951291182e-05 | 0.0028606852208 | 0.0023411504345205087 | 0.002623281340598957 | 0.00305844491231 | 0.00023031763776888527 | 0.000301408726102 |
| 0.0010000000475 | 0.00019725963608454677 | 0.00571789347275 | 0.004679455359484493 | 0.005262909903586977 | 0.00610351925161 | 0.00046241651477617817 | 0.000590427229895 |
| 0.00200000009499 | 0.00039333623953314147 | 0.0113432606374 | 0.009283188299445907 | 0.010545977232801282 | 0.012195819413 | 0.0009252357930512352 | 0.00116750257047 |


## PC physics-kernel performance

| mode | frames | mean_frame_time_s | median_frame_time_s | std_frame_time_s | p95_frame_time_s | max_frame_time_s | mean_achieved_factor | missed_100ms_deadlines |
|---|---|---|---|---|---|---|---|---|
| REALTIME | 1000 | 1.3379e-05 | 1.32e-05 | 1.3556979445720631e-06 | 1.35e-05 | 4.71e-05 | 7504.41763766245 | 0 |
| TRAINING | 1000 | 1.33567e-05 | 1.32e-05 | 1.454995574605683e-06 | 1.33e-05 | 4.68e-05 | 75166.86561452401 | 0 |
| XENON | 1000 | 0.0006679089 | 0.0006596 | 4.467491509593308e-05 | 0.0006999 | 0.0015223 | 150100.6145006602 | 0 |


## Hardware/HLS work still pending

| Item | Status |
|---|---|
| HLS C simulation | Covered by the native smoke and parity tests |
| HLS synthesis and Vivado implementation | Pending: Vivado/Vitis are not available in this PC session |
| RTL co-simulation | Pending tool run |
| ZedBoard execution time and compression | Pending hardware testing |
| UART framing/endurance | Pending hardware testing |
| GUI hardware operation | Pending hardware testing |
| PC-FPGA parity | Pending hardware testing |
