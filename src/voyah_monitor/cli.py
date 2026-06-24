from __future__ import annotations

import argparse
import asyncio
import json
import sys

from voyah_monitor.bot import run_bot
from voyah_monitor.config import Settings, get_settings
from voyah_monitor.network_inspector import load_network_capture, suggest_allowed_paths
from voyah_monitor.session import session_exists
from voyah_monitor.storage import TelemetryStorage
from voyah_monitor.telemetry import format_status, dashboard_items_to_telemetry
from voyah_monitor.vehicle_status import format_dashboard_status
from voyah_monitor.session_manager import SessionExpiredError
from voyah_monitor.voyah_api import VoyahReadOnlyApi


def _session_error_message(exc: Exception) -> str:
    if isinstance(exc, SessionExpiredError):
        return str(exc)
    return f"{exc}\nIf refresh failed, run `voyah-monitor login` again."


def cmd_login(settings: Settings) -> int:
    try:
        from voyah_monitor.auth_login import run_interactive_login
    except ImportError as exc:
        print(
            "Playwright is required for login. Install locally:\n"
            "  pip install -e \".[login]\" && playwright install chromium\n"
            "Or run: scripts/local-login.sh (Linux/macOS) or scripts/local-login.bat (Windows)",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    asyncio.run(run_interactive_login(settings))
    return 0


def cmd_inspect(settings: Settings) -> int:
    capture = load_network_capture(settings.voyah_network_capture_path)
    if not capture:
        print("Network capture not found. Run `voyah-monitor login` first.", file=sys.stderr)
        return 1

    get_paths, post_paths = suggest_allowed_paths(capture)
    print(json.dumps(capture.to_dict(), ensure_ascii=False, indent=2))
    print()
    print("Suggested allow-list:")
    if get_paths:
        print("VOYAH_ALLOWED_GET_PATHS=" + ",".join(sorted(get_paths)))
    if post_paths:
        print("VOYAH_ALLOWED_POST_PATHS=" + ",".join(sorted(post_paths)))
    return 0


def cmd_fetch(settings: Settings) -> int:
    if not session_exists(settings.voyah_session_path):
        print("Session not found. Run `voyah-monitor login` first.", file=sys.stderr)
        return 1

    storage = TelemetryStorage(settings.voyah_db_path)
    try:
        with VoyahReadOnlyApi(settings) as api:
            items = api.fetch_dashboard_status()
    except SessionExpiredError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed to fetch dashboard status: {_session_error_message(exc)}", file=sys.stderr)
        return 1

    telemetry_items = dashboard_items_to_telemetry(items)
    saved = 0
    for telemetry in telemetry_items:
        storage.save_snapshot(telemetry)
        saved += 1
        print(format_status(telemetry))
        print("---")

    print(f"Saved snapshots: {saved}")
    return 0 if saved else 1


def cmd_status(settings: Settings) -> int:
    if not session_exists(settings.voyah_session_path):
        print("Session not found. Run `voyah-monitor login` first.", file=sys.stderr)
        return 1

    try:
        with VoyahReadOnlyApi(settings) as api:
            items = api.fetch_dashboard_status()
    except SessionExpiredError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed to fetch dashboard status: {_session_error_message(exc)}", file=sys.stderr)
        return 1

    print(format_dashboard_status(items))
    return 0


def cmd_compact_db(settings: Settings) -> int:
    storage = TelemetryStorage(settings.voyah_db_path)
    before_mb = storage.db_path.stat().st_size / 1024 / 1024
    updated, _ = storage.compact_stored_raw_json()
    after_mb = storage.db_path.stat().st_size / 1024 / 1024
    print(f"Compacted {updated} snapshots")
    print(f"Database: {before_mb:.1f} MB -> {after_mb:.1f} MB")
    return 0


def cmd_bot(settings: Settings) -> int:
    asyncio.run(run_bot(settings))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VOYAH Assist read-only telemetry monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="Interactive SMS login and session capture")
    subparsers.add_parser("inspect", help="Show captured network requests and suggested allow-list")
    subparsers.add_parser("fetch", help="Fetch telemetry using read-only allow-list")
    subparsers.add_parser("status", help="Show live vehicle fields from VOYAH dashboard (read-only)")
    subparsers.add_parser(
        "compact-db",
        help="Shrink stored raw_json blobs (drops unused API fields) and VACUUM",
    )
    subparsers.add_parser("bot", help="Run Telegram bot")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()

    commands = {
        "login": cmd_login,
        "inspect": cmd_inspect,
        "fetch": cmd_fetch,
        "status": cmd_status,
        "compact-db": cmd_compact_db,
        "bot": cmd_bot,
    }
    exit_code = commands[args.command](settings)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
