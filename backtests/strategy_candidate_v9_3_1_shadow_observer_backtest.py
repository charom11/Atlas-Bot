#!/usr/bin/env python3
"""Compatibility entrypoint alias for run_v9_3_1_shadow_observer_backtest.py."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.run_v9_3_1_shadow_observer_backtest import (
    ReplayConfig,
    ReplayResult,
    replay_symbol,
    _dataset_path,
    load_assets,
    run,
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())
