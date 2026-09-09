#!/usr/bin/env python3
"""1-Click Sync from Laptop to GitHub (scripts/ copy)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sync_to_github import main

if __name__ == "__main__":
    main()
