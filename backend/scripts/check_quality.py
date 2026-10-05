"""Run Ruff/mypy and reject diagnostics beyond the reviewed legacy debt ledger.

The ledger matches the file, rule, message and affected source line. It never
ignores an entire module. --prune-baseline only removes resolved entries;
adding accepted debt requires an explicit reviewed ledger change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import TypedDict

BACKEND = Path(__file__).resolve().parents[1]
BASELINE = BACKEND / "quality-baseline.json"
MYPY_ERROR = re.compile(r"^(.+?):(\d+)(?::\d+)?: error: (.+?)  \[([^]]+)\]$")


class Diagnostic(TypedDict):
    tool: str
    file: str
    code: str
    message: str
    source_hash: str


def diagnostic(tool: str, filename: str, line: int, code: str, message: str) -> Diagnostic:
    path = Path(filename)
    if not path.is_absolute():
        path = BACKEND / path
    relative = path.resolve().relative_to(BACKEND).as_posix()
    lines = path.read_text(encoding="utf-8").splitlines()
    source = lines[line - 1] if line <= len(lines) else ""
    return {
        "tool": tool,
        "file": relative,
        "code": code,
        "message": message,
        "source_hash": hashlib.sha256(source.encode()).hexdigest(),
    }


def fingerprint(value: Diagnostic) -> str:
    return json.dumps(value, sort_keys=True)


def collect() -> list[Diagnostic]:
    results: list[Diagnostic] = []
    ruff = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format=json"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    if ruff.returncode not in (0, 1):
        raise RuntimeError(f"Ruff failed: {ruff.stderr.strip()}")
    for item in json.loads(ruff.stdout):
        results.append(
            diagnostic(
                "ruff",
                item["filename"],
                item["location"]["row"],
                item["code"],
                item["message"],
            )
        )

    mypy = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-error-summary"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    if mypy.returncode not in (0, 1):
        raise RuntimeError(f"Mypy failed: {mypy.stderr.strip()}")
    for line in mypy.stdout.splitlines():
        match = MYPY_ERROR.match(line)
        if match:
            filename, row, message, code = match.groups()
            results.append(diagnostic("mypy", filename, int(row), code, message))
        elif ": error:" in line:
            raise RuntimeError(f"Unrecognized mypy diagnostic: {line}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prune-baseline", action="store_true")
    args = parser.parse_args()
    baseline: list[Diagnostic] = json.loads(BASELINE.read_text())["diagnostics"]
    actual = collect()
    allowed = Counter(fingerprint(item) for item in baseline)
    present = Counter(fingerprint(item) for item in actual)
    introduced = present - allowed
    resolved = allowed - present
    if introduced:
        for key, count in sorted(introduced.items()):
            item = json.loads(key)
            print(f"NEW {item['tool']} {item['file']} [{item['code']}] {item['message']} ({count})")
        print(f"Failed: {sum(introduced.values())} diagnostics beyond the legacy baseline.")
        return 1
    if args.prune_baseline:
        remaining: list[Diagnostic] = []
        for item in baseline:
            key = fingerprint(item)
            if present[key]:
                remaining.append(item)
                present[key] -= 1
        ledger = json.loads(BASELINE.read_text())
        ledger["diagnostics"] = remaining
        BASELINE.write_text(json.dumps(ledger, indent=2) + "\n")
    counts = Counter(item["tool"] for item in actual)
    print(
        f"Quality ratchet passed: {dict(counts)} pre-existing diagnostics remain; "
        f"{sum(resolved.values())} resolved ledger entries."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
