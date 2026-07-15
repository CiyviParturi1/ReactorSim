#!/usr/bin/env python3
"""Analyse the deterministic PC accident-surrogate campaign."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


IAEA_CHERNOBYL = "https://pub.iaea.org/MTCD/publications/PDF/Pub913e_web.pdf"
NRC_TMI = "https://www.nrc.gov/reading-rm/doc-collections/fact-sheets/3mile-isle"
NRC_TMI_TIMELINE = (
    "https://www.nrc.gov/reading-rm/doc-collections/gen-comm/bulletins/1979/bl79005a"
)


def read_trace(path: Path) -> list[dict[str, Any]]:
    numeric = {
        "sim_time_s", "n", "thermal_power", "Tf", "Tc", "rho", "rho_dollars",
        "rod_position", "rod_target", "I_norm", "Xe_norm", "rho_xe", "decay_heat",
        "plant_mode", "scram_active", "numerical_fault",
    }
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in numeric:
            row[key] = float(row[key])
    return rows


def extremum(rows: list[dict[str, Any]], key: str, maximum: bool = True) -> dict[str, float]:
    fn = max if maximum else min
    row = fn(rows, key=lambda item: item[key])
    return {"value": row[key], "time_s": row["sim_time_s"]}


def event_time(rows: list[dict[str, Any]], name: str) -> float:
    return next(row["sim_time_s"] for row in rows if row["event"] == name)


def sample_at(rows: list[dict[str, Any]], time_s: float) -> dict[str, Any]:
    return min(rows, key=lambda row: abs(row["sim_time_s"] - time_s))


def event_count(rows: list[dict[str, Any]], name: str) -> int:
    return sum(row["event"] == name for row in rows)


def nondecreasing_time(rows: list[dict[str, Any]]) -> bool:
    return all(left["sim_time_s"] <= right["sim_time_s"] for left, right in zip(rows, rows[1:]))


def trace_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    finite = all(
        math.isfinite(row[key])
        for row in rows
        for key in ("sim_time_s", "n", "thermal_power", "Tf", "Tc", "rho", "Xe_norm")
    )
    initial_n = rows[0]["n"]
    peak_n = extremum(rows, "n")
    return {
        "rows": len(rows),
        "initial_n": initial_n,
        "peak_n": peak_n,
        "peak_factor_from_initial": peak_n["value"] / initial_n,
        "peak_fuel_temperature_C": extremum(rows, "Tf"),
        "peak_coolant_temperature_C": extremum(rows, "Tc"),
        "peak_positive_reactivity": extremum(rows, "rho"),
        "final": {
            "time_s": rows[-1]["sim_time_s"],
            "n": rows[-1]["n"],
            "Tf_C": rows[-1]["Tf"],
            "Tc_C": rows[-1]["Tc"],
            "decay_heat": rows[-1]["decay_heat"],
        },
        "all_finite": finite,
        "numerical_faults": sum(int(row["numerical_fault"]) for row in rows),
    }


def plot_chernobyl(traces: dict[str, list[dict[str, Any]]], output: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    styles = {
        "chernobyl_rbmk_like": ("RBMK-like (C1)", "#b22222"),
        "chernobyl_modern_pwr": ("Modern PWR-SMR (C0)", "#1769aa"),
    }
    for name, (label, color) in styles.items():
        rows = traces[name]
        x = [(row["sim_time_s"] - 20.0) for row in rows]
        axes[0].plot(x, [row["n"] for row in rows], label=label, color=color)
        axes[1].plot(x, [row["Tf"] for row in rows], label=label, color=color)
        axes[2].plot(x, [row["rho_dollars"] for row in rows], label=label, color=color)
    for axis in axes:
        axis.axvline(36, color="#555555", linestyle="--", linewidth=1, label="AZ-5 / SCRAM" if axis is axes[0] else None)
        axis.axvline(42, color="#b22222", linestyle=":", linewidth=1, label="RBMK surrogate shutdown insertion" if axis is axes[0] else None)
        axis.grid(alpha=0.25)
    axes[0].set_ylabel("Normalized neutron power")
    axes[1].set_ylabel("Fuel temperature (deg C)")
    axes[2].set_ylabel("Reactivity ($)")
    axes[2].set_xlabel("Time since test start (s)")
    axes[0].legend(loc="upper left")
    peak = extremum(traces["chernobyl_rbmk_like"], "n")
    axes[0].annotate(
        f"Peak {peak['value']:.2f}\n({peak['value'] / traces['chernobyl_rbmk_like'][0]['n']:.1f}x initial)",
        xy=(peak["time_s"] - 20.0, peak["value"]), xytext=(52, peak["value"] * 0.78),
        arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9,
    )
    fig.suptitle("Simplified Chernobyl-style low-power transient")
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_tmi(traces: dict[str, list[dict[str, Any]]], output: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    styles = {
        "tmi_loss_of_cooling": ("TMI-like cooling loss (C2)", "#d2691e"),
        "tmi_modern_pwr": ("Modern PWR-SMR (C0)", "#1769aa"),
    }
    for name, (label, color) in styles.items():
        rows = traces[name]
        x = [row["sim_time_s"] / 3600.0 for row in rows]
        axes[0].plot(x, [row["Tf"] for row in rows], label=f"{label}, fuel", color=color, linewidth=2)
        axes[0].plot(x, [row["Tc"] for row in rows], label=f"{label}, coolant", color=color, linestyle="--")
    loss = traces["tmi_loss_of_cooling"]
    modern = traces["tmi_modern_pwr"]
    x = [row["sim_time_s"] / 3600.0 for row in loss]
    fuel_penalty = [left["Tf"] - right["Tf"] for left, right in zip(loss, modern)]
    coolant_penalty = [left["Tc"] - right["Tc"] for left, right in zip(loss, modern)]
    axes[1].plot(x, fuel_penalty, label="Excess fuel temperature", color="#b22222", linewidth=2)
    axes[1].plot(x, coolant_penalty, label="Excess coolant temperature", color="#d2691e", linestyle="--")
    axes[1].fill_between(x, 0, fuel_penalty, color="#b22222", alpha=0.12)
    for axis in axes:
        axis.axvline(1.75, color="#555555", linestyle="--", linewidth=1, label="Core-uncovery surrogate" if axis is axes[0] else None)
        axis.axvline(2.3, color="#555555", linestyle=":", linewidth=1, label="Cooling restored" if axis is axes[0] else None)
        axis.grid(alpha=0.25)
    axes[0].set_ylabel("Temperature (deg C)")
    axes[1].set_ylabel("Temperature above modern C0 (deg C)")
    axes[1].set_xlabel("Time after feedwater loss (h)")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[1].legend(loc="upper right", fontsize=8)
    peak = extremum(loss, "Tf")
    axes[0].annotate(
        f"Delayed peak\n{peak['value']:.0f} deg C",
        xy=(peak["time_s"] / 3600.0, peak["value"]), xytext=(2.55, peak["value"] - 90),
        arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9,
    )
    fig.suptitle("Simplified TMI-style loss of cooling and core-uncovery surrogate")
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir", type=Path)
    args = parser.parse_args()
    results = args.results_dir
    names = (
        "chernobyl_rbmk_like", "chernobyl_modern_pwr",
        "tmi_loss_of_cooling", "tmi_modern_pwr",
    )
    traces = {name: read_trace(results / f"{name}.csv") for name in names}
    metrics = {name: trace_metrics(rows) for name, rows in traces.items()}

    rbmk = traces["chernobyl_rbmk_like"]
    modern_ch = traces["chernobyl_modern_pwr"]
    tmi = traces["tmi_loss_of_cooling"]
    modern_tmi = traces["tmi_modern_pwr"]
    ch_test = event_time(rbmk, "test_start_and_rod_withdrawal")
    ch_az5 = event_time(rbmk, "az5_command_shutdown_delayed")
    ch_shutdown = event_time(rbmk, "delayed_negative_shutdown_insertion")
    tmi_trip = event_time(tmi, "reactor_trip")
    historical_heatup = event_time(tmi, "core_uncovery_heatup_surrogate_begins")

    scenario_definition = {
        "chernobyl_style": {
            "duration_s": 120.0,
            "frame_s": 0.1,
            "initial_power": 0.0625,
            "initial_iodine_ratio": 1.0,
            "initial_xenon_ratio": 1.25,
            "requested_rod_reactivity": 0.0025,
            "events_s": {"rod_withdrawal": 20.0, "AZ5": 56.0, "RBMK_shutdown_effect": 62.0},
            "presets": {"accident": 1, "modern_comparison": 0},
        },
        "tmi_style": {
            "duration_s": 14400.0,
            "frame_s": 1.0,
            "initial_power": 1.0,
            "events_s": {"feedwater_loss": 0.0, "reactor_trip": 12.0, "pump_reduction": 600.0, "core_uncovery_surrogate": 6300.0, "cooling_restored": 8280.0},
            "surrogate_parameters": {"degraded_gamma": 0.01, "uncovered_gamma": 0.00025, "uncovered_K_heat": 25.0},
            "presets": {"accident": 2, "modern_comparison": 0},
        },
    }
    accuracy = {
        "chernobyl": {
            "historical_reference": IAEA_CHERNOBYL,
            "test_to_AZ5_s": ch_az5 - ch_test,
            "AZ5_to_surrogate_shutdown_insertion_s": ch_shutdown - ch_az5,
            "rbmk_peak_time_after_AZ5_s": metrics["chernobyl_rbmk_like"]["peak_n"]["time_s"] - ch_az5,
            "timing_character_match": abs((ch_az5 - ch_test) - 36.0) < 0.001 and abs((ch_shutdown - ch_az5) - 6.0) < 0.001,
            "magnitude_validated": False,
            "assessment": "Timing is imposed from the historical sequence and the positive-feedback preset produces a rapid rise. The lumped model cannot validate accident magnitude because it has no void fraction, graphite-displacer effect, spatial kinetics, pressure, or structural failure.",
        },
        "tmi": {
            "historical_references": [NRC_TMI, NRC_TMI_TIMELINE],
            "reactor_trip_s": tmi_trip,
            "NRC_trip_window_s": [9.0, 12.0],
            "trip_timing_match": 9.0 <= tmi_trip <= 12.01,
            "scheduled_core_uncovery_s": historical_heatup,
            "scheduled_peak_fuel_temperature_s": metrics["tmi_loss_of_cooling"]["peak_fuel_temperature_C"]["time_s"],
            "scheduled_heatup_timing_match": 6300.0 <= metrics["tmi_loss_of_cooling"]["peak_fuel_temperature_C"]["time_s"] <= 8280.01,
            "assessment": "The prompt trip, staged cooling degradation, delayed core-uncovery heat-up and recovery after relief-valve isolation are represented as a presentation surrogate. The event timing is imposed; coolant inventory and pressure are not solved.",
        },
    }

    checks = {
        "expected_trace_lengths": len(rbmk) == 1204 and len(modern_ch) == 1203 and len(tmi) == 14405 and len(modern_tmi) == 14405,
        "time_is_nondecreasing": all(nondecreasing_time(rows) for rows in traces.values()),
        "scenario_names_are_consistent": all(all(row["scenario"] == name for row in rows) for name, rows in traces.items()),
        "expected_events_occur_once": (
            event_count(rbmk, "test_start_and_rod_withdrawal") == 1
            and event_count(rbmk, "az5_command_shutdown_delayed") == 1
            and event_count(rbmk, "delayed_negative_shutdown_insertion") == 1
            and event_count(modern_ch, "automatic_scram") == 1
            and event_count(tmi, "reactor_trip") == 1
            and event_count(tmi, "core_uncovery_heatup_surrogate_begins") == 1
            and event_count(tmi, "relief_valve_isolated_and_cooling_restored") == 1
        ),
        "scheduled_event_times_match": (
            abs(ch_test - 20.0) < 0.001 and abs(ch_az5 - 56.0) < 0.001
            and abs(ch_shutdown - 62.0) < 0.001 and abs(tmi_trip - 12.0) < 0.001
            and abs(historical_heatup - 6300.0) < 0.01
            and abs(event_time(tmi, "relief_valve_isolated_and_cooling_restored") - 8280.0) < 0.01
        ),
        "all_traces_finite": all(value["all_finite"] for value in metrics.values()),
        "zero_numerical_faults": all(value["numerical_faults"] == 0 for value in metrics.values()),
        "rbmk_peak_exceeds_10x_initial": metrics["chernobyl_rbmk_like"]["peak_factor_from_initial"] >= 10.0,
        "rbmk_peak_exceeds_modern": metrics["chernobyl_rbmk_like"]["peak_n"]["value"] > metrics["chernobyl_modern_pwr"]["peak_n"]["value"],
        "modern_scram_collapses_power_within_1s": sample_at(modern_ch, 57.0)["n"] < 0.01,
        "tmi_like_delayed_fuel_peak_exceeds_modern_by_200C": metrics["tmi_loss_of_cooling"]["peak_fuel_temperature_C"]["value"] > metrics["tmi_modern_pwr"]["peak_fuel_temperature_C"]["value"] + 200.0,
        "tmi_trip_timing_matches_NRC_window": accuracy["tmi"]["trip_timing_match"],
        "tmi_delayed_heatup_occurs_in_scheduled_window": accuracy["tmi"]["scheduled_heatup_timing_match"],
        "tmi_cooling_restoration_returns_below_300C": sample_at(tmi, 10800.0)["Tf"] < 300.0 and sample_at(tmi, 10800.0)["Tc"] < 300.0,
    }
    summary = {
        "campaign": "PC accident-character surrogate tests",
        "scope": "Educational lumped point-kinetics and two-node thermal model; not an accident-analysis code.",
        "scenario_definition": scenario_definition,
        "metrics": metrics,
        "accuracy": accuracy,
        "checks": checks,
    }
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (results / "scenario_definition.json").write_text(
        json.dumps(scenario_definition, indent=2) + "\n", encoding="utf-8"
    )

    figures = results / "figures"
    figures.mkdir(exist_ok=True)
    plot_chernobyl(traces, figures / "chernobyl_comparison.png")
    plot_tmi(traces, figures / "tmi_comparison.png")

    rbmk_m = metrics["chernobyl_rbmk_like"]
    pwr_m = metrics["chernobyl_modern_pwr"]
    tmi_m = metrics["tmi_loss_of_cooling"]
    tmi_pwr_m = metrics["tmi_modern_pwr"]
    report = f"""# PC accident-character simulation results

