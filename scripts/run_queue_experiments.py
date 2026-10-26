#!/usr/bin/env python3
"""D5: run the five bottleneck queue scenarios and write their text logs.

The compiled ./queue_compare binary appends one CSV row per run to
results/d5_metrics.csv. This runner starts from a fresh D5 CSV, leaves all
D1-D4 outputs untouched, and stores one text log per scenario.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "queue_compare"
RESULTS = ROOT / "results"
CSV = RESULTS / "d5_metrics.csv"
SCENARIOS = ["default", "fqcodel100", "fifo100", "devq100", "devq10"]

BUILD_CMD = (
    "g++ -std=c++17 -O0 -g0 src/queue_compare.cc -o queue_compare "
    "$(pkg-config --cflags --libs ns3-core ns3-network ns3-internet "
    "ns3-point-to-point ns3-applications ns3-flow-monitor ns3-traffic-control)"
)


def main() -> int:
    if not BIN.exists():
        print("[build] queue_compare binary missing, compiling...")
        subprocess.run(BUILD_CMD, shell=True, cwd=ROOT, check=True)
    if CSV.exists():
        CSV.unlink()
    for scenario in SCENARIOS:
        result = subprocess.run(
            [str(BIN), f"--scenario={scenario}", f"--csvfile={CSV}"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        log_path = RESULTS / f"d5_{scenario}.txt"
        log_path.write_text(result.stdout)
        print(f"[run] {scenario}: wrote {log_path}")
    print(f"wrote {CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
