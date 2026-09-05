#!/usr/bin/env python3
"""
================================================================================
WEATHER-ENSEMBLE BOT BACKWARD COMPATIBILITY PROXY
================================================================================
This file acts as a seamless alias/wrapper for `main.py`.
It allows legacy imports and command invocations to work transparently.
================================================================================
"""

import sys
import os

# Ensure the directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import *
from main import main

if __name__ == '__main__':
    main()
