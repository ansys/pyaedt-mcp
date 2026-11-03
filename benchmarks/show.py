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

"""Print every metric in a benchmark result file.

Usage::

    python benchmarks/show.py results/current.json [--filter connect.]
"""

import argparse
import json
from pathlib import Path


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("result", type=Path)
    parser.add_argument("--filter", default="", help="Only show metrics starting with this")
    args = parser.parse_args()
    data = json.loads(args.result.read_text(encoding="utf-8"))
    print(f"{data['meta']['label']} @ {data['meta']['git']} ({data['meta']['timestamp']})")
    for name, m in data["metrics"].items():
        if name.startswith(args.filter):
            print(
                f"{name:60s} n={m['n']:<3d} median={m['median']:.3f} "
                f"max={m['max']:.3f} sum={sum(m['values']):.2f} {m['unit']}"
            )
    for note in data.get("notes", []):
        print("note:", note)


if __name__ == "__main__":
    main()
