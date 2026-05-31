from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from playwright.async_api import Page, Request, Response, async_playwright

from voyah_monitor.config import Settings
from voyah_monitor.network_inspector import (
    CapturedRequest,
    NetworkCapture,
    classify_request,
    preview_response_body,
    save_network_capture,
    suggest_allowed_paths,
)
from voyah_monitor.session import save_session


async def _wait_for_login_success(page: Page, base_url: str, timeout_sec: int = 300) -> bool:
    """Wait until URL changes away from login page or dashboard elements appear."""
    login_markers = ("login", "auth", "signin", "sign-in")
    deadline = asyncio.get_event_loop().time() + timeout_sec

    while asyncio.get_event_loop().time() < deadline:
        current_url = page.url.lower()
        if not any(marker in current_url for marker in login_markers):
            return True

        # Common post-login UI hints
        for selector in (
            "nav",
            "[data-testid='dashboard']",
            ".dashboard",
            "main",
        ):
            try:
                if await page.locator(selector).count() > 0:
                    return True
            except Exception:
                pass

        await asyncio.sleep(1)

    return False


async def run_interactive_login(settings: Settings) -> None:
    capture = NetworkCapture(
        base_url=settings.voyah_base_url,
        captured_at=datetime.now(UTC).isoformat(),
    )
    pending: dict[str, CapturedRequest] = {}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        def on_request(request: Request) -> None:
            if request.resource_type not in {"xhr", "fetch", "document"}:
                return
            from urllib.parse import urlparse

            path = urlparse(request.url).path or "/"

            pending[request.url] = CapturedRequest(
                timestamp=datetime.now(UTC).isoformat(),
                method=request.method,
                url=request.url,
                path=path,
                status=None,
                resource_type=request.resource_type,
                request_content_type=request.headers.get("content-type"),
                response_content_type=None,
                classification=classify_request(request.method, request.url, settings.voyah_base_url),
            )

        async def on_response(response: Response) -> None:
            request = response.request
            item = pending.get(request.url)
            if not item:
                return
            item.status = response.status
            item.response_content_type = response.headers.get("content-type")
            if response.headers.get("content-type", "").startswith("application/json"):
                try:
                    body = await response.text()
                    item.response_preview = preview_response_body(body)
                except Exception:
                    item.response_preview = None
            capture.requests.append(item)
            pending.pop(request.url, None)

        page.on("request", on_request)
        page.on("response", lambda response: asyncio.create_task(on_response(response)))

        print(f"Opening {settings.voyah_base_url} ...")
        await page.goto(settings.voyah_base_url, wait_until="domcontentloaded")

        print()
        print("=== VOYAH login ===")
        print("1. Enter your phone number on the page.")
        print("2. Accept personal data consent if required.")
        print("3. Complete SmartCaptcha manually if it appears.")
        print("4. Click 'Get SMS code' and wait for the SMS.")
        print()

        phone = settings.voyah_phone.strip()
        if phone and phone != "+7":
            try:
                phone_input = page.locator(
                    "input[type='tel'], input[name*='phone' i], input[placeholder*='телефон' i]"
                ).first
                if await phone_input.count() > 0:
                    await phone_input.fill(phone)
                    print(f"Phone prefilled from VOYAH_PHONE: {phone}")
            except Exception:
                print("Could not auto-fill phone; please enter it manually.")

        sms_code = input("Enter SMS code when received (or press Enter after manual login): ").strip()
        if sms_code:
            try:
                code_input = page.locator(
                    "input[type='tel'], input[name*='code' i], input[placeholder*='код' i], input[inputmode='numeric']"
                ).last
                if await code_input.count() > 0:
                    await code_input.fill(sms_code)
                    print("SMS code entered.")
            except Exception:
                print("Could not auto-fill SMS code; please enter it manually on the page.")

            for selector in (
                "button:has-text('Войти')",
                "button:has-text('Подтвердить')",
                "button:has-text('Продолжить')",
                "button[type='submit']",
            ):
                try:
                    button = page.locator(selector).first
                    if await button.count() > 0 and await button.is_enabled():
                        await button.click()
                        break
                except Exception:
                    continue

        print("Waiting for successful login...")
        logged_in = await _wait_for_login_success(page, settings.voyah_base_url)
        if not logged_in:
            print("Login was not detected within timeout. Session may be incomplete.", file=sys.stderr)

        print("Navigating dashboard pages to capture telemetry API calls...")
        await asyncio.sleep(3)

        # Try clicking common navigation items without submitting forms.
        for selector in (
            "a[href*='vehicle']",
            "a[href*='fleet']",
            "a[href*='car']",
            "a[href*='monitor']",
            "a[href*='map']",
            "button:has-text('Автомоб')",
            "button:has-text('Транспорт')",
        ):
            try:
                link = page.locator(selector).first
                if await link.count() > 0 and await link.is_visible():
                    await link.click(timeout=3000)
                    await asyncio.sleep(2)
            except Exception:
                continue

        await save_session(context, settings.voyah_session_path)
        save_network_capture(settings.voyah_network_capture_path, capture)

        get_paths, post_paths = suggest_allowed_paths(capture)
        print()
        print("=== Login complete ===")
        print(f"Session saved to: {settings.voyah_session_path}")
        print(f"Network capture saved to: {settings.voyah_network_capture_path}")
        print(f"Captured API-like requests: {len(capture.requests)}")
        if get_paths:
            print("Suggested VOYAH_ALLOWED_GET_PATHS:")
            print(",".join(sorted(get_paths)))
        if post_paths:
            print("Suggested VOYAH_ALLOWED_POST_PATHS:")
            print(",".join(sorted(post_paths)))
        if not get_paths and not post_paths:
            print("No API candidates detected yet. Open more pages manually, then re-run login.")

        print()
        print("Press Enter to close the browser...")
        await asyncio.to_thread(input)

        await browser.close()
