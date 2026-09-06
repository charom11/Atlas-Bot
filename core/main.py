#!/usr/bin/env python3
"""
================================================================================
CORE MAIN COMPATIBILITY PROXY
================================================================================
This file acts as a seamless compatibility launcher forwarding to the canonical
root `main.py`. It guarantees 0 code drift across repository trees while
preserving backwards compatibility for any legacy callers or imports.
================================================================================
"""

import os
import sys

# Ensure project root directory is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import *
from main import main

if __name__ == '__main__':
    main()
