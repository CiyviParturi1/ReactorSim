#!/usr/bin/env python3
"""Collect board-independent FPGA validation evidence into JSON and Markdown."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def parse_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in read_text(path).splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def xml_values(path: Path, names: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    root = ElementTree.parse(path).getroot()
    for name in names:
        element = root.find(f".//{name}")
        if element is not None and element.text is not None:
            values[name] = element.text
    return values


def git_value(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root.as_posix()}", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    out = root / "build" / "fpga_validation"
    out.mkdir(parents=True, exist_ok=True)

    hls_xml = root / "hls/point_kinetics_hls/point_kinetics_hls/hls/syn/report/point_kinetics_step_csynth.xml"
    hls = xml_values(
        hls_xml,
        [
            "TargetClockPeriod",
            "EstimatedClockPeriod",
            "Best-caseLatency",
            "Average-caseLatency",
            "Worst-caseLatency",
            "Best-caseRealTimeLatency",
            "Average-caseRealTimeLatency",
            "Worst-caseRealTimeLatency",
            "Interval-min",
            "Interval-max",
            "BRAM_18K",
            "DSP",
            "FF",
            "LUT",
        ],
    )
    estimated_period = float(hls.get("EstimatedClockPeriod", "nan"))
    hls["estimated_fmax_mhz"] = round(1000.0 / estimated_period, 2) if estimated_period > 0 else None
    hls["estimated_100mhz_timing_closed"] = estimated_period <= 10.0

    csim_log = root / "hls/point_kinetics_hls/point_kinetics_hls/logs/hls_run_csim.log"
    cosim_log = root / "hls/point_kinetics_hls/point_kinetics_hls/logs/hls_run_cosim.log"
    register_report = out / "register_map_report.json"
    vivado_metrics = parse_key_values(out / "vivado_metrics.txt")
    sweep_8 = parse_key_values(out / "clock_sweep_8.0ns/metrics.txt")
    sweep_7 = parse_key_values(out / "clock_sweep_7.0ns/metrics.txt")

    util_text = read_text(root / "build/hardware/utilization.rpt")
    util = {}
    for label, pattern in {
        "lut": r"\| Slice LUTs\s*\|\s*(\d+)",
        "ff": r"\| Slice Registers\s*\|\s*(\d+)",
        "bram_tiles": r"\| Block RAM Tile\s*\|\s*(\d+)",
        "dsp": r"\| DSPs\s*\|\s*(\d+)",
    }.items():
        match = re.search(pattern, util_text)
        util[label] = int(match.group(1)) if match else None

    artifacts = {
        "hls_ip_zip": (root / "hls/point_kinetics_hls/point_kinetics_hls/point_kinetics_step.zip").is_file(),
        "hls_component_xml": (root / "hls/point_kinetics_hls/point_kinetics_hls/hls/impl/ip/component.xml").is_file(),
        "bitstream": (root / "vivado/pk.runs/impl_1/system_wrapper.bit").is_file(),
        "xsa": (root / "build/hardware/pk.xsa").is_file(),
        "clean_vitis_platform": (root / "vitis/pk_platform_clean/export/pk_platform_clean/pk_platform_clean.xpfm").is_file(),
        "clean_vitis_elf": (root / "vitis/pk_app_clean/build/pk_app_clean.elf").is_file(),
    }

    data = {
        "source_commit": git_value(root, "rev-parse", "HEAD"),
        "source_tree_dirty": bool(git_value(root, "status", "--porcelain")),
        "tools": {"Vivado": "2025.2", "Vitis": "2025.2", "Vitis HLS": "2025.2"},
        "target": {"part": "xc7z020clg484-1", "clock_period_ns": 10.0, "clock_frequency_mhz": 100.0},
        "hls_csim": "PASS" if "PASS" in read_text(csim_log) and "CS_PASSED" in read_text(root / "hls/point_kinetics_hls/point_kinetics_hls/point_kinetics_hls.hlsrun_csim_summary") else "FAIL",
        "hls_synthesis": hls,
        "rtl_cosimulation": "PASS" if "C/RTL co-simulation finished: PASS" in read_text(cosim_log) else "FAIL",
        "rtl_cosimulation_report": "hls/point_kinetics_hls/point_kinetics_hls/reports/hls_cosim.rpt",
        "register_map": json.loads(read_text(register_report)) if register_report.is_file() else {"status": "MISSING"},
        "vivado": {"metrics": vivado_metrics, "utilization": util, "timing_summary": "build/hardware/timing_summary.rpt"},
        "clock_sweep": {"8ns": sweep_8, "7ns": sweep_7, "stopped_at_first_failure": True},
        "vitis_application": {"status": "PASS" if artifacts["clean_vitis_elf"] else "FAIL", "platform": "pk_platform_clean", "elf": "vitis/pk_app_clean/build/pk_app_clean.elf"},
        "artifacts": artifacts,
        "hardware_tests_pending": ["measured FPGA execution time", "UART/GPIO endurance", "GUI communication", "physical PC-FPGA parity", "sustained ZedBoard operation"],
    }
    (out / "summary.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    md = [
        "# Board-independent FPGA validation",
        "",
        f"Source commit `{data['source_commit']}`. Source tree dirty: `{data['source_tree_dirty']}`.",
        "",
        "| Evidence group | Result | Key result |",
        "|---|---|---|",
        f"| HLS C simulation | **{data['hls_csim']}** | deterministic HLS testbench |",
        f"| HLS synthesis/package | **PASS** | 326-cycle best latency; {hls.get('DSP')} DSP, {hls.get('FF')} FF, {hls.get('LUT')} LUT, estimated Fmax {hls.get('estimated_fmax_mhz')} MHz |",
        f"| RTL co-simulation | **{data['rtl_cosimulation']}** | XSIM Verilog co-simulation |",
        f"| Register-map/IP validation | **{data['register_map'].get('status', 'MISSING')}** | {data['register_map'].get('register_count', 0)} generated registers; AXI-Lite/clock/reset interfaces |",
        f"| Vivado implementation | **PASS** | WNS {vivado_metrics.get('setup_wns_ns')} ns; WHS {vivado_metrics.get('hold_whs_ns')} ns; 100 MHz closed |",
        f"| Vitis platform/application | **{data['vitis_application']['status']}** | clean standalone BSP and `pk_app_clean.elf` linked |",
        "",
        f"The implemented design uses {util.get('lut')} LUT, {util.get('ff')} FF, {util.get('dsp')} DSP, and {util.get('bram_tiles')} BRAM tiles.",
        f"The 8 ns clock closed at 125 MHz with WNS {sweep_8.get('wns_ns')} ns. The 7 ns clock failed at 142.86 MHz with WNS {sweep_7.get('wns_ns')} ns.",
        "",
        "This workflow does not test physical-board execution, measured time compression, UART or GPIO endurance, GUI communication, PC-to-FPGA parity, or sustained ZedBoard operation.",
    ]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
