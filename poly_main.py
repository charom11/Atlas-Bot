#!/usr/bin/env python3
"""
================================================================================
POLYMARKET MASTER RUNNER (poly_main.py)
================================================================================
Entry point for Polymarket Prediction Bot from root directory.
Delegates directly to polymarket/poly_main.py.

Usage:
  python poly_main.py             (Interactive Menu)
  python poly_main.py --paper     (24/7 Autopilot Paper Trading)
  python poly_main.py --live      (24/7 Live Trading via CLOB)
  python poly_main.py --scan      (Scan All Live Markets)
  python poly_main.py --audit     (Wallet & API Health Check)
================================================================================
"""
import os
import sys

# Route to polymarket module
poly_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "polymarket")
if poly_dir not in sys.path:
    sys.path.insert(0, poly_dir)

from poly_main import main

if __name__ == '__main__':
    main()
