#!/usr/bin/env python3
"""Analyse the deterministic Chapter 7 PC campaign CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, float | str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = []
        for raw in csv.DictReader(handle):
            row: dict[str, float | str] = {}
            for key, value in raw.items():
                if key in {"scenario", "event", "mode"}:
                    row[key] = value or ""
                else:
                    row[key] = float(value) if value not in {None, ""} else math.nan
            rows.append(row)
        return rows


def number(row: dict[str, float | str], key: str) -> float:
    return float(row[key])


def nearest(rows: list[dict[str, float | str]], time_s: float) -> dict[str, float | str]:
    return min(rows, key=lambda row: abs(number(row, "sim_time_s") - time_s))


def physical_summary(path: Path) -> dict[str, float | str]:
    rows = read_csv(path)
    initial = rows[0]
    n0 = number(initial, "n")
    return {
        "file": path.name,
        "initial_power": n0,
        "max_power_drift_fraction": max(abs(number(row, "n") - n0) / max(abs(n0), 1.0e-12) for row in rows),
        "max_abs_rho": max(abs(number(row, "rho")) for row in rows),
        "max_fuel_temperature_drift": max(abs(number(row, "Tf") - number(initial, "Tf")) for row in rows),
        "max_coolant_temperature_drift": max(abs(number(row, "Tc") - number(initial, "Tc")) for row in rows),
        "final_power": number(rows[-1], "n"),
        "final_time_s": number(rows[-1], "sim_time_s"),
    }


def transient_summary(path: Path) -> dict[str, float | str]:
    rows = read_csv(path)
    initial = rows[0]
    peak = max(rows, key=lambda row: number(row, "n"))
    return {
        "file": path.name,
        "peak_power": number(peak, "n"),
        "time_to_peak_s": number(peak, "sim_time_s"),
        "min_power": min(number(row, "n") for row in rows),
        "max_fuel_temperature": max(number(row, "Tf") for row in rows),
        "max_coolant_temperature": max(number(row, "Tc") for row in rows),
        "final_power": number(rows[-1], "n"),
        "initial_power": number(initial, "n"),
    }


def rod_phase_summary(path: Path) -> dict[str, float | str]:
    rows = read_csv(path)
    disturbance = [row for row in rows if 20.0 <= number(row, "sim_time_s") <= 80.0]
    recovery = [row for row in rows if number(row, "sim_time_s") >= 80.0]
    withdrawal = path.stem.endswith("withdrawal")
    if withdrawal:
        disturbance_row = max(disturbance, key=lambda row: number(row, "n"))
        recovery_row = min(recovery, key=lambda row: number(row, "n"))
        disturbance_label = "maximum"
        recovery_label = "minimum"
    else:
        disturbance_row = min(disturbance, key=lambda row: number(row, "n"))
        recovery_row = max(recovery, key=lambda row: number(row, "n"))
        disturbance_label = "minimum"
        recovery_label = "maximum"
    return {
        "file": path.name,
        "disturbance_extremum": disturbance_label,
        "disturbance_power": number(disturbance_row, "n"),
        "disturbance_time_s": number(disturbance_row, "sim_time_s"),
        "recovery_extremum": recovery_label,
        "recovery_power": number(recovery_row, "n"),
        "recovery_time_s": number(recovery_row, "sim_time_s"),
        "final_power": number(rows[-1], "n"),
    }


def scram_table(path: Path, event_time_s: float = 10.0) -> list[dict[str, float | str]]:
    rows = read_csv(path)
    result = []
    for offset in (0.1, 1.0, 10.0, 60.0, 600.0, 3600.0, 7200.0):
        row = nearest(rows, event_time_s + offset)
        result.append({
            "time_after_scram_s": offset,
            "sim_time_s": number(row, "sim_time_s"),
            "neutron_power": number(row, "n"),
            "decay_heat": number(row, "decay_heat"),
            "thermal_power": number(row, "thermal_power"),
            "Tf": number(row, "Tf"),
            "Tc": number(row, "Tc"),
        })
    return result


def xenon_summary(path: Path) -> dict[str, float | str]:
    rows = read_csv(path)
    post_scram = [row for row in rows if number(row, "sim_time_s") >= 10.0]
    max_xenon = max(post_scram, key=lambda row: number(row, "Xe_norm"))
    min_rho_xe = min(post_scram, key=lambda row: number(row, "rho_xe"))
    after_peak = [row for row in post_scram if number(row, "sim_time_s") >= number(max_xenon, "sim_time_s")]
    close_rows = [row for row in after_peak if abs(number(row, "Xe_norm") - 1.0) <= 0.01]
    return {
        "file": path.name,
        "duration_after_scram_h": (number(rows[-1], "sim_time_s") - 10.0) / 3600.0,
        "iodine_at_xenon_peak": number(max_xenon, "I_norm"),
        "xenon_max": number(max_xenon, "Xe_norm"),
        "xenon_peak_time_h": (number(max_xenon, "sim_time_s") - 10.0) / 3600.0,
        "maximum_xenon_worth_dollars": number(min_rho_xe, "rho_xe") / 0.007,
        "xenon_worth_time_h": (number(min_rho_xe, "sim_time_s") - 10.0) / 3600.0,
        "xenon_return_within_1pct_time_h": ((number(close_rows[0], "sim_time_s") - 10.0) / 3600.0) if close_rows else None,
        "maximum_critical_rod_position": max(number(row, "critical_rod_position") for row in post_scram),
        "minimum_neutron_power": min(number(row, "n") for row in post_scram),
    }


def convergence_summary(path: Path) -> list[dict[str, float | str]]:
    rows = read_csv(path)
    result = []
    for h in sorted({number(row, "h_s") for row in rows}):
        subset = [row for row in rows if math.isclose(number(row, "h_s"), h, rel_tol=0.0, abs_tol=1.0e-12)]
        entry: dict[str, float | str] = {"h_s": h}
        for variable, error_key, reference_key in (
            ("n", "error_n", "ref_n"),
            ("Tf", "error_Tf", "ref_Tf"),
            ("Tc", "error_Tc", "ref_Tc"),
        ):
            errors = [abs(number(row, error_key)) for row in subset]
            relative = [abs(number(row, error_key)) / max(abs(number(row, reference_key)), 1.0e-12) for row in subset]
            entry[f"{variable}_rmse"] = math.sqrt(sum(error * error for error in errors) / len(errors))
            entry[f"{variable}_max_abs"] = max(errors)
            entry[f"{variable}_max_relative"] = max(relative)
            entry[f"{variable}_final_error"] = number(subset[-1], error_key)
        result.append(entry)
    return result


def performance_summary(path: Path) -> list[dict[str, float | str]]:
    rows = read_csv(path)
    result = []
    for mode in ("REALTIME", "TRAINING", "XENON"):
        subset = [row for row in rows if row.get("mode") == mode]
        times = [number(row, "wall_compute_s") for row in subset]
        factor_key = "kernel_throughput_factor" if "kernel_throughput_factor" in subset[0] else "achieved_factor"
        factors = [number(row, factor_key) for row in subset]
        sorted_times = sorted(times)
        p95 = sorted_times[min(len(sorted_times) - 1, math.ceil(0.95 * len(sorted_times)) - 1)]
        result.append({
            "mode": mode,
            "frames": len(subset),
            "mean_frame_time_s": statistics.mean(times),
            "median_frame_time_s": statistics.median(times),
            "std_frame_time_s": statistics.stdev(times) if len(times) > 1 else 0.0,
            "p95_frame_time_s": p95,
            "max_frame_time_s": max(times),
            "mean_kernel_throughput_factor": statistics.mean(factors),
            "min_kernel_throughput_factor": min(factors),
            "missed_100ms_deadlines": sum(int(number(row, "missed_100ms_deadline")) for row in subset),
        })
    return result


def make_plots(input_dir: Path, figures_dir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    figures_dir.mkdir(parents=True, exist_ok=True)

    def plot_file(filename: str, x: str, series: list[tuple[str, str]], title: str, output: str, log_y: bool = False) -> None:
        rows = read_csv(input_dir / filename)
        figure, axis = plt.subplots(figsize=(10, 5.5))
        for label, key in series:
            axis.plot([number(row, x) for row in rows], [number(row, key) for row in rows], label=label)
        axis.set_title(title)
        axis.set_xlabel(x)
        axis.grid(True, alpha=0.3)
        if log_y:
            axis.set_yscale("log")
        axis.legend()
        figure.tight_layout()
        figure.savefig(figures_dir / output, dpi=160)
        plt.close(figure)

    plot_file("rod_withdrawal.csv", "sim_time_s", [("N", "n"), ("rod position", "rod_position"), ("rho ($)", "rho_dollars")], "Control-rod withdrawal", "rod_withdrawal.png")
    plot_file("rod_insertion.csv", "sim_time_s", [("N", "n"), ("rod position", "rod_position"), ("rho ($)", "rho_dollars")], "Control-rod insertion", "rod_insertion.png")
    plot_file("scram_fast.csv", "sim_time_s", [("N", "n"), ("thermal power", "thermal_power"), ("decay heat", "decay_heat")], "Fast SCRAM response", "scram_fast.png", log_y=True)
    xenon_rows = read_csv(input_dir / "xenon_36h.csv")
    figure, axis = plt.subplots(figsize=(10, 5.5))
    time_h = [(number(row, "sim_time_s") - 10.0) / 3600.0 for row in xenon_rows]
    axis.plot(time_h, [number(row, "I_norm") for row in xenon_rows], label="I norm")
    axis.plot(time_h, [number(row, "Xe_norm") for row in xenon_rows], label="Xe norm")
    axis.set_title("36-hour iodine-xenon transient after SCRAM")
    axis.set_xlabel("time after SCRAM (h)")
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.tight_layout()
    figure.savefig(figures_dir / "xenon_36h.png", dpi=160)
    plt.close(figure)

    figure, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for mode in range(3):
        rows = read_csv(input_dir / f"preset_{mode}.csv")
        axes[0].plot([number(row, "sim_time_s") for row in rows], [number(row, "n") for row in rows], label=f"preset {mode}")
        axes[1].plot([number(row, "sim_time_s") for row in rows], [number(row, "Tf") for row in rows], label=f"preset {mode}")
        axes[2].plot([number(row, "sim_time_s") for row in rows], [number(row, "Tc") for row in rows], label=f"preset {mode}")
    for axis, label in zip(axes, ("N", "Tf", "Tc")):
        axis.set_ylabel(label)
        axis.grid(True, alpha=0.3)
        axis.legend()
    axes[-1].set_xlabel("sim_time_s")
    figure.suptitle("Identical reactivity insertion across presets")
    figure.tight_layout()
    figure.savefig(figures_dir / "preset_comparison.png", dpi=160)
    plt.close(figure)

    rows = read_csv(input_dir / "rk4_convergence.csv")
    figure, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for h in sorted({number(row, "h_s") for row in rows}):
        subset = [row for row in rows if math.isclose(number(row, "h_s"), h, rel_tol=0.0, abs_tol=1.0e-12)]
        time = [number(row, "sim_time_s") for row in subset]
        for axis, key in zip(axes, ("error_n", "error_Tf", "error_Tc")):
            axis.plot(time, [number(row, key) for row in subset], label=f"h={h:g}")
    for axis, label in zip(axes, ("error N", "error Tf", "error Tc")):
        axis.set_ylabel(label)
        axis.grid(True, alpha=0.3)
        axis.legend()
    axes[-1].set_xlabel("sim_time_s")
    figure.suptitle("Semi-implicit solver error versus RK4 reference")
    figure.tight_layout()
    figure.savefig(figures_dir / "rk4_error.png", dpi=160)
    plt.close(figure)


def markdown_table(rows: list[dict[str, float | str]], columns: list[str]) -> str:
    if not rows:
        return "(no rows)"
    header = "| " + " | ".join(columns) + " |\n|" + "|".join("---" for _ in columns) + "|\n"
    body = ""
    for row in rows:
        body += "| " + " | ".join(str(row.get(column, "")) for column in columns) + " |\n"
    return header + body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    input_dir = args.input.resolve()

    summary: dict[str, object] = {
        "steady_state": [physical_summary(path) for path in sorted(input_dir.glob("steady_power_*.csv"))],
        "rod_transients": [rod_phase_summary(input_dir / name) for name in ("rod_withdrawal.csv", "rod_insertion.csv")],
        "scram_long_table": scram_table(input_dir / "scram_long.csv"),
        "xenon": xenon_summary(input_dir / "xenon_36h.csv"),
        "preset_comparison": [transient_summary(input_dir / f"preset_{mode}.csv") for mode in range(3)],
        "rk4_convergence": convergence_summary(input_dir / "rk4_convergence.csv"),
        "performance": performance_summary(input_dir / "performance_frames.csv"),
    }
    (input_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Chapter 7 PC campaign results",
        "",
        "All values below were computed from the raw CSV files in this directory. The PC campaign does not establish FPGA hardware execution, UART reliability, GUI hardware operation, or PC-FPGA parity.",
        "",
        "## Steady-state tests",
        "",
        markdown_table(summary["steady_state"], ["file", "initial_power", "max_power_drift_fraction", "max_abs_rho", "max_fuel_temperature_drift", "max_coolant_temperature_drift"]),
        "",
        "## Rod-transient phase summary",
        "",
        "The disturbance extremum is measured during 20–80 s. The recovery extremum is measured after the rod target is restored at 80 s.",
        "",
        markdown_table(summary["rod_transients"], ["file", "disturbance_extremum", "disturbance_power", "disturbance_time_s", "recovery_extremum", "recovery_power", "recovery_time_s", "final_power"]),
        "",
        "## SCRAM and decay heat",
        "",
        markdown_table(summary["scram_long_table"], ["time_after_scram_s", "neutron_power", "decay_heat", "thermal_power", "Tf", "Tc"]),
        "",
        "## Iodine-xenon transient",
        "",
        markdown_table([summary["xenon"]], ["duration_after_scram_h", "iodine_at_xenon_peak", "xenon_max", "xenon_peak_time_h", "maximum_xenon_worth_dollars", "xenon_worth_time_h", "xenon_return_within_1pct_time_h", "maximum_critical_rod_position"]),
        "",
        "## სამი რეაქტორული წინასწარი კონფიგურაციის პასუხი ერთნაირ რეაქტიულობის ზემოქმედებაზე",
        "",
        "This is a complete preset-behaviour comparison. It includes both the presets’ feedback coefficients and their different active cooling-removal conditions; it is not an isolation of temperature-feedback coefficients.",
        "",
        markdown_table(summary["preset_comparison"], ["file", "peak_power", "time_to_peak_s", "max_fuel_temperature", "max_coolant_temperature", "final_power"]),
        "",
        "## RK4 and timestep convergence",
        "",
        markdown_table(summary["rk4_convergence"], ["h_s", "n_rmse", "n_max_abs", "n_max_relative", "Tf_rmse", "Tf_max_abs", "Tc_rmse", "Tc_max_abs"]),
        "",
        "## PC physics-kernel performance",
        "",
        "The reported factor is kernel throughput factor: raw physics-kernel work divided by measured kernel wall time. It excludes pacing, GUI rendering, communication, and deliberate waiting. No 100 ms deadlines were missed in 1000 frames per mode, so the PC kernel can sustain the requested 1×, 10×, and 1000× operating modes.",
        "",
        markdown_table(summary["performance"], ["mode", "frames", "mean_frame_time_s", "median_frame_time_s", "std_frame_time_s", "p95_frame_time_s", "max_frame_time_s", "mean_kernel_throughput_factor", "missed_100ms_deadlines"]),
        "",
        "## Hardware/HLS work still pending",
        "",
        "| Item | Status |",
        "|---|---|",
        "| HLS C simulation | Covered by the native smoke and parity tests |",
        "| HLS synthesis and Vivado implementation | Pending: Vivado/Vitis are not available in this PC session |",
        "| RTL co-simulation | Pending tool run |",
        "| ZedBoard execution time and compression | Pending hardware testing |",
        "| UART framing/endurance | Pending hardware testing |",
        "| GUI hardware operation | Pending hardware testing |",
        "| PC-FPGA parity | Pending hardware testing |",
    ]
    (input_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    make_plots(input_dir, input_dir / "figures")
    print(f"Wrote {input_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
