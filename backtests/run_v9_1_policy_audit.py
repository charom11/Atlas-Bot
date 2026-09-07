"""Small offline V9.1 policy audit helper.

This intentionally does not claim portfolio performance. It verifies that an
existing V9 event stream obeys V9.1 admission rules before a full institutional
backtest is run locally.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from strategy_candidate_v9_1 import audit_summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="backtests/v9_1_policy.json")
    args = parser.parse_args()
    report = audit_summary()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
