# Project architecture

## Runtime architecture

```mermaid
flowchart LR
    USER["Student / researcher"]

    subgraph COMMON["Canonical model source"]
        CFG["point_kinetics_config.h<br/>timing and plant constants"]
        CORE["point_kinetics_core.h<br/>kinetics, thermal, decay heat,<br/>iodine/xenon, rods and SCRAM"]
        CHELP["point_kinetics_c.h<br/>C plant/telemetry helpers"]
        CFG --> CORE
        CFG --> CHELP
    end

    subgraph PC["PC simulation path"]
        LAUNCH["pc_sim_launcher.py<br/>build and process relay"]
        SOLVER["pc_solver.cpp<br/>frame pacing and commands"]
        PLOT["plot_realtime.py<br/>GUI, controls and plots"]

        PLOT -- "control commands" --> LAUNCH
        LAUNCH -- "stdin commands" --> SOLVER
        SOLVER -- "23-field CSV telemetry" --> LAUNCH
        LAUNCH -- "stdout pipe" --> PLOT
    end

    subgraph BOARD["ZedBoard runtime"]
        SWITCHES["8 physical switches"]

        subgraph ZYNQ["Zynq-7000"]
            PS["Processing System 7 / Cortex-A9<br/>standalone main.c<br/>pacing, commands and telemetry"]
            SMC["AXI SmartConnect"]
            GPIO["AXI GPIO<br/>switch inputs"]
            HLS["point_kinetics_step HLS IP<br/>persistent reactor state"]
            RESET["Processor System Reset"]

            PS -- "M_AXI_GP0" --> SMC
            SMC -- "AXI4-Lite control/status" --> HLS
            SMC -- "AXI4-Lite reads" --> GPIO
            RESET -. "synchronous reset" .-> SMC
            RESET -. "synchronous reset" .-> GPIO
            RESET -. "synchronous reset" .-> HLS
        end

        SWITCHES --> GPIO
    end

    USER --> PLOT
    PLOT -- "UART commands" --> PS
    PS -- "UART CSV telemetry" --> PLOT

    SOLVER -. "compiled with" .-> CORE
    HLS -. "synthesized from" .-> CORE
    CFG -. "shared C constants" .-> PS
    CHELP -. "telemetry helpers" .-> PS
```

The PC and FPGA paths execute the same `pk::ReactorState` equations from the
canonical core. The ARM application does not duplicate the physics solver: it
selects the timestep and substep count, writes commands to the HLS register
map, waits for completion, reads outputs, and emits telemetry using shared C
plant helpers.

One output frame follows this sequence:

1. The GUI, UART, or board switches provide an operator command.
2. The PC host or ARM application selects `h` and the bounded substep count.
3. The shared core advances neutron power, six precursors, decay heat,
   temperatures, rods, and time one substep at a time.
4. Iodine and xenon are updated once per frame using average neutron power.
5. The PC host or ARM application emits the same 23-field CSV schema.
6. The plotter displays state, feedback components, rod position, achieved
   compression, timestep, plant mode, and SCRAM status.

## FPGA block design

```mermaid
flowchart LR
    PS["processing_system7_0<br/>Cortex-A9, DDR, UART<br/>100 MHz FCLK"]
    AXI["axi_smc<br/>1 slave / 2 masters"]
    HLS["point_kinetics_step_0<br/>AXI4-Lite at 0x40000000"]
    GPIO["axi_gpio_0<br/>8 inputs at 0x40010000"]
    RST["rst_ps7_0_100M"]
    SW["ZedBoard switches"]

    PS -- "M_AXI_GP0" --> AXI
    AXI --> HLS
    AXI --> GPIO
    SW --> GPIO
    PS -. "FCLK_CLK0" .-> AXI
    PS -. "FCLK_CLK0" .-> HLS
    PS -. "FCLK_CLK0" .-> GPIO
    PS -. "FCLK_RESET0_N" .-> RST
    RST -. "peripheral_aresetn" .-> AXI
    RST -. "peripheral_aresetn" .-> HLS
    RST -. "peripheral_aresetn" .-> GPIO
```

## Build and verification pipeline

```mermaid
flowchart LR
    CFG["Shared configuration"]
    CORE["Canonical physics core"]
    CHELP["C telemetry helpers"]
    HLSTOP["HLS top and configuration"]
    HLSBUILD["Vitis HLS compile/package"]
    IP["Packaged point_kinetics_step IP"]
    REFRESH["refresh_hls_ip.tcl"]
    BD["Vivado block design and constraints"]
    VIVADO["build_vivado_bitstream.tcl<br/>synthesis, implementation and timing gate"]
    BIT["system_wrapper.bit"]
    XSA["pk.xsa"]
    VITIS["build_vitis.py<br/>platform, BSP and application"]
    ELF["pk_app.elf"]

    CFG --> CORE
    CFG --> CHELP
    CORE --> HLSTOP
    HLSTOP --> HLSBUILD --> IP
    IP --> REFRESH --> BD
    BD --> VIVADO
    VIVADO --> BIT
    VIVADO --> XSA
    CFG --> VITIS
    CHELP --> VITIS
    XSA --> VITIS --> ELF

    CORE --> PHYS["physics_regression.cpp<br/>independent RK4 and precision checks"]
    CORE --> PARITY["pc_hls_parity.cpp<br/>core versus HLS interface"]
    HLSTOP --> TB["tb_point_kinetics.cpp<br/>HLS smoke and long-duration tests"]
```

Generated HLS output, Vivado runs, bitstreams, XSA files, Vitis platforms, and
ELF files are build artifacts. The versioned sources are the common model,
wrappers, application, block-design metadata, constraints, tests, and build
scripts.

## Component responsibilities

| Component | Responsibility |
| --- | --- |
| `point_kinetics_config.h` | Cross-target timing, feedback, rod-worth, SCRAM and decay-heat constants |
| `point_kinetics_core.h` | Canonical reactor state and numerical update methods |
| `point_kinetics_c.h` | C plant coefficients and critical-rod helpers for ARM telemetry |
| `point_kinetics.cpp/.h` | HLS AXI interface and persistent FPGA state |
| `pc_solver.cpp` | PC command handling, frame pacing and telemetry |
| `main.c` | ARM control of HLS IP, physical switches, UART and telemetry |
| `plot_realtime.py` | PC/serial input, controls, plots and status presentation |
| Vivado block design | PS7, AXI interconnect, HLS accelerator, GPIO, clock and reset integration |
| Regression tests | Numerical precision, reference comparison and PC/HLS parity |

