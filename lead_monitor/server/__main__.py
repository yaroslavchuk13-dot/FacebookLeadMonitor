"""Entry point: `python -m lead_monitor.server`."""

import sys

from lead_monitor.server.extension_api import main

sys.exit(main())
