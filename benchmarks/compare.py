# Copyright (C) 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Compare two benchmark result files and print a Markdown table.

Usage::

    python benchmarks/compare.py results/baseline.json results/current.json [--md out.md]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _fmt(value: float, unit: str) -> str:
    if unit == "s":
        return f"{value * 1000:.0f} ms" if value < 1 else f"{value:.2f} s"
    if unit in {"MB"}:
        return f"{value:.0f} MB"
    return f"{value:,.0f}" if value >= 10 else f"{value:.2f}"


def compare(baseline: dict, current: dict) -> str:
    """Return a Markdown comparison table of median values."""
    rows = [
        f"Baseline: `{baseline['meta']['git']}` | Current: `{current['meta']['git']}`",
        "",
        "| Metric | Baseline (median) | Current (median) | Change | Speed-up |",
        "|---|---:|---:|---:|---:|",
    ]
    names = sorted(set(baseline["metrics"]) | set(current["metrics"]))
    for name in names:
        b = baseline["metrics"].get(name)
        c = current["metrics"].get(name)
        if not b or not c:
            continue
        unit = c["unit"]
        # Failure counters are summed rather than averaged.
        if name.startswith("stability."):
            bv, cv = sum(b["values"]), sum(c["values"])
        else:
            bv, cv = b["median"], c["median"]
        change = ((cv - bv) / bv * 100) if bv else 0.0
        speedup = f"{bv / cv:.1f}x" if unit == "s" and cv > 0 else ""
        rows.append(
            f"| {name} | {_fmt(bv, unit)} | {_fmt(cv, unit)} | {change:+.0f}% | {speedup} |"
        )
    return "\n".join(rows)


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--md", type=Path, default=None, help="Write the table to a file")
    args = parser.parse_args()
    table = compare(
        json.loads(args.baseline.read_text(encoding="utf-8")),
        json.loads(args.current.read_text(encoding="utf-8")),
    )
    print(table)
    if args.md:
        args.md.write_text(table + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
