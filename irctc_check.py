"""
Primary checker: drives IRCTC's actual search page with Playwright.
Replicates the exact manual flow shown in the user's screenshot:
  From = MADGAON - MAO, To = THANE - TNA, Date = 16/06/2026,
  Class = Exec. Chair Car (EC), Quota = GENERAL.

Returns a CheckResult describing what was observed.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import (
    Browser,
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
    train_found: bool          # Does train 22230 appear in the results list?
    booking_open: bool         # Does it appear bookable (not greyed/ARP)?
    raw_signal: str            # Short string describing what was detected
    screenshot_path: str | None
    error: str | None = None


def _fill_station(page: Page, placeholder_text: str, value: str) -> None:
    """Type into IRCTC's autocomplete station field and pick the first result."""
    # IRCTC uses p-autoComplete; the visible input has a placeholder.
    # Robust selector: <input> inside element whose placeholder matches.
    inp = page.locator(f"input[placeholder*='{placeholder_text}']").first
    inp.click(timeout=ACTION_TIMEOUT * 1000)
    inp.fill("")
    inp.type(value, delay=40)
    # Wait for dropdown options, click first
    page.locator("ul.ui-autocomplete-items li").first.click(timeout=ACTION_TIMEOUT * 1000)


def _set_date(page: Page, ddmmyyyy: str) -> None:
    """Overwrite the journey date field."""
    date_inp = page.locator("input[formcontrolname='journeyDate']").first
    date_inp.click()
    date_inp.press("Control+A")
    date_inp.type(ddmmyyyy, delay=30)
    # Press Escape to close the date picker overlay
    page.keyboard.press("Escape")


def _select_dropdown(page: Page, formcontrolname: str, option_label: str) -> None:
    """Select an option from a p-dropdown by visible label."""
    dropdown = page.locator(f"p-dropdown[formcontrolname='{formcontrolname}']").first
    dropdown.click()
    page.locator("li[role='option']", has_text=option_label).first.click(
        timeout=ACTION_TIMEOUT * 1000
    )


def _shoot(page: Page, label: str) -> str:
    Path(SCREENSHOT_DIR).mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = f"{SCREENSHOT_DIR}/{ts}-{label}.png"
    try:
        page.screenshot(path=path, full_page=True)
    except Exception:
        return ""
    return path


def check_irctc() -> CheckResult:
    with sync_playwright() as pw:
        browser: Browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
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
        screenshot = None

        try:
            page.goto(IRCTC_URL, timeout=PAGE_LOAD_TIMEOUT * 1000, wait_until="networkidle")
        except PWTimeout:
            screenshot = _shoot(page, "load-timeout")
            return CheckResult(False, False, "irctc_load_timeout", screenshot,
                               error="IRCTC page did not finish loading")

        # Some days IRCTC shows a popup ("Disha" chatbot or service notice). Close if present.
        try:
            close_btns = page.locator("button:has-text('OK'), .close, [aria-label='Close']")
            if close_btns.count() > 0:
                close_btns.first.click(timeout=2000)
        except Exception:
            pass

        try:
            _fill_station(page, "From", SOURCE_NAME.split(" - ")[0])
            _fill_station(page, "To", DEST_NAME.split(" - ")[0])
            _set_date(page, JOURNEY_DATE_DDMMYYYY)
            _select_dropdown(page, "journeyClass", TRAVEL_CLASS_LABEL)
            _select_dropdown(page, "journeyQuota", QUOTA_LABEL)
        except Exception as e:
            screenshot = _shoot(page, "form-fill-failed")
            return CheckResult(False, False, "form_fill_failed", screenshot, error=str(e))

        screenshot_pre = _shoot(page, "before-search")

        # Click Search Trains
        try:
            page.locator("button:has-text('Search')").first.click()
        except Exception as e:
            return CheckResult(False, False, "search_click_failed",
                               screenshot_pre, error=str(e))

        # Wait for either results or an error banner. Results render as <app-train-avl-enq>
        # nodes; error banners are <p-toast> elements.
        try:
            page.wait_for_selector(
                "app-train-avl-enq, p-toast .ui-toast-detail, .alert",
                timeout=PAGE_LOAD_TIMEOUT * 1000,
            )
        except PWTimeout:
            screenshot = _shoot(page, "no-results-render")
            return CheckResult(False, False, "results_not_rendered",
                               screenshot, error="results did not render")

        # Give the list a moment to fully populate
        page.wait_for_timeout(2000)
        screenshot = _shoot(page, "results")

        # Capture the rendered text of the results region
        body_text = page.locator("body").inner_text()

        # Check for IRCTC's "No direct trains" or ARP error
        if re.search(r"no direct trains|train not available|ARP", body_text, re.I):
            return CheckResult(False, False, "no_direct_trains_or_arp", screenshot)

        train_found = bool(re.search(rf"\b{TRAIN_NUMBER}\b", body_text))

        # If train is listed, look for booking-state indicators near the train.
        # IRCTC shows class tiles with status: AVAILABLE-NNNN, RAC NNN, WL NNN,
        # REGRET/WL, NOT AVBL, TRAIN DEPARTED, BOOKING NOT STARTED.
        booking_open = False
        signal = "train_not_in_list"

        if train_found:
            # Slice the page text around the train number to inspect locally
            idx = body_text.find(TRAIN_NUMBER)
            window = body_text[max(0, idx - 200): idx + 1500]
            if re.search(r"AVAILABLE|RAC|WL\s*\d+|REGRET", window, re.I):
                booking_open = True
                signal = "available_or_waitlist"
            elif re.search(r"BOOKING\s+NOT\s+STARTED|ARP", window, re.I):
                booking_open = False
                signal = "booking_not_started"
            elif re.search(r"TRAIN\s+CANCELLED|TRAIN\s+DEPARTED|NOT\s+AVBL", window, re.I):
                booking_open = False
                signal = "train_cancelled_or_departed"
            else:
                # Train is listed but no class status text — treat as listed but unknown.
                # For a fresh ARP-opened day, IRCTC almost always shows AVAILABLE-XXXX,
                # so "listed without status" is unusual.
                booking_open = True
                signal = "train_listed_status_unclear"

        browser.close()
        return CheckResult(train_found, booking_open, signal, screenshot)
