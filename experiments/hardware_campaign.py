#!/usr/bin/env python3
"""Capture and analyse physical ZedBoard Chapter 7 evidence.

The script does not program the board. It records the artifacts selected for
a manual Vitis session, captures the UART stream, and writes the acceptance
results.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FRAME_SECONDS = 0.1
FIELD_NAMES = (
    "sim_time_s", "n", "Tf", "rho", "rho_dollars", "Tc", "I_norm", "Xe_norm",
    "rho_xe", "achieved_factor", "rod_position", "rod_target", "engine_status",
    "target_h_s", "step_real_time_s", "decay_heat", "plant_mode", "rho_rod_dollars",
    "rho_fuel_dollars", "rho_coolant_dollars", "rho_xenon_dollars",
    "critical_rod_position", "scram_active",
)
ARTIFACTS = {
    "bitstream": "vitis/pk_app_clean/_ide/bitstream/pk.bit",
    "xsa": "build/hardware/pk.xsa",
    "elf": "vitis/pk_app_clean/build/pk_app_clean.elf",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT,
        text=True, capture_output=True, check=False,
    )
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_record(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    if not path.is_file():
        return {"path": relative, "present": False}
    stat = path.stat()
    return {
        "path": relative,
        "present": True,
        "bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": sha256(path),
    }


def init_results(args: argparse.Namespace) -> int:
    output = args.results_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "generated_utc": utc_now(),
        "purpose": "Chapter 7 physical ZedBoard hardware acceptance evidence",
        "source": {
            "commit": git_value("rev-parse", "HEAD"),
            "branch": git_value("branch", "--show-current"),
            "tree_dirty": bool(git_value("status", "--porcelain")),
            "tree_status": git_value("status", "--porcelain"),
        },
        "board": {"model": "ZedBoard XC7Z020", "serial": args.board_serial},
        "target": {"clock_frequency_mhz": 100.0, "uart_port": args.port, "uart_baud": args.baud},
        "tools": {"vivado": args.vivado_version, "vitis": args.vitis_version},
        "artifacts": {name: artifact_record(path) for name, path in ARTIFACTS.items()},
        "operator": {"test_started_utc": args.test_time or utc_now()},
    }
    write_json(output / "metadata.json", metadata)
    (output / "README.md").write_text(
        "# Chapter 7 physical ZedBoard results\n\n"
        "This directory stores one board campaign. `metadata.json` identifies "
        "the board image and software artifacts. Each test folder keeps the "
        "original UART stream, capture settings, malformed-line record, and "
        "validation result. The UART text cannot be recreated by a PC test.\n\n"
        "Parsed telemetry and command-timeline CSV files are derived files and "
        "remain ignored by Git. The summary, parity reports, and figures contain "
        "the results used in Chapter 7.\n",
        encoding="utf-8",
    )
    print(f"Created {output}")
    return 0


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


def stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "median": None, "p95": None, "max": None}
    return {
        "count": len(values), "min": min(values), "mean": statistics.mean(values),
        "median": statistics.median(values), "p95": percentile(values, 0.95), "max": max(values),
    }


def parse_row(line: str) -> tuple[list[float] | None, str | None]:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != len(FIELD_NAMES):
        return None, f"field_count={len(parts)}"
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None, "non_numeric"
    if not all(math.isfinite(value) for value in values):
        return None, "non_finite"
    return values, None


def load_schedule(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("schedule must be a JSON list")
    events: list[dict[str, Any]] = []
    for index, event in enumerate(data):
        if not isinstance(event, dict) or not isinstance(event.get("command"), str):
            raise ValueError(f"schedule event {index} needs a string command")
        timing = [key for key in ("at_sim_time_s", "at_wall_s") if key in event]
        if len(timing) != 1 or not isinstance(event[timing[0]], (int, float)):
            raise ValueError(f"schedule event {index} needs exactly one numeric timing key")
        events.append(dict(event))
    return events


def validate_rows(rows: list[dict[str, str]], capture: dict[str, Any] | None = None) -> dict[str, Any]:
    values = [{key: float(row[key]) for key in FIELD_NAMES} for row in rows]
    times = [row["sim_time_s"] for row in values]
    host_times = [float(row["host_monotonic_s"]) for row in rows]
    restart_indices = [index for index, (a, b) in enumerate(zip(times, times[1:])) if b <= a]
    # A fresh Vitis run restarts simulated time. Analyse the most
    # recent continuous execution epoch, while retaining the reset as evidence.
    analysis_start = restart_indices[-1] + 1 if restart_indices else 0
    analysis_values = values[analysis_start:]
    analysis_host_times = host_times[analysis_start:]
    analysis_times = times[analysis_start:]
    frame_intervals = [b - a for a, b in zip(analysis_host_times, analysis_host_times[1:])]
    sim_frame_deltas = [b - a for a, b in zip(analysis_times, analysis_times[1:])]
    host_observed_factors = [
        sim_delta / wall_delta
        for sim_delta, wall_delta in zip(sim_frame_deltas, frame_intervals)
        if wall_delta > 0.0
    ]
    reversals = len(restart_indices)
    invalid_engine = sum(1 for row in analysis_values if row["engine_status"] <= 0.0)
    intervals_missed = sum(max(0, round(interval / FRAME_SECONDS) - 1) for interval in frame_intervals if interval > 1.5 * FRAME_SECONDS)
    has_rows = bool(analysis_values)
    expected_restarts = reversals == 0 or int((capture or {}).get("data_start_seen", 0)) >= reversals
    result = {
        "rows_received": len(rows),
        "rows_in_latest_execution_epoch": len(analysis_values),
        "data_start_seen": int((capture or {}).get("data_start_seen", 0)),
        "malformed_rows": int((capture or {}).get("malformed_rows", 0)),
        "wrong_field_counts": int((capture or {}).get("wrong_field_counts", 0)),
        "non_finite_values": int((capture or {}).get("non_finite_values", 0)),
        "simulation_time_reversals": reversals,
        "restart_events": reversals,
        "restarts_confirmed_by_data_start": expected_restarts,
        "invalid_engine_states": invalid_engine,
        "serial_disconnects": int((capture or {}).get("serial_disconnects", 0)),
        "frame_interval_s": stats(frame_intervals),
        "simulated_frame_advance_s": stats(sim_frame_deltas),
        "host_observed_factor": stats(host_observed_factors),
        "per_substep_execution_s": stats([row["step_real_time_s"] for row in analysis_values]),
        "achieved_factor": stats([row["achieved_factor"] for row in analysis_values]),
        "missed_100ms_frames": intervals_missed,
        "sim_time_start_s": analysis_times[0] if analysis_times else None,
        "sim_time_end_s": analysis_times[-1] if analysis_times else None,
        "analysis_scope": "latest continuous execution epoch",
        "acceptance": {
            "data_start": bool((capture or {}).get("data_start_seen", 0)),
            "exactly_23_fields": has_rows and int((capture or {}).get("wrong_field_counts", 0)) == 0,
            "finite": has_rows and int((capture or {}).get("non_finite_values", 0)) == 0,
            "monotonic_time": has_rows and expected_restarts,
            "valid_engine": has_rows and invalid_engine == 0,
        },
        "notes": {"missed_frame_definition": "estimated skipped frames for UART intervals >150 ms"},
    }
    return result


def validate_capture(test_dir: Path) -> dict[str, Any]:
    telemetry = test_dir / "telemetry.csv"
    capture_path = test_dir / "capture.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8")) if capture_path.is_file() else {}
    with telemetry.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    result = validate_rows(rows, capture)
    write_json(test_dir / "telemetry_validation.json", result)
    return result


def capture(args: argparse.Namespace) -> int:
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise SystemExit("pyserial is required: pip install pyserial") from exc
    test_dir = args.results_dir.resolve() / args.test_name
    test_dir.mkdir(parents=True, exist_ok=True)
    schedule = load_schedule(args.schedule)
    pending = list(schedule)
    start = time.monotonic()
    last_sim_time: float | None = None
    capture_info: dict[str, Any] = {
        "started_utc": utc_now(), "port": args.port, "baud": args.baud, "test_name": args.test_name,
        "data_start_seen": 0, "malformed_rows": 0, "wrong_field_counts": 0,
        "non_finite_values": 0, "serial_disconnects": 0, "pre_sync_discarded_lines": 0,
        "schedule": schedule,
    }
    with (test_dir / "uart_raw.txt").open("w", encoding="utf-8", newline="") as raw, \
         (test_dir / "malformed_lines.txt").open("w", encoding="utf-8", newline="") as malformed, \
         (test_dir / "command_timeline.csv").open("w", encoding="utf-8", newline="") as event_file, \
         (test_dir / "telemetry.csv").open("w", encoding="utf-8", newline="") as data_file:
        events = csv.DictWriter(event_file, fieldnames=("host_utc", "host_monotonic_s", "sim_time_s", "label", "command"))
        events.writeheader()
        writer = csv.DictWriter(data_file, fieldnames=("host_utc", "host_monotonic_s", *FIELD_NAMES))
        writer.writeheader()
        try:
            port = serial.Serial(args.port, args.baud, timeout=0.25)
        except Exception as exc:
            raise SystemExit(f"Could not open {args.port}: {exc}") from exc
        try:
            stream_synced = False
            while time.monotonic() - start < args.max_wall_s:
                try:
                    text = port.readline().decode("utf-8", errors="replace").rstrip("\r\n")
                except Exception as exc:
                    capture_info["serial_disconnects"] += 1
                    malformed.write(f"serial_error: {exc}\n")
                    break
                if not text:
                    continue
                host_mono = time.monotonic() - start
                raw.write(text + "\n")
                raw.flush()
                if "DATA_START" in text:
                    capture_info["data_start_seen"] += 1
                    continue
                if "," not in text:
                    continue
                row, reason = parse_row(text)
                if reason:
                    # Opening a live UART can begin in the middle of a frame.
                    # Discard only these leading fragments; later malformed rows
                    # remain evidence of a framing failure.
                    if not stream_synced:
                        capture_info["pre_sync_discarded_lines"] += 1
                        malformed.write(f"{host_mono:.9f},pre_sync_{reason},{text}\n")
                        continue
                    capture_info["malformed_rows"] += 1
                    if reason.startswith("field_count"):
                        capture_info["wrong_field_counts"] += 1
                    if reason == "non_finite":
                        capture_info["non_finite_values"] += 1
                    malformed.write(f"{host_mono:.9f},{reason},{text}\n")
                    continue
                assert row is not None
                stream_synced = True
                last_sim_time = row[0]
                writer.writerow({"host_utc": utc_now(), "host_monotonic_s": f"{host_mono:.9f}", **dict(zip(FIELD_NAMES, row))})
                data_file.flush()
                for event in list(pending):
                    due = ("at_wall_s" in event and host_mono >= float(event["at_wall_s"])) or (
                        "at_sim_time_s" in event and last_sim_time >= float(event["at_sim_time_s"])
                    )
                    if due:
                        command = event["command"].strip()
                        port.write((command + "\n").encode("ascii"))
                        events.writerow({"host_utc": utc_now(), "host_monotonic_s": f"{host_mono:.9f}", "sim_time_s": f"{last_sim_time:.9f}", "label": event.get("label", ""), "command": command})
                        event_file.flush()
                        pending.remove(event)
                        # A simulated-time command can reset simulation time.
                        # Wait for the next telemetry row before evaluating the
                        # remaining simulated-time events against the new state.
                        if "at_sim_time_s" in event:
                            break
                if args.until_sim_time_s is not None and last_sim_time >= args.until_sim_time_s and not pending:
                    break
        finally:
            port.close()
    capture_info["finished_utc"] = utc_now()
    capture_info["elapsed_wall_s"] = time.monotonic() - start
    capture_info["last_sim_time_s"] = last_sim_time
    capture_info["unexecuted_schedule_events"] = pending
    write_json(test_dir / "capture.json", capture_info)
    summary = validate_capture(test_dir)
    print(json.dumps(summary, indent=2))
    return 0


def csv_rows(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8") as handle:
        raw_rows = list(csv.DictReader(handle))
    result: list[dict[str, float]] = []
    for raw in raw_rows:
        row: dict[str, float] = {}
        for key, value in raw.items():
            if value in (None, ""):
                continue
            try:
                row[key] = float(value)
            except ValueError:
                # PC evidence also contains descriptive scenario/event columns.
                continue
        if "sim_time_s" in row:
            result.append(row)
    return result


def interpolate(rows: list[dict[str, float]], key: str, at_time: float) -> float | None:
    if not rows or at_time < rows[0]["sim_time_s"] or at_time > rows[-1]["sim_time_s"]:
        return None
    for left, right in zip(rows, rows[1:]):
        if left["sim_time_s"] <= at_time <= right["sim_time_s"]:
            span = right["sim_time_s"] - left["sim_time_s"]
            if span <= 0:
                return None
            fraction = (at_time - left["sim_time_s"]) / span
            return left[key] + fraction * (right[key] - left[key])
    return rows[-1][key] if at_time == rows[-1]["sim_time_s"] else None


def latest_continuous_epoch(rows: list[dict[str, float]]) -> list[dict[str, float]]:
    """Discard rows preceding the last deliberate simulation-time reset."""
    start = 0
    previous: float | None = None
    for index, row in enumerate(rows):
        current = row["sim_time_s"]
        if previous is not None and current < previous:
            start = index
        previous = current
    return rows[start:]


def parity(args: argparse.Namespace) -> int:
    fpga = sorted(latest_continuous_epoch(csv_rows(args.fpga_csv)), key=lambda row: row["sim_time_s"])
    pc = sorted(csv_rows(args.pc_csv), key=lambda row: row["sim_time_s"])
    mappings = {"N": "n", "T_f": "Tf", "T_c": "Tc", "I": "I_norm", "Xe": "Xe_norm", "rho": "rho", "P_decay": "decay_heat", "rod_position": "rod_position"}
    fpga_offset = 0.0
    pc_offset = 0.0
    if args.align_scram:
        fpga_scram = next((row["sim_time_s"] for row in fpga if row.get("scram_active", 0.0) >= 0.5), None)
        pc_scram = next((row["sim_time_s"] for row in pc if row.get("scram_active", 0.0) >= 0.5), None)
        if fpga_scram is None or pc_scram is None:
            raise SystemExit("--align-scram requires scram_active telemetry in both files")
        fpga_offset = fpga_scram
        pc_offset = pc_scram
    summary: dict[str, Any] = {
        "fpga_csv": str(args.fpga_csv), "pc_csv": str(args.pc_csv), "tolerance": args.tolerance,
        "alignment": "scram" if args.align_scram else "absolute_simulated_time",
        "fpga_time_origin_s": fpga_offset, "pc_time_origin_s": pc_offset, "variables": {},
    }
    for label, key in mappings.items():
        comparisons: list[tuple[float, float]] = []
        for hw in fpga:
            expected = interpolate(pc, key, pc_offset + (hw["sim_time_s"] - fpga_offset))
            if expected is not None and key in hw:
                comparisons.append((hw[key], expected))
        errors = [actual - expected for actual, expected in comparisons]
        absolute = [abs(error) for error in errors]
        summary["variables"][label] = {
            "points": len(errors), "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)) if errors else None,
            "max_abs": max(absolute) if absolute else None,
            "within_scaled_tolerance": all(
                abs(actual - expected) <= args.tolerance * (1.0 + abs(actual) + abs(expected))
                for actual, expected in comparisons
            ),
        }
    summary["all_variables_within_scaled_tolerance"] = all(value["within_scaled_tolerance"] for value in summary["variables"].values())
    write_json(args.output, summary)
    print(json.dumps(summary, indent=2))
    return 0


def hardware_xenon_summary(path: Path) -> dict[str, Any] | None:
    rows = csv_rows(path)
    if not rows:
        return None
    scram_rows = [row for row in rows if row.get("scram_active", 0.0) >= 0.5]
    if not scram_rows:
        return None
    scram_time = scram_rows[0]["sim_time_s"]
    post_scram = [row for row in rows if row["sim_time_s"] >= scram_time]
    peak = max(post_scram, key=lambda row: row["Xe_norm"])
    worst_worth = min(post_scram, key=lambda row: row["rho_xe"])
    settled = [row for row in post_scram if row["sim_time_s"] >= peak["sim_time_s"] and abs(row["Xe_norm"] - 1.0) <= 0.01]
    return {
        "scram_time_s": scram_time,
        "duration_after_scram_h": (post_scram[-1]["sim_time_s"] - scram_time) / 3600.0,
        "iodine_at_xenon_peak": peak["I_norm"],
        "maximum_xenon_ratio": peak["Xe_norm"],
        "xenon_peak_time_h": (peak["sim_time_s"] - scram_time) / 3600.0,
        "maximum_xenon_worth_dollars": worst_worth["rho_xe"] / 0.007,
        "xenon_worth_time_h": (worst_worth["sim_time_s"] - scram_time) / 3600.0,
        "return_within_1pct_h": (settled[0]["sim_time_s"] - scram_time) / 3600.0 if settled else None,
        "maximum_critical_rod_position": max(row["critical_rod_position"] for row in post_scram),
    }


def make_xenon_plot(telemetry: Path, output: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    rows = latest_continuous_epoch(csv_rows(telemetry))
    scram_rows = [row for row in rows if row.get("scram_active", 0.0) >= 0.5]
    if not scram_rows:
        return False
    scram_time = scram_rows[0]["sim_time_s"]
    rows = [row for row in rows if row["sim_time_s"] >= scram_time]
    figure, axis = plt.subplots(figsize=(10, 5.5))
    time_h = [(row["sim_time_s"] - scram_time) / 3600.0 for row in rows]
    axis.plot(time_h, [row["I_norm"] for row in rows], label="I norm")
    axis.plot(time_h, [row["Xe_norm"] for row in rows], label="Xe norm")
    peak = max(rows, key=lambda row: row["Xe_norm"])
    peak_h = (peak["sim_time_s"] - scram_time) / 3600.0
    axis.axvline(peak_h, color="#555555", linestyle="--", linewidth=1, label=f"Xe peak ({peak_h:.2f} h)")
    axis.scatter([peak_h], [peak["Xe_norm"]], color="#b22222", zorder=4)
    axis.annotate(
        f"Xe peak {peak['Xe_norm']:.3f}", xy=(peak_h, peak["Xe_norm"]),
        xytext=(peak_h + 1.2, peak["Xe_norm"] - 0.12),
        arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9,
    )
    axis.set_title("Physical FPGA iodine-xenon transient after SCRAM")
    axis.set_xlabel("time after SCRAM (h)")
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=160)
    plt.close(figure)
    return True


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "(no recorded tests)"
    header = "| " + " | ".join(columns) + " |\n|" + "|".join("---" for _ in columns) + "|\n"
    return header + "".join("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |\n" for row in rows)


def campaign_summary(args: argparse.Namespace) -> int:
    results_dir = args.results_dir.resolve()
    metadata_path = results_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    tests: list[dict[str, Any]] = []
    xenon: dict[str, Any] | None = None
    xenon_file: Path | None = None
    for validation_path in sorted(results_dir.glob("*/telemetry_validation.json")):
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        validation["test"] = validation_path.parent.name
        tests.append(validation)
        telemetry = validation_path.parent / "telemetry.csv"
        if "xenon" in validation_path.parent.name.lower() and telemetry.is_file():
            xenon = hardware_xenon_summary(telemetry)
            xenon_file = telemetry
    parity_reports = []
    parity_summary: list[dict[str, Any]] = []
    for parity_path in sorted(results_dir.rglob("*parity*.json")):
        try:
            report = json.loads(parity_path.read_text(encoding="utf-8"))
            parity_reports.append(report)
            variables = list(report.get("variables", {}).values())
            parity_summary.append({
                "report": parity_path.stem,
                "pass": report.get("all_variables_within_scaled_tolerance", False),
                "points": max((variable.get("points", 0) or 0 for variable in variables), default=0),
                "worst_rmse": max((variable.get("rmse", 0.0) or 0.0 for variable in variables), default=0.0),
                "worst_max_abs": max((variable.get("max_abs", 0.0) or 0.0 for variable in variables), default=0.0),
            })
        except json.JSONDecodeError:
            continue
    acceptance = [{
        "test": test["test"], "rows": test["rows_received"], "latest_epoch_rows": test["rows_in_latest_execution_epoch"],
        "restarts": test["restart_events"], "DATA_START": test["acceptance"]["data_start"],
        "23_fields": test["acceptance"]["exactly_23_fields"], "finite": test["acceptance"]["finite"],
        "monotonic_time": test["acceptance"]["monotonic_time"], "engine_valid": test["acceptance"]["valid_engine"],
        "malformed": test["malformed_rows"], "missed_frames": test["missed_100ms_frames"],
    } for test in tests]
    timing = [{
        "test": test["test"], "frames": test["rows_received"],
        "achieved_factor_mean": test["achieved_factor"]["mean"],
        "host_observed_factor_mean": test["host_observed_factor"]["mean"],
        "substep_min_s": test["per_substep_execution_s"]["min"],
        "substep_mean_s": test["per_substep_execution_s"]["mean"],
        "substep_median_s": test["per_substep_execution_s"]["median"],
        "substep_p95_s": test["per_substep_execution_s"]["p95"],
        "substep_max_s": test["per_substep_execution_s"]["max"],
        "frame_p95_s": test["frame_interval_s"]["p95"], "missed_frames": test["missed_100ms_frames"],
    } for test in tests]
    summary = {"metadata": metadata, "physical_acceptance": acceptance, "execution_timing": timing, "xenon": xenon, "parity": parity_reports, "parity_summary": parity_summary}
    write_json(results_dir / "summary.json", summary)
    lines = [
        "# Chapter 7 physical ZedBoard results", "",
        "Recorded UART data in this directory produced this report.", "",
        "## Physical acceptance matrix", "", markdown_table(acceptance, ["test", "rows", "latest_epoch_rows", "restarts", "DATA_START", "23_fields", "finite", "monotonic_time", "engine_valid", "malformed", "missed_frames"]), "",
        "## Measured FPGA execution and compression", "", markdown_table(timing, ["test", "frames", "achieved_factor_mean", "host_observed_factor_mean", "substep_min_s", "substep_mean_s", "substep_median_s", "substep_p95_s", "substep_max_s", "frame_p95_s", "missed_frames"]), "",
        "## Hardware iodine-xenon run", "", markdown_table([xenon] if xenon else [], ["duration_after_scram_h", "iodine_at_xenon_peak", "maximum_xenon_ratio", "xenon_peak_time_h", "maximum_xenon_worth_dollars", "return_within_1pct_h", "maximum_critical_rod_position"]), "",
        "## PC-to-FPGA parity", "", f"Recorded parity reports: {len(parity_reports)}.", "",
        markdown_table(parity_summary, ["report", "pass", "points", "worst_rmse", "worst_max_abs"]),
    ]
    if xenon_file and make_xenon_plot(xenon_file, results_dir / "figures" / "hardware_xenon.png"):
        lines.extend(["", "Hardware xenon graph: `figures/hardware_xenon.png`."])
    (results_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {results_dir / 'summary.md'}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create a fingerprinted result directory")
    init.add_argument("--results-dir", required=True, type=Path)
    init.add_argument("--board-serial", default="unknown")
    init.add_argument("--port", default="COM7")
    init.add_argument("--baud", default=115200, type=int)
    init.add_argument("--vivado-version", default="Vivado 2025.2")
    init.add_argument("--vitis-version", default="Vitis 2025.2")
    init.add_argument("--test-time")
    capture_parser = commands.add_parser("capture", help="capture UART and issue a deterministic command schedule")
    capture_parser.add_argument("--results-dir", required=True, type=Path)
    capture_parser.add_argument("--test-name", required=True)
    capture_parser.add_argument("--port", default="COM7")
    capture_parser.add_argument("--baud", default=115200, type=int)
    capture_parser.add_argument("--schedule", type=Path)
    capture_parser.add_argument("--until-sim-time-s", type=float)
    capture_parser.add_argument("--max-wall-s", type=float, default=180.0)
    validate = commands.add_parser("validate", help="validate an already captured telemetry CSV")
    validate.add_argument("--test-dir", required=True, type=Path)
    compare = commands.add_parser("parity", help="align FPGA and PC data by simulated time")
    compare.add_argument("--fpga-csv", required=True, type=Path)
    compare.add_argument("--pc-csv", required=True, type=Path)
    compare.add_argument("--output", required=True, type=Path)
    compare.add_argument("--tolerance", type=float, default=2.0e-5, help="native PC/HLS scaled tolerance")
    compare.add_argument("--align-scram", action="store_true", help="align simulated-time origins at SCRAM")
    summary = commands.add_parser("summary", help="write final Markdown and JSON evidence summary")
    summary.add_argument("--results-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "init":
        return init_results(args)
    if args.command == "capture":
        return capture(args)
    if args.command == "validate":
        print(json.dumps(validate_capture(args.test_dir.resolve()), indent=2))
        return 0
    if args.command == "parity":
        return parity(args)
    if args.command == "summary":
        return campaign_summary(args)
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
