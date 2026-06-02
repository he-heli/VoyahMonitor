#!/usr/bin/env python3
"""Interactive VOYAH SMS login — run on a machine with a desktop browser.

Outputs:
  data/session.json
  data/network_capture.json

Use scripts/local-login.sh (macOS/Linux) or scripts/local-login.bat (Windows).
"""

from __future__ import annotations

import asyncio
import sys


def main() -> int:
    try:
        from voyah_monitor.auth_login import run_interactive_login
        from voyah_monitor.config import get_settings
    except ImportError:
        print(
            "Install login dependencies first:\n"
            "  pip install -e \".[login]\" && playwright install chromium\n"
            "Or run scripts/local-login.sh / local-login.bat",
            file=sys.stderr,
        )
        return 1

    settings = get_settings()
    asyncio.run(run_interactive_login(settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
