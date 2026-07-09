#!/usr/bin/env python3
"""Merge wrapped C/C++ continuation lines unless clearly a long signature/call."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_LINE = 200


def tracked_sources() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.c", "*.h", "*.cpp", "*.hpp"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line.strip()]


def is_comment_or_preprocessor(line: str) -> bool:
    stripped = line.lstrip()
    return (
        not stripped
        or stripped.startswith("#")
        or stripped.startswith("//")
        or stripped.startswith("/*")
        or stripped.startswith("*")
    )


def assignment_continuation(line: str) -> bool:
    stripped = line.rstrip()
    if not stripped:
        return False
    if stripped.endswith(("==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=")):
        return False
    return stripped.endswith("=")


def operator_continuation(line: str) -> bool:
    stripped = line.rstrip()
    return stripped.endswith((",", "(", "&&", "||", "+", "-", "*", "/"))


def in_signature_block(lines: list[str], index: int) -> bool:
    """Keep multi-line function declarations with unclosed '(' until ')'."""
    line = lines[index].rstrip()
    if "(" not in line:
        return False
    if line.count("(") <= line.count(")"):
        return False
    if not re.search(r"\b(void|int|float|double|bool|static|inline|class|struct|enum)\b", line):
        return False
    depth = 0
    for ch in line:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    j = index + 1
    while j < len(lines) and depth > 0:
        for ch in lines[j]:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        j += 1
    return j - index > 1


def should_merge(prev: str, nxt: str) -> bool:
    if is_comment_or_preprocessor(prev) or is_comment_or_preprocessor(nxt):
        return False
    prev_stripped = prev.rstrip()
    nxt_stripped = nxt.lstrip()
    if not prev_stripped or not nxt_stripped:
        return False
    if prev_stripped.endswith("{") or prev_stripped.endswith("};"):
        return False
    if nxt_stripped.startswith("{"):
        return False

    indent_prev = len(prev) - len(prev.lstrip(" "))
    indent_next = len(nxt) - len(nxt.lstrip(" "))
    if indent_next < indent_prev:
        return False

    merged = prev_stripped + " " + nxt_stripped
    if len(merged) > MAX_LINE:
        return False

    if assignment_continuation(prev_stripped):
        return True
    if operator_continuation(prev_stripped):
        return True
    if prev_stripped.endswith("return"):
        return True
    if "<<" in prev_stripped and not prev_stripped.endswith(";"):
        return True
    return False


def unwrap_text(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if in_signature_block(lines, i):
            start = i
            line = lines[i].rstrip()
            depth = line.count("(") - line.count(")")
            out.append(lines[i])
            i += 1
            while i < len(lines) and depth > 0:
                out.append(lines[i])
                depth += lines[i].count("(") - lines[i].count(")")
                i += 1
            continue

        if i + 1 < len(lines) and should_merge(lines[i], lines[i + 1]):
            merged = lines[i].rstrip() + " " + lines[i + 1].lstrip()
            j = i + 2
            while j < len(lines) and should_merge(merged, lines[j]):
                merged = merged.rstrip() + " " + lines[j].lstrip()
                j += 1
            out.append(merged)
            i = j
            continue

        out.append(lines[i])
        i += 1

    new_text = "\n".join(out)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text


def main() -> None:
    changed = 0
    for path in tracked_sources():
        original = path.read_text(encoding="utf-8", errors="ignore")
        updated = unwrap_text(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            changed += 1
    print(f"updated_files={changed}")


if __name__ == "__main__":
    main()
