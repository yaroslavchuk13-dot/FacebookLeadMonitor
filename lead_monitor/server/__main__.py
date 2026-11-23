"""Kept for compatibility: `python -m lead_monitor.server` starts the whole program."""

import sys

from lead_monitor.app import main

sys.exit(main())