These are **simplified educational surrogates**, not validated reconstructions or safety analyses. The model contains lumped point kinetics, iodine/xenon, decay heat, two temperatures and rod feedback; it does not model coolant inventory, void fraction, pressure, core coverage, spatial power, graphite displacers or material failure.

## Results

| Scenario | Main result | Modern C0 comparison | Numerical status |
|---|---:|---:|---|
| Chernobyl-style C1 | peak neutron power {rbmk_m['peak_n']['value']:.3f} ({rbmk_m['peak_factor_from_initial']:.2f}x initial), {accuracy['chernobyl']['rbmk_peak_time_after_AZ5_s']:.1f} s after AZ-5 | peak {pwr_m['peak_n']['value']:.3f} ({pwr_m['peak_factor_from_initial']:.2f}x); immediate SCRAM | finite, no fault |
| TMI-style C2 | delayed fuel peak {tmi_m['peak_fuel_temperature_C']['value']:.1f} deg C at {tmi_m['peak_fuel_temperature_C']['time_s'] / 3600.0:.2f} h | peak fuel {tmi_pwr_m['peak_fuel_temperature_C']['value']:.1f} deg C at startup, then cooling | finite, no fault |

## Scenario timing and interpretation

- **Chernobyl character:** test start to AZ-5 is {accuracy['chernobyl']['test_to_AZ5_s']:.1f} s and the surrogate negative shutdown insertion is delayed another {accuracy['chernobyl']['AZ5_to_surrogate_shutdown_insertion_s']:.1f} s. C1's positive coolant-temperature feedback produces a continuing rapid rise while C0's prompt SCRAM collapses power. These timings are imposed to mirror the IAEA sequence; accident magnitude is **not validated**.
- **TMI character:** reactor trip occurs at {tmi_trip:.1f} s, within the NRC 9-12 s range. Cooling degrades at 10 min, the core-uncovery surrogate begins at 1.75 h, and cooling is restored at 2.3 h. These scheduled stages create the intended delayed heat-up and recovery shape for presentation.

## Automated checks

| Check | Result |
|---|---|
"""
    for name, passed in checks.items():
        report += f"| {name.replace('_', ' ')} | {'PASS' if passed else 'FAIL'} |\n"
    report += f"""

The TMI core-uncovery stage is a transparent presentation surrogate implemented by reducing fuel-to-coolant coupling; it is not a solved coolant-inventory model. Higher-fidelity work would require coolant level, pressure and relief-flow dynamics. The Chernobyl surrogate similarly schedules its shutdown delay rather than modelling rod/displacer geometry.

## References

- IAEA, *INSAG-7: The Chernobyl Accident*: {IAEA_CHERNOBYL}
- US NRC, *Backgrounder on the Three Mile Island Accident*: {NRC_TMI}
- US NRC, *Bulletin 79-05A accident timeline*: {NRC_TMI_TIMELINE}
"""
    (results / "summary.md").write_text(report, encoding="utf-8")
    print(f"Wrote {results / 'summary.json'}")
    print(f"Wrote {results / 'summary.md'}")
    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        print(f"FAILED checks: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
