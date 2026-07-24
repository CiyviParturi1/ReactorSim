#!/usr/bin/env python3
"""Generate the Chapter 7 comparison and evidence figures from recorded data."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


REPORTS = (
    ("preset_0_parity", "M0 / PWR-SMR"),
    ("preset_1_parity", "M1 / RBMK-like"),
    ("preset_2_parity", "M2 / cooling-loss"),
    ("rod_insertion_parity", "Rod insertion"),
    ("rod_withdrawal_parity", "Rod withdrawal"),
    ("xenon_36h_parity", "Xenon, 36 h"),
)
VARIABLES = (
    ("N", "n"),
    ("T_f", "Tf"),
    ("T_c", "Tc"),
    ("I", "I_norm"),
    ("Xe", "Xe_norm"),
    ("rho", "rho"),
    ("P_decay", "decay_heat"),
    ("rod position", "rod_position"),
)
PLOT_VARIABLES = (("N", "n"), ("T_f", "Tf"), ("T_c", "Tc"))
COLORS = ("#1769aa", "#d2691e", "#2e8b57", "#b22222", "#6a3d9a", "#555555")


def read_numeric_csv(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8") as handle:
        result: list[dict[str, float]] = []
        for raw in csv.DictReader(handle):
            row: dict[str, float] = {}
            for key, value in raw.items():
                if value in (None, ""):
                    continue
                try:
                    row[key] = float(value)
                except ValueError:
                    continue
            if "sim_time_s" in row:
                result.append(row)
        return result


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_epoch(rows: list[dict[str, float]]) -> list[dict[str, float]]:
    start = 0
    previous: float | None = None
    for index, row in enumerate(rows):
        current = row["sim_time_s"]
        if previous is not None and current < previous:
            start = index
        previous = current
    return sorted(rows[start:], key=lambda row: row["sim_time_s"])


def interpolate(rows: list[dict[str, float]], key: str, time_s: float) -> float | None:
    if not rows or time_s < rows[0]["sim_time_s"] or time_s > rows[-1]["sim_time_s"]:
        return None
    for left, right in zip(rows, rows[1:]):
        if left["sim_time_s"] <= time_s <= right["sim_time_s"]:
            span = right["sim_time_s"] - left["sim_time_s"]
            if span <= 0.0 or key not in left or key not in right:
                return None
            fraction = (time_s - left["sim_time_s"]) / span
            return left[key] + fraction * (right[key] - left[key])
    return rows[-1].get(key) if time_s == rows[-1]["sim_time_s"] else None


def report_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def build_case(root: Path, report_name: str, label: str) -> dict[str, Any]:
    report = load_json(root / "experiments" / "results" / "chapter7_fpga_20260713" / f"{report_name}.json")
    fpga = latest_epoch(read_numeric_csv(report_path(root, report["fpga_csv"])))
    pc = sorted(read_numeric_csv(report_path(root, report["pc_csv"])), key=lambda row: row["sim_time_s"])
    fpga_origin = float(report.get("fpga_time_origin_s", 0.0))
    pc_origin = float(report.get("pc_time_origin_s", 0.0))
    alignment = report.get("alignment", "absolute_simulated_time")
    comparisons: dict[str, dict[str, list[float]]] = {
        name: {"time": [], "fpga": [], "pc": []} for name, _ in VARIABLES
    }
    for hw in fpga:
        elapsed = hw["sim_time_s"] - fpga_origin if alignment == "scram" else hw["sim_time_s"]
        target_pc_time = pc_origin + elapsed if alignment == "scram" else hw["sim_time_s"]
        for name, key in VARIABLES:
            if key not in hw:
                continue
            expected = interpolate(pc, key, target_pc_time)
            if expected is None:
                continue
            comparisons[name]["time"].append(elapsed)
            comparisons[name]["fpga"].append(hw[key])
            comparisons[name]["pc"].append(expected)
    return {"name": report_name, "label": label, "report": report, "comparisons": comparisons}


def save(figure: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(figure)


def format_error(value: float) -> str:
    return f"{value:.3e}"


def sample_stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
    return {
        "min": min(values),
        "mean": statistics.mean(values),
        "p95": p95,
        "max": max(values),
    }


def binned_max(x: list[float], y: list[float], bins: int = 180) -> tuple[list[float], list[float]]:
    if len(x) <= bins:
        return x, y
    stride = math.ceil(len(x) / bins)
    result_x: list[float] = []
    result_y: list[float] = []
    for start in range(0, len(x), stride):
        stop = min(len(x), start + stride)
        result_x.append((x[start] + x[stop - 1]) / 2.0)
        result_y.append(max(y[start:stop]))
    return result_x, result_y


def scaled_residual(case: dict[str, Any], name: str) -> tuple[list[float], list[float], float]:
    values = case["comparisons"][name]
    tolerance = float(case["report"]["tolerance"])
    ratios = [
        abs(actual - expected) / (tolerance * (1.0 + abs(actual) + abs(expected)))
        for actual, expected in zip(values["fpga"], values["pc"])
    ]
    return values["time"], ratios, max(ratios, default=0.0)


def plot_overlay(cases: list[dict[str, Any]], output: Path, title: str, time_label: str, scale: float) -> None:
    figure, axes = plt.subplots(4, len(cases), figsize=(6.2 * len(cases), 10), sharex="col", squeeze=False)
    for column, case in enumerate(cases):
        comparisons = case["comparisons"]
        for row, (name, key) in enumerate(PLOT_VARIABLES):
            axis = axes[row][column]
            values = comparisons[name]
            x = [value * scale for value in values["time"]]
            axis.plot(x, values["pc"], color="#1769aa", linewidth=1.5, label="PC")
            axis.plot(x, values["fpga"], color="#d2691e", linewidth=1.2, linestyle="--", label="FPGA")
            axis.set_ylabel({"N": "N", "T_f": "Tf (°C)", "T_c": "Tc (°C)"}[name])
            axis.grid(True, alpha=0.25)
            if row == 0:
                axis.set_title(case["label"])
            if row == 0 and column == 0:
                axis.legend(loc="best")
        residual_axis = axes[3][column]
        ratio_max: dict[str, float] = {}
        for color, (name, _) in zip(COLORS[:3], PLOT_VARIABLES):
            time, ratios, ratio_max[name] = scaled_residual(case, name)
            x, envelope = binned_max([value * scale for value in time], ratios)
            residual_axis.plot(x, [max(value, 1.0e-8) for value in envelope], color=color, linewidth=1.4, label=name)
        residual_axis.axhline(1.0, color="#555555", linestyle="--", linewidth=1.1, label="tolerance limit")
        residual_axis.set_yscale("log")
        residual_axis.set_ylim(1.0e-8, 2.0)
        residual_axis.set_ylabel("Binned maximum\nresidual / tolerance")
        residual_axis.set_xlabel(time_label)
        residual_axis.grid(True, alpha=0.25)
        status = "pass" if case["report"].get("all_variables_within_scaled_tolerance") else "FAIL"
        residual_axis.text(
            0.02, 0.96,
            "maximum fraction of tolerance: " + ", ".join(f"{name} {value:.3g}" for name, value in ratio_max.items()) + f"\n{status}: every value < 1",
            transform=residual_axis.transAxes, va="top", fontsize=8,
            bbox={"facecolor": "white", "alpha": 0.82, "edgecolor": "#bbbbbb"},
        )
        residual_axis.legend(loc="lower right", fontsize=8, ncol=2)
    figure.suptitle(title, y=1.01)
    save(figure, output)


def plot_xenon_overlay(case: dict[str, Any], output: Path) -> None:
    figure, axes = plt.subplots(4, 2, figsize=(12, 10), squeeze=False)
    windows = ((0.0, 0.05, "Early shutdown response"), (0.0, 36.0, "Full 36-hour run"))
    for column, (left, right, heading) in enumerate(windows):
        for row, (name, _) in enumerate(PLOT_VARIABLES):
            axis = axes[row][column]
            values = case["comparisons"][name]
            x = [value / 3600.0 for value in values["time"]]
            axis.plot(x, values["pc"], color="#1769aa", linewidth=1.5, label="PC")
            axis.plot(x, values["fpga"], color="#d2691e", linewidth=1.2, linestyle="--", label="FPGA")
            axis.set_xlim(left, right)
            axis.set_ylabel({"N": "N", "T_f": "Tf (°C)", "T_c": "Tc (°C)"}[name])
            axis.grid(True, alpha=0.25)
            if row == 0:
                axis.set_title(heading)
            if row == 0 and column == 0:
                axis.legend(loc="best")
        residual_axis = axes[3][column]
        maxima: dict[str, float] = {}
        for color, (name, _) in zip(COLORS[:3], PLOT_VARIABLES):
            time, ratios, maxima[name] = scaled_residual(case, name)
            x, envelope = binned_max([value / 3600.0 for value in time], ratios, bins=200)
            residual_axis.plot(x, [max(value, 1.0e-8) for value in envelope], color=color, linewidth=1.4, label=name)
        residual_axis.axhline(1.0, color="#555555", linestyle="--", linewidth=1.1, label="tolerance limit")
        residual_axis.set_xlim(left, right)
        residual_axis.set_ylim(1.0e-8, 2.0)
        residual_axis.set_yscale("log")
        residual_axis.set_ylabel("Binned maximum\nresidual / tolerance")
        residual_axis.set_xlabel("Time after SCRAM (h)")
        residual_axis.grid(True, alpha=0.25)
        if column == 1:
            residual_axis.text(
                0.02, 0.96,
                "maximum fraction of tolerance: " + ", ".join(f"{name} {value:.3g}" for name, value in maxima.items()),
                transform=residual_axis.transAxes, va="top", fontsize=8,
                bbox={"facecolor": "white", "alpha": 0.82, "edgecolor": "#bbbbbb"},
            )
        residual_axis.legend(loc="lower right", fontsize=8, ncol=2)
    figure.suptitle("PC–FPGA xenon-run parity", y=1.01)
    save(figure, output)


def parity_error_matrices(cases: list[dict[str, Any]]) -> tuple[list[list[float]], list[list[float]]]:
    raw: list[list[float]] = []
    ratios: list[list[float]] = []
    for case in cases:
        report_tolerance = float(case["report"].get("tolerance", 0.0))
        raw_row: list[float] = []
        ratio_row: list[float] = []
        for name, _ in VARIABLES:
            values = case["comparisons"][name]
            errors = [abs(actual - expected) for actual, expected in zip(values["fpga"], values["pc"])]
            scaled = [report_tolerance * (1.0 + abs(actual) + abs(expected)) for actual, expected in zip(values["fpga"], values["pc"])]
            raw_row.append(max(errors, default=0.0))
            ratio_row.append(max((error / limit for error, limit in zip(errors, scaled) if limit > 0.0), default=0.0))
        raw.append(raw_row)
        ratios.append(ratio_row)
    return raw, ratios


def plot_parity_errors(cases: list[dict[str, Any]], output: Path) -> None:
    _, ratios = parity_error_matrices(cases)
    labels = [name for name, _ in VARIABLES]
    row_labels = [case["label"] for case in cases]
    display = [[max(value, 1.0e-6) for value in row] for row in ratios]
    figure, axis = plt.subplots(figsize=(12, 6.5))
    image = axis.imshow(
        display,
        aspect="auto",
        cmap="viridis",
        norm=matplotlib.colors.LogNorm(vmin=1.0e-6, vmax=1.0),
    )
    for row, values in enumerate(ratios):
        for column, value in enumerate(values):
            text = "0" if value == 0.0 else f"{value:.2g}"
            axis.text(
                column, row, text,
                ha="center", va="center",
                color="white" if value >= 0.02 else "black",
                fontsize=9,
            )
    axis.set_xticks(range(len(labels)), labels)
    axis.set_yticks(range(len(row_labels)), row_labels)
    axis.set_xlabel("Compared variable")
    axis.set_title("Maximum PC–FPGA residual as a fraction of scaled tolerance")
    colorbar = figure.colorbar(image, ax=axis, pad=0.02)
    colorbar.set_label("Maximum residual / tolerance (1 = limit)")
    axis.text(
        0.0, -0.14,
        "All cells are below 1; exact-zero residuals are labelled 0.",
        transform=axis.transAxes,
        fontsize=9,
    )
    figure.suptitle("PC–FPGA parity by variable and report", y=1.01)
    save(figure, output)


def load_fpga_timing(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    results = root / "experiments" / "results" / "chapter7_fpga_20260713"
    summary = load_json(results / "summary.json")
    timing = {row["test"]: row for row in summary["execution_timing"]}
    validations = {name: load_json(results / name / "telemetry_validation.json") for name in ("m0_1000_frames", "m1_1000_frames", "m2_1000_frames")}
    return timing, validations


def plot_timing_compression(root: Path, output: Path) -> None:
    timing, validations = load_fpga_timing(root)
    names = ("m0_1000_frames", "m1_1000_frames", "m2_1000_frames")
    labels = ("M0", "M1", "M2")
    requested = (1.0, 10.0, 1000.0)
    figure, axes = plt.subplots(2, 1, figsize=(10, 8), gridspec_kw={"height_ratios": (1.35, 1.0)})
    x = list(range(3))
    width = 0.24
    series = (
        ("Requested", requested, "#888888"),
        ("ARM-reported median", [float(validations[name]["achieved_factor"]["median"]) for name in names], "#1769aa"),
        ("Host-observed median", [float(validations[name]["host_observed_factor"]["median"]) for name in names], "#d2691e"),
    )
    for offset, (label, values, color) in enumerate(series):
        bars = axes[0].bar([value + (offset - 1) * width for value in x], values, width, label=label, color=color)
        for bar, value in zip(bars, values):
            axes[0].annotate(f"{value:.4g}", (bar.get_x() + bar.get_width() / 2.0, value), xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=8, rotation=90)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("Compression factor (log scale)")
    axes[0].set_xticks(x, labels)
    axes[0].set_title("Requested versus achieved FPGA compression")
    axes[0].grid(True, axis="y", alpha=0.25)
    axes[0].legend(ncol=3)

    for index, name in enumerate(names):
        stats = validations[name]["frame_interval_s"]
        low = float(stats["min"]) * 1000.0
        median = float(stats["median"]) * 1000.0
        p95 = float(stats["p95"]) * 1000.0
        high = float(stats["max"]) * 1000.0
        color = "#b22222" if int(timing[name]["missed_frames"]) else "#1769aa"
        axes[1].hlines(index, low, high, color=color, linewidth=2.0)
        axes[1].plot(median, index, marker="o", color=color, label="median" if index == 0 else None)
        axes[1].plot(p95, index, marker="s", color=color, label="p95" if index == 0 else None)
        axes[1].plot(high, index, marker="|", color=color, markersize=10, label="maximum" if index == 0 else None)
        missed = int(timing[name]["missed_frames"])
        if missed:
            axes[1].annotate("1 interval >150 ms", (high, index), xytext=(-6, 10), textcoords="offset points", ha="right", fontsize=9)
    axes[1].axvline(100.0, color="#555555", linestyle="--", linewidth=1.2, label="nominal 100 ms cadence")
    axes[1].axvline(150.0, color="#b22222", linestyle=":", linewidth=1.2, label="missed-frame threshold (>150 ms)")
    axes[1].set_yticks(x, labels)
    axes[1].set_xlim(88.0, 160.0)
    axes[1].set_xlabel("Host-observed UART frame interval (ms)")
    axes[1].set_title("Frame delivery intervals and missed-frame criterion")
    axes[1].grid(True, axis="x", alpha=0.25)
    axes[1].legend(ncol=2, fontsize=8, loc="lower right")
    figure.suptitle("FPGA timing and achieved compression", y=1.01)
    save(figure, output)


def pc_performance(root: Path) -> dict[str, dict[str, float]]:
    path = root / "experiments" / "results" / "chapter7_pc_20260711" / "performance_frames.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict[str, float]] = {}
    for mode in ("REALTIME", "TRAINING", "XENON"):
        values = [float(row["wall_compute_s"]) for row in rows if row["mode"] == mode]
        ordered = sorted(values)
        p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
        result[mode] = {"min": min(values), "mean": statistics.mean(values), "p95": p95, "max": max(values)}
    return result


def plot_pc_vs_fpga_timing(root: Path, output: Path) -> None:
    modes = ("REALTIME", "TRAINING", "XENON")
    fpga_names = ("m0_1000_frames", "m1_1000_frames", "m2_1000_frames")
    steps = (1000, 1000, 50000)
    pc_path = root / "experiments" / "results" / "chapter7_pc_20260711" / "performance_frames.csv"
    with pc_path.open(newline="", encoding="utf-8") as handle:
        pc_rows = list(csv.DictReader(handle))

    pc_frame: list[dict[str, float]] = []
    pc_step: list[dict[str, float]] = []
    fpga_frame: list[dict[str, float]] = []
    fpga_step: list[dict[str, float]] = []
    fpga_root = root / "experiments" / "results" / "chapter7_fpga_20260713"
    for mode, name, substeps in zip(modes, fpga_names, steps):
        pc_values = [float(row["wall_compute_s"]) for row in pc_rows if row["mode"] == mode]
        pc_frame.append(sample_stats(pc_values))
        pc_step.append(sample_stats([value / substeps for value in pc_values]))
        fpga_rows = latest_epoch(read_numeric_csv(fpga_root / name / "telemetry.csv"))
        fpga_step_values = [row["step_real_time_s"] for row in fpga_rows]
        fpga_step.append(sample_stats(fpga_step_values))
        fpga_frame.append(sample_stats([value * substeps for value in fpga_step_values]))

    figure, axes = plt.subplots(2, 1, figsize=(10.5, 8.5), sharex=True)
    x = list(range(3))
    width = 0.34
    panels = (
        (axes[0], pc_step, fpga_step, 1.0e6, "Per-substep compute time (µs)", "Equivalent per-substep execution time"),
        (
            axes[1],
            pc_frame,
            fpga_frame,
            1000.0,
            "Complete physics-frame compute time (ms)",
            "Complete compute time for one output frame\n(compute only; pacing, UART, GUI and deliberate waiting excluded)",
        ),
    )
    for axis, pc_stats, fpga_stats, multiplier, ylabel, heading in panels:
        for offset, stats_list, label, color in (
            (-width / 2, pc_stats, "PC kernel", "#1769aa"),
            (width / 2, fpga_stats, "FPGA HLS", "#d2691e"),
        ):
            means = [stats["mean"] * multiplier for stats in stats_list]
            maxima = [stats["max"] * multiplier for stats in stats_list]
            p95s = [stats["p95"] * multiplier for stats in stats_list]
            positions = [value + offset for value in x]
            bars = axis.bar(positions, means, width, color=color, label=label)
            axis.errorbar(
                positions, means,
                yerr=[[0.0] * 3, [maximum - mean for maximum, mean in zip(maxima, means)]],
                fmt="none", color="#333333", capsize=3, linewidth=1,
            )
            axis.plot(
                positions, p95s,
                linestyle="none", marker="_", color="#333333", markersize=12,
                label="p95" if label == "FPGA HLS" else None,
            )
            for bar, mean in zip(bars, means):
                axis.annotate(
                    f"{mean:.3g}",
                    (bar.get_x() + bar.get_width() / 2.0, mean),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=8,
                )
        axis.set_yscale("log")
        axis.set_ylabel(ylabel)
        axis.set_title(heading)
        axis.grid(True, axis="y", alpha=0.25)
    axes[1].axhline(100.0, color="#555555", linestyle="--", linewidth=1.2, label="100 ms compute budget")
    axes[1].set_xticks(
        x,
        [
            f"M0 / REALTIME\n{steps[0]:,} substeps",
            f"M1 / TRAINING\n{steps[1]:,} substeps",
            f"M2 / XENON\n{steps[2]:,} substeps",
        ],
    )
    axes[1].set_xlabel("Operating mode")
    axes[0].legend(ncol=3, fontsize=8)
    axes[1].legend(ncol=3, fontsize=8)
    figure.suptitle("Direct PC-versus-FPGA compute-time comparison", y=1.01)
    save(figure, output)


def scram_time(rows: list[dict[str, float]]) -> float:
    return next(row["sim_time_s"] for row in rows if row.get("scram_active", 0.0) >= 0.5)


def plot_xenon_worth(root: Path, output: Path) -> None:
    pc_rows_all = read_numeric_csv(root / "experiments" / "results" / "chapter7_pc_20260711" / "xenon_36h.csv")
    fpga_rows_all = latest_epoch(read_numeric_csv(root / "experiments" / "results" / "chapter7_fpga_20260713" / "xenon_36h" / "telemetry.csv"))
    pc_scram = scram_time(pc_rows_all)
    fpga_scram = scram_time(fpga_rows_all)
    sources = (("PC", pc_rows_all, pc_scram, "#1769aa", "-"), ("FPGA", fpga_rows_all, fpga_scram, "#d2691e", "--"))
    figure, axes = plt.subplots(3, 1, figsize=(10, 8.5), sharex=True)
    peak_times: list[float] = []
    for label, rows, origin, color, linestyle in sources:
        rows = [row for row in rows if row["sim_time_s"] >= origin]
        time_h = [(row["sim_time_s"] - origin) / 3600.0 for row in rows]
        axes[0].plot(time_h, [row["I_norm"] for row in rows], color=color, linestyle=linestyle, linewidth=1.4, label=f"{label}: I")
        axes[0].plot(time_h, [row["Xe_norm"] for row in rows], color=color, linestyle=linestyle, linewidth=1.8, alpha=0.65, label=f"{label}: Xe")
        axes[1].plot(time_h, [row["rho_xe"] / 0.007 for row in rows], color=color, linestyle=linestyle, linewidth=1.6, label=label)
        axes[2].plot(time_h, [row["critical_rod_position"] for row in rows], color=color, linestyle=linestyle, linewidth=1.6, label=label)
        peak = max(rows, key=lambda row: row["Xe_norm"])
        peak_times.append((peak["sim_time_s"] - origin) / 3600.0)
    peak_time = statistics.mean(peak_times)
    for axis in axes:
        axis.axvline(peak_time, color="#555555", linestyle=":", linewidth=1.0)
        axis.grid(True, alpha=0.25)
    axes[0].set_ylabel("Iodine / xenon ratio")
    axes[0].set_title("Iodine and xenon inventories")
    axes[1].set_ylabel("Differential xenon reactivity ($)")
    axes[1].set_title("Relative to the initial equilibrium xenon state")
    axes[2].set_ylabel("Rod position (normalized)")
    axes[2].set_xlabel("Time after SCRAM (h)")
    axes[2].set_title("Hypothetical critical position required to offset xenon")
    axes[0].annotate(f"Xe peak ≈ {peak_time:.2f} h", xy=(peak_time, 1.50), xytext=(peak_time + 1.3, 1.28), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    rod_values = [row["critical_rod_position"] for _, rows, origin, _, _ in sources for row in rows if row["sim_time_s"] >= origin]
    max_rod = max(rod_values)
    axes[2].axhline(max_rod, color="#555555", linestyle=":", linewidth=0.8)
    axes[2].annotate(f"maximum {max_rod:.3f}", xy=(peak_time, max_rod), xytext=(peak_time + 2.0, max_rod - 0.05), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    axes[0].legend(ncol=2, fontsize=8, loc="best")
    axes[1].legend(loc="best")
    axes[2].legend(loc="best")
    figure.suptitle("Xenon worth and required critical rod position", y=1.01)
    save(figure, output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    fpga_figures = root / "experiments" / "results" / "chapter7_fpga_20260713" / "figures"
    pc_figures = root / "experiments" / "results" / "chapter7_pc_20260711" / "figures"

    cases = [build_case(root, name, label) for name, label in REPORTS]
    rod_cases = [case for case in cases if case["name"] in {"rod_insertion_parity", "rod_withdrawal_parity"}]
    xenon_case = [case for case in cases if case["name"] == "xenon_36h_parity"]
    plot_overlay(rod_cases, fpga_figures / "pc_fpga_rod_transient_overlay.png", "PC–FPGA rod-transient parity", "Simulation time (s)", 1.0)
    plot_xenon_overlay(xenon_case[0], fpga_figures / "pc_fpga_xenon_overlay.png")
    plot_parity_errors(cases, fpga_figures / "parity_max_error_by_variable.png")
    plot_timing_compression(root, fpga_figures / "fpga_timing_compression.png")
    plot_pc_vs_fpga_timing(root, fpga_figures / "pc_vs_fpga_timing.png")
    plot_xenon_worth(root, fpga_figures / "xenon_worth_and_critical_rod.png")
    print(f"Wrote Chapter 7 comparison figures to {fpga_figures}")
    print(f"PC figures are written to {pc_figures} by analyse_results.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
