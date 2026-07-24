#!/usr/bin/env python3
"""Analyse the deterministic Chapter 7 PC campaign CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path


PRESET_NAMES = {
    0: "PWR-SMR",
    1: "RBMK-like",
    2: "Cooling-loss",
}


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

    def save(figure, output: str) -> None:
        figure.tight_layout()
        figure.savefig(figures_dir / output, dpi=180)
        plt.close(figure)

    def plot_rod(filename: str, title: str, output: str) -> None:
        rows = read_csv(input_dir / filename)
        time_s = [number(row, "sim_time_s") for row in rows]
        figure, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
        series = (("Normalized neutron power", "n"), ("Rod position (fraction)", "rod_position"), ("Reactivity ($)", "rho_dollars"))
        for axis, (label, key) in zip(axes, series):
            axis.plot(time_s, [number(row, key) for row in rows], color="#1769aa", linewidth=1.6, label=label)
            axis.set_ylabel(label)
            axis.grid(True, alpha=0.3)
            axis.legend(loc="best")
        axes[-1].set_xlabel("Simulation time (s)")
        figure.suptitle(title)
        save(figure, output)

    plot_rod("rod_withdrawal.csv", "Control-rod withdrawal", "rod_withdrawal.png")
    plot_rod("rod_insertion.csv", "Control-rod insertion", "rod_insertion.png")

    scram_rows = read_csv(input_dir / "scram_fast.csv")
    scram_time = [number(row, "sim_time_s") for row in scram_rows]
    figure, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for axis, label, key in zip(axes, ("Normalized neutron power", "Decay heat", "Total thermal power"), ("n", "decay_heat", "thermal_power")):
        axis.plot(scram_time, [number(row, key) for row in scram_rows], color="#b22222" if key == "n" else "#1769aa", linewidth=1.6, label=label)
        axis.set_ylabel(label)
        axis.set_yscale("log")
        axis.grid(True, alpha=0.3)
        axis.legend(loc="best")
    axes[-1].set_xlabel("Simulation time (s)")
    figure.suptitle("Fast SCRAM response")
    save(figure, "scram_fast.png")

    xenon_rows = read_csv(input_dir / "xenon_36h.csv")
    figure, axis = plt.subplots(figsize=(10, 5.5))
    time_h = [(number(row, "sim_time_s") - 10.0) / 3600.0 for row in xenon_rows]
    axis.plot(time_h, [number(row, "I_norm") for row in xenon_rows], label="I norm")
    axis.plot(time_h, [number(row, "Xe_norm") for row in xenon_rows], label="Xe norm")
    peak = max(xenon_rows, key=lambda row: number(row, "Xe_norm"))
    peak_h = (number(peak, "sim_time_s") - 10.0) / 3600.0
    peak_xe = number(peak, "Xe_norm")
    axis.axvline(peak_h, color="#555555", linestyle="--", linewidth=1, label=f"Xe peak ({peak_h:.2f} h)")
    axis.scatter([peak_h], [peak_xe], color="#b22222", zorder=4)
    axis.annotate(f"Xe peak {peak_xe:.3f}", xy=(peak_h, peak_xe), xytext=(peak_h + 1.2, peak_xe - 0.12), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    axis.set_title("36-hour iodine-xenon transient after SCRAM")
    axis.set_xlabel("time after SCRAM (h)")
    axis.grid(True, alpha=0.3)
    axis.legend()
    save(figure, "xenon_36h.png")

    figure, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for mode in range(3):
        rows = read_csv(input_dir / f"preset_{mode}.csv")
        label = PRESET_NAMES[mode]
        axes[0].plot([number(row, "sim_time_s") for row in rows], [number(row, "n") for row in rows], label=label)
        axes[1].plot([number(row, "sim_time_s") for row in rows], [number(row, "Tf") for row in rows], label=label)
        axes[2].plot([number(row, "sim_time_s") for row in rows], [number(row, "Tc") for row in rows], label=label)
    for axis, label in zip(axes, ("Normalized neutron power", "Fuel temperature (°C)", "Coolant temperature (°C)")):
        axis.set_ylabel(label)
        axis.grid(True, alpha=0.3)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 0.97))
    axes[-1].set_xlabel("Simulation time (s)")
    figure.suptitle("Response to identical reactivity commands across plant presets")
    figure.subplots_adjust(top=0.88)
    save(figure, "preset_comparison.png")

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
    save(figure, "rk4_error.png")

    performance = performance_summary(input_dir / "performance_frames.csv")
    mode_labels = ["REALTIME", "TRAINING", "XENON"]
    figure, axis = plt.subplots(figsize=(10, 5.8))
    x = list(range(len(mode_labels)))
    width = 0.24
    metrics = (("Mean", "mean_frame_time_s", "#1769aa"), ("p95", "p95_frame_time_s", "#d2691e"), ("Maximum", "max_frame_time_s", "#b22222"))
    for offset, (label, key, color) in enumerate(metrics):
        values_ms = [float(row[key]) * 1000.0 for row in performance]
        bars = axis.bar([value + (offset - 1) * width for value in x], values_ms, width, label=label, color=color)
        for bar, value in zip(bars, values_ms):
            axis.annotate(f"{value:.3g}", (bar.get_x() + bar.get_width() / 2.0, value), xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=8, rotation=90)
    axis.axhline(100.0, color="#555555", linestyle="--", linewidth=1.2, label="100 ms frame deadline")
    axis.set_yscale("log")
    axis.set_xticks(x, mode_labels)
    axis.set_ylabel("Frame-computation time (ms, log scale)")
    axis.set_title("PC frame-computation performance")
    axis.grid(True, axis="y", alpha=0.3)
    axis.legend(ncol=2)
    save(figure, "pc_performance.png")

    long_rows = read_csv(input_dir / "scram_long.csv")
    long_rows = [row for row in long_rows if number(row, "sim_time_s") >= 10.0]
    time_after = [number(row, "sim_time_s") - 10.0 for row in long_rows]
    figure, axes = plt.subplots(2, 1, figsize=(10, 7.2), sharex=True, gridspec_kw={"height_ratios": (1.4, 0.8)})
    axes[0].plot(time_after, [max(number(row, "n"), 1.0e-45) for row in long_rows], label="Neutron power", color="#b22222", linewidth=1.7)
    axes[0].plot(time_after, [max(number(row, "thermal_power"), 1.0e-45) for row in long_rows], label="Total thermal power", color="#1769aa", linewidth=1.5, linestyle="--")
    axes[0].plot(time_after, [max(number(row, "decay_heat"), 1.0e-45) for row in long_rows], label="Decay heat", color="#d2691e", linewidth=2.0)
    decay_fraction = [
        number(row, "decay_heat") / max(number(row, "thermal_power"), 1.0e-45)
        for row in long_rows
    ]
    axes[1].plot(time_after, decay_fraction, color="#d2691e", linewidth=2.0)
    axes[1].axhline(1.0, color="#555555", linestyle=":", linewidth=1.0)
    for mark, label in ((60.0, "60 s"), (600.0, "600 s"), (3600.0, "1 h"), (7200.0, "2 h")):
        for axis in axes:
            axis.axvline(mark, color="#777777", linestyle=":" if mark not in (3600.0, 7200.0) else "--", linewidth=0.8)
        axes[0].text(mark, 0.98, label, transform=axes[0].get_xaxis_transform(), ha="right", va="top", fontsize=8, rotation=90)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("Normalized power (log scale)")
    axes[0].set_title("Power components after SCRAM")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()
    axes[1].set_xscale("symlog", linthresh=60.0)
    axes[1].set_xticks((0.0, 10.0, 60.0, 600.0, 3600.0, 7200.0), ("0", "10", "60", "600", "3600", "7200"))
    axes[1].set_ylim(0.0, 1.05)
    axes[1].set_xlabel("Time after SCRAM (s; symmetric-log scale)")
    axes[1].set_ylabel("Decay heat / total\nthermal power")
    axes[1].set_title("Decay heat becomes the total thermal-power source")
    axes[1].grid(True, alpha=0.3)
    figure.suptitle("Two-hour SCRAM response and decay heat")
    save(figure, "scram_decay_heat_2h.png")

    steady = [physical_summary(path) for path in sorted(input_dir.glob("steady_power_*.csv"))]
    figure, axis = plt.subplots(figsize=(9, 5.2))
    powers = [float(row["initial_power"]) for row in steady]
    drifts = [float(row["max_power_drift_fraction"]) for row in steady]
    display_floor = 1.0e-12
    display = [max(value, display_floor) for value in drifts]
    markers = ["o" if value > 0.0 else "v" for value in drifts]
    for index, (value, marker) in enumerate(zip(display, markers)):
        axis.vlines(index, display_floor, value, color="#1769aa", linewidth=2)
        axis.plot(index, value, marker=marker, color="#1769aa", markersize=8)
        label = f"{drifts[index]:.2e}" if drifts[index] > 0.0 else "0 (float precision)"
        axis.annotate(label, (index, value), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=9)
    axis.axhline(1.0e-3, color="#555555", linestyle="--", linewidth=1.1, label="project drift tolerance (10⁻³)")
    axis.set_yscale("log")
    axis.set_ylim(5.0e-13, 3.0e-3)
    axis.set_xticks(range(len(powers)), [f"{power:.2f}" for power in powers])
    axis.set_xlabel("Initial normalized power")
    axis.set_ylabel("Maximum relative power drift")
    axis.set_title("Steady-state power drift")
    axis.grid(True, axis="y", alpha=0.3)
    axis.legend(loc="upper right")
    save(figure, "steady_state_drift.png")


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
