from __future__ import annotations

import argparse
import asyncio
import json
import sys

from voyah_monitor.auth_login import run_interactive_login
from voyah_monitor.bot import run_bot
from voyah_monitor.client import VoyahClient
from voyah_monitor.config import Settings, get_settings
from voyah_monitor.network_inspector import load_network_capture, suggest_allowed_paths
from voyah_monitor.session import session_exists
from voyah_monitor.storage import TelemetryStorage
from voyah_monitor.telemetry import format_status, normalize_payload
from voyah_monitor.vehicle_status import format_dashboard_status
from voyah_monitor.session_manager import SessionExpiredError
from voyah_monitor.voyah_api import VoyahReadOnlyApi


def _session_error_message(exc: Exception) -> str:
    if isinstance(exc, SessionExpiredError):
        return str(exc)
    return f"{exc}\nIf refresh failed, run `voyah-monitor login` again."


def cmd_login(settings: Settings) -> int:
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
        with VoyahClient(settings) as client:
            results = client.fetch_all_allowed()
    except SessionExpiredError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    saved = 0
    for item in results:
        if "error" in item:
            print(f"ERROR {item['method']} {item['path']}: {item['error']}", file=sys.stderr)
            continue
        telemetry_items = normalize_payload(item["data"])
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
        "bot": cmd_bot,
    }
    exit_code = commands[args.command](settings)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
