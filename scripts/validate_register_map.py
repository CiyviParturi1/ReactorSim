#!/usr/bin/env python3
"""Validate the exported HLS AXI-Lite map against the ARM application."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from xml.etree import ElementTree


ADDR_RE = re.compile(
    r"^#define\s+XPOINT_KINETICS_STEP_CTRL_ADDR_([A-Z0-9_]+)\s+0x([0-9a-fA-F]+)",
    re.MULTILINE,
)
PK_RE = re.compile(
    r"^#define\s+PK_[A-Z0-9_]+\s+(XPOINT_KINETICS_STEP_CTRL_ADDR_[A-Z0-9_]+)",
    re.MULTILINE,
)


def parse_header(path: Path) -> dict[str, int]:
    return {name: int(value, 16) for name, value in ADDR_RE.findall(path.read_text(encoding="utf-8"))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output_dir = (args.output_dir or root / "build" / "fpga_validation").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    header_paths = sorted(
        path
        for path in (root / "vitis").rglob("xpoint_kinetics_step_hw.h")
        if path.is_file()
    )
    component = root / "hls" / "point_kinetics_hls" / "point_kinetics_hls" / "hls" / "impl" / "ip" / "component.xml"
    app = root / "vitis" / "pk_app" / "src" / "main.c"

    checks: dict[str, object] = {
        "headers_found": [str(path.relative_to(root)) for path in header_paths],
        "component_xml": str(component.relative_to(root)),
        "status": "FAIL",
    }
    errors: list[str] = []

    if not header_paths:
        errors.append("No generated xpoint_kinetics_step_hw.h found under vitis/")
        canonical: dict[str, int] = {}
    else:
        canonical = parse_header(header_paths[0])
        checks["canonical_header"] = str(header_paths[0].relative_to(root))
        checks["register_count"] = len(canonical)
        for path in header_paths[1:]:
            parsed = parse_header(path)
            if parsed != canonical:
                errors.append(f"Register map differs from canonical header: {path.relative_to(root)}")

    if not app.is_file():
        errors.append(f"ARM application source not found: {app}")
    else:
        app_text = app.read_text(encoding="utf-8")
        app_symbols = PK_RE.findall(app_text)
        checks["arm_register_symbols"] = len(app_symbols)
        missing = sorted(
            symbol.removeprefix("XPOINT_KINETICS_STEP_CTRL_ADDR_")
            for symbol in app_symbols
            if symbol.removeprefix("XPOINT_KINETICS_STEP_CTRL_ADDR_") not in canonical
        )
        if missing:
            errors.append("ARM application references missing generated registers: " + ", ".join(missing))

    if not component.is_file():
        errors.append(f"Exported HLS IP component.xml not found: {component}")
    else:
        try:
            ElementTree.parse(component)
        except ElementTree.ParseError as exc:
            errors.append(f"Cannot parse component.xml: {exc}")
        component_text = component.read_text(encoding="utf-8")
        required_interfaces = ["s_axi_CTRL", "ap_clk", "ap_rst_n"]
        missing_interfaces = [name for name in required_interfaces if f">{name}<" not in component_text]
        checks["required_interfaces"] = required_interfaces
        if missing_interfaces:
            errors.append("Exported IP is missing interfaces: " + ", ".join(missing_interfaces))

    checks["errors"] = errors
    checks["status"] = "PASS" if not errors else "FAIL"
    json_path = output_dir / "register_map_report.json"
    md_path = output_dir / "register_map_report.md"
    json_path.write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# HLS IP register-map validation",
        "",
        f"Status: **{checks['status']}**",
        "",
        f"Generated headers compared: {len(header_paths)}",
        f"Canonical register count: {len(canonical)}",
        f"ARM register symbols checked: {checks.get('arm_register_symbols', 0)}",
        "",
        "Interfaces checked: `s_axi_CTRL`, `ap_clk`, `ap_rst_n`",
    ]
    if errors:
        lines.extend(["", "Errors:", ""] + [f"- {error}" for error in errors])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(checks, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
