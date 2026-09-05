#!/usr/bin/env python3
"""
================================================================================
WEATHER-ENSEMBLE BOT CORE BACKWARD COMPATIBILITY PROXY
================================================================================
This file acts as a seamless alias/wrapper for `core/main.py`.
================================================================================
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.main import *
from core.main import main

if __name__ == '__main__':
    main()
