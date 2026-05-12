"""
Primary checker: drives IRCTC's actual search page with Playwright.

Hardening principles:
1. Take a screenshot at every milestone. The `last_screenshot` variable is the
   "latest visible state" — returned even on partial failure.
2. Multiple selector strategies per field. Try formcontrolname first (most
   stable), then placeholder, then visible label.
3. Aggressively dismiss any modal/popup before form fill.
4. Never let an exception escape this module — return a CheckResult instead.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import (
    Browser,
    Locator,
    Page,
    TimeoutError as PWTimeout,
    sync_playwright,
)

from config import (
    ACTION_TIMEOUT,
    DEST_NAME,
    JOURNEY_DATE_DDMMYYYY,
    PAGE_LOAD_TIMEOUT,
    QUOTA_LABEL,
    SCREENSHOT_DIR,
    SOURCE_NAME,
    TRAIN_NUMBER,
    TRAVEL_CLASS_LABEL,
)

IRCTC_URL = "https://www.irctc.co.in/nget/train-search"


@dataclass
class CheckResult:
    train_found: bool
    booking_open: bool
    raw_signal: str
    screenshot_path: str | None
    error: str | None = None
    threw: bool = False  # True only if exception escaped to module boundary


# --- Helpers --------------------------------------------------------------
def _shoot(page: Page, label: str) -> str | None:
    """Take a full-page screenshot. Returns path or None on failure."""
    try:
        Path(SCREENSHOT_DIR).mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = f"{SCREENSHOT_DIR}/{ts}-{label}.png"
        page.screenshot(path=path, full_page=True, timeout=15000)
        return path
    except Exception as e:
        print(f"  [warn] screenshot {label!r} failed: {e}")
        return None


def _dismiss_popups(page: Page) -> None:
    """IRCTC shows various popups (Disha bot, service notices). Try to close all."""
    selectors = [
        "button.btn-modal-close",
        "button:has-text('OK')",
        "button:has-text('Ok')",
        ".close",
        "[aria-label='Close']",
        "i.fa-times",
        "p-dialog button.ui-dialog-titlebar-close",
        "div.disha-banner i",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = loc.count()
            for i in range(min(count, 3)):
                try:
                    loc.nth(i).click(timeout=1500)
                    page.wait_for_timeout(300)
                except Exception:
                    pass
        except Exception:
            pass
    # Also press Escape a couple of times in case a dialog is focused
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
    except Exception:
        pass


def _find_station_input(page: Page, which: str) -> Locator:
    """Locate the From or To autocomplete input. which is 'origin' or 'destination'."""
    candidates = [
        f"p-autocomplete[formcontrolname='{which}'] input",
        f"[formcontrolname='{which}'] input",
        f"input[placeholder='{'From' if which == 'origin' else 'To'}*']",
        f"input[placeholder*='{'From' if which == 'origin' else 'To'}']",
    ]
    last_err = None
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                # Verify it's actually visible
                loc.wait_for(state="visible", timeout=3000)
                return loc
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Could not find {which} input. Last error: {last_err}")


def _fill_station(page: Page, which: str, station_text: str) -> None:
    inp = _find_station_input(page, which)
    inp.click(timeout=ACTION_TIMEOUT * 1000)
    inp.fill("")
    inp.type(station_text, delay=60)
    # Wait for autocomplete dropdown
    dropdown_selectors = [
        "ul.ui-autocomplete-items li",
        ".ui-autocomplete-items li",
        "[role='listbox'] [role='option']",
        ".ng-tns-c75 li",  # PrimeNG class pattern, may vary
    ]
    for sel in dropdown_selectors:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=4000)
            page.locator(sel).first.click(timeout=3000)
            return
        except Exception:
            continue
    # Fallback: just press Enter, IRCTC sometimes accepts that
    inp.press("Enter")


def _set_date(page: Page, ddmmyyyy: str) -> None:
    candidates = [
        "p-calendar[formcontrolname='journeyDate'] input",
        "input[formcontrolname='journeyDate']",
        "input[placeholder='DD/MM/YYYY*']",
        "input[placeholder*='DD/MM']",
    ]
    inp = None
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                inp = loc
                break
        except Exception:
            continue
    if inp is None:
        raise RuntimeError("Could not find date input")
    inp.click(timeout=ACTION_TIMEOUT * 1000)
    inp.press("Control+A")
    inp.press("Delete")
    inp.type(ddmmyyyy, delay=40)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)


def _select_dropdown(page: Page, formcontrolname: str, option_label: str) -> None:
    dropdown_candidates = [
        f"p-dropdown[formcontrolname='{formcontrolname}']",
        f"[formcontrolname='{formcontrolname}']",
    ]
    dropdown = None
    for sel in dropdown_candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                dropdown = loc
                break
        except Exception:
            continue
    if dropdown is None:
        raise RuntimeError(f"Could not find dropdown {formcontrolname}")
    dropdown.click(timeout=ACTION_TIMEOUT * 1000)
    page.wait_for_timeout(500)
    option_candidates = [
        f"li[role='option']:has-text('{option_label}')",
        f"[role='option']:has-text('{option_label}')",
        f"li:has-text('{option_label}')",
        f"span:has-text('{option_label}')",
    ]
    for sel in option_candidates:
        try:
            page.locator(sel).first.click(timeout=3000)
            return
        except Exception:
            continue
    raise RuntimeError(f"Could not find option '{option_label}' in {formcontrolname}")


# --- Main entry -----------------------------------------------------------
def check_irctc() -> CheckResult:
    """Returns a CheckResult. Never raises."""
    last_screenshot: str | None = None
    err_msg: str | None = None
    signal = "started"
    train_found = False
    booking_open = False

    try:
        with sync_playwright() as pw:
            browser: Browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    # IRCTC sends broken HTTP/2 frames; force HTTP/1.1
                    "--disable-http2",
                    "--disable-features=UseHttp2,SpdyForOverHttp2,EnableQuic",
                ],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 900},
                locale="en-IN",
            )
            page = ctx.new_page()
            page.set_default_timeout(ACTION_TIMEOUT * 1000)

            # Block analytics/ads — they often stall the load event on IRCTC
            def _blocker(route):
                url = route.request.url.lower()
                blocked = ["google-analytics", "googletagmanager", "doubleclick",
                           "facebook.net", "hotjar", "clarity.ms", "googleadservices"]
                if any(b in url for b in blocked):
                    return route.abort()
                return route.continue_()
            try:
                page.route("**/*", _blocker)
            except Exception:
                pass

            # Step 1: Load page. IRCTC is often very slow for non-IN IPs.
            # We try progressively looser wait conditions; on each attempt's
            # timeout we still try to proceed since the DOM may be usable.
            load_err: str | None = None
            for attempt, wait_until in enumerate(["domcontentloaded", "commit"]):
                try:
                    page.goto(IRCTC_URL,
                              timeout=PAGE_LOAD_TIMEOUT * 1000,
                              wait_until=wait_until)
                    load_err = None
                    break
                except Exception as e:
                    load_err = str(e)[:300]
                    print(f"  [warn] goto attempt {attempt + 1} "
                          f"({wait_until}) failed: {load_err[:150]}")

            # Whether goto succeeded or timed out, give the page time to render
            # and check if the form is actually usable. Many timeouts are
            # caused by tracking scripts / ads stalling, not the form itself.
            page.wait_for_timeout(5000)
            last_screenshot = _shoot(page, "01-after-load")

            # Real success criterion: is there an input we can type into?
            form_usable = False
            try:
                page.wait_for_selector("input", state="visible", timeout=15000)
                form_usable = True
                signal = "page_usable"
            except Exception:
                pass

            if not form_usable:
                err_for_return = load_err or "page never rendered an input"
                browser.close()
                return CheckResult(False, False, "irctc_load_failed",
                                   last_screenshot, error=err_for_return)

            if load_err:
                # Form is usable despite goto timeout — log but continue
                print(f"  [info] proceeding despite goto timeout: "
                      f"{load_err[:100]}")
            last_screenshot = _shoot(page, "01-loaded")
            signal = "page_loaded"

            # Step 2: Dismiss any popups
            _dismiss_popups(page)
            page.wait_for_timeout(500)
            last_screenshot = _shoot(page, "02-popups-dismissed") or last_screenshot

            # Step 3: Fill From
            try:
                _fill_station(page, "origin", SOURCE_NAME.split(" - ")[0])
                last_screenshot = _shoot(page, "03-from-filled") or last_screenshot
                signal = "from_filled"
            except Exception as e:
                err_msg = f"from_fill_failed: {e}"
                last_screenshot = _shoot(page, "03-from-fail") or last_screenshot
                browser.close()
                return CheckResult(False, False, "form_fill_failed",
                                   last_screenshot, error=err_msg)

            # Step 4: Fill To
            try:
                _fill_station(page, "destination", DEST_NAME.split(" - ")[0])
                last_screenshot = _shoot(page, "04-to-filled") or last_screenshot
                signal = "to_filled"
            except Exception as e:
                err_msg = f"to_fill_failed: {e}"
                last_screenshot = _shoot(page, "04-to-fail") or last_screenshot
                browser.close()
                return CheckResult(False, False, "form_fill_failed",
                                   last_screenshot, error=err_msg)

            # Step 5: Set date
            try:
                _set_date(page, JOURNEY_DATE_DDMMYYYY)
                last_screenshot = _shoot(page, "05-date-set") or last_screenshot
                signal = "date_set"
            except Exception as e:
                err_msg = f"date_set_failed: {e}"
                last_screenshot = _shoot(page, "05-date-fail") or last_screenshot
                browser.close()
                return CheckResult(False, False, "form_fill_failed",
                                   last_screenshot, error=err_msg)

            # Step 6: Class (optional - if it fails, continue with default)
            try:
                _select_dropdown(page, "journeyClass", TRAVEL_CLASS_LABEL)
                signal = "class_selected"
            except Exception as e:
                print(f"  [warn] class select failed (continuing): {e}")

            # Step 7: Quota (optional - default is GENERAL anyway)
            try:
                _select_dropdown(page, "journeyQuota", QUOTA_LABEL)
                signal = "quota_selected"
            except Exception as e:
                print(f"  [warn] quota select failed (continuing): {e}")

            last_screenshot = _shoot(page, "06-form-complete") or last_screenshot

            # Step 8: Click Search
            try:
                search_candidates = [
                    "button.search_btn",
                    "button:has-text('Search')",
                    "button.train_Search",
                ]
                clicked = False
                for sel in search_candidates:
                    try:
                        page.locator(sel).first.click(timeout=4000)
                        clicked = True
                        break
                    except Exception:
                        continue
                if not clicked:
                    raise RuntimeError("could not click Search button")
            except Exception as e:
                err_msg = f"search_click_failed: {e}"
                last_screenshot = _shoot(page, "07-search-click-fail") or last_screenshot
                browser.close()
                return CheckResult(False, False, "search_click_failed",
                                   last_screenshot, error=err_msg)

            # Step 9: Wait for results to render
            try:
                page.wait_for_selector(
                    "app-train-avl-enq, p-toast .ui-toast-detail, "
                    ".alert, .train_list, .err-toast-message",
                    timeout=PAGE_LOAD_TIMEOUT * 1000,
                )
                page.wait_for_timeout(2500)
            except PWTimeout:
                last_screenshot = _shoot(page, "08-no-results") or last_screenshot
                browser.close()
                return CheckResult(False, False, "results_not_rendered",
                                   last_screenshot,
                                   error="results did not render in time")

            last_screenshot = _shoot(page, "09-results") or last_screenshot

            # Step 10: Parse results
            body_text = page.locator("body").inner_text()
            train_found = bool(re.search(rf"\b{TRAIN_NUMBER}\b", body_text))

            # Look for IRCTC error toasts
            err_toast = re.search(
                r"(no direct trains|train not available|booking not.{0,30}allowed|"
                r"ARP|advance reservation period)",
                body_text, re.I,
            )

            if err_toast and not train_found:
                signal = f"irctc_toast: {err_toast.group(0)[:80]}"
            elif train_found:
                idx = body_text.find(TRAIN_NUMBER)
                window = body_text[max(0, idx - 200): idx + 1500]
                if re.search(r"AVAILABLE|RAC|WL\s*\d+|REGRET", window, re.I):
                    booking_open = True
                    signal = "available_or_waitlist"
                elif re.search(r"BOOKING\s+NOT\s+STARTED", window, re.I):
                    signal = "booking_not_started"
                elif re.search(r"TRAIN\s+CANCELLED|TRAIN\s+DEPARTED|NOT\s+AVBL",
                               window, re.I):
                    signal = "train_cancelled_or_departed"
                else:
                    booking_open = True
                    signal = "train_listed_status_unclear"
            else:
                signal = "train_not_in_results"

            browser.close()
            return CheckResult(train_found, booking_open, signal,
                               last_screenshot, error=err_msg)

    except Exception as e:
        # Catastrophic failure (e.g., Playwright not installed, browser crashed)
        return CheckResult(False, False, "playwright_crashed",
                           last_screenshot, error=str(e), threw=True)
