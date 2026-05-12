"""
Main entry point. Subcommands:

  python check_train.py daily         # one search + always email screenshot
  python check_train.py test-email    # send a test email, exit
  python check_train.py once          # run once, print result, do NOT email
  python check_train.py reset         # clear state file
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone, timedelta

import state
from config import (
    DEST_NAME,
    JOURNEY_DATE_DDMMYYYY,
    QUOTA_LABEL,
    SOURCE_NAME,
    TRAIN_NUMBER,
    TRAVEL_CLASS_LABEL,
)

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now_str() -> str:
    return datetime.now(IST).strftime("%a, %d %b %Y, %I:%M %p IST")


def _subject(train_found: bool, booking_open: bool, error: bool) -> str:
    today = datetime.now(IST).strftime("%d-%b-%Y")
    if error:
        return f"[Watcher ERROR] Train {TRAIN_NUMBER} check failed - {today}"
    if booking_open:
        return f"[BOOK NOW] Train {TRAIN_NUMBER} bookings OPEN for {JOURNEY_DATE_DDMMYYYY}"
    if train_found:
        return f"[Daily] Train {TRAIN_NUMBER} listed but not yet bookable - {today}"
    return f"[Daily] Train {TRAIN_NUMBER} not in results yet - {today}"


def _body(method: str, signal: str, train_found: bool, booking_open: bool,
          screenshot: str | None, error: str | None) -> str:
    if error and not train_found:
        status_line = f"ERROR during check: {error}"
    elif booking_open:
        status_line = "BOOKING IS OPEN. Go book on IRCTC now."
    elif train_found:
        status_line = "Train is in IRCTC results but booking not yet open."
    else:
        status_line = "Train is not yet showing in IRCTC results for the date."

    return (
        f"Daily check for train {TRAIN_NUMBER} "
        f"({SOURCE_NAME} -> {DEST_NAME})\n"
        f"Target journey date: {JOURNEY_DATE_DDMMYYYY}\n"
        f"Class: {TRAVEL_CLASS_LABEL}    Quota: {QUOTA_LABEL}\n"
        f"Run time: {_ist_now_str()}\n\n"
        f"Status: {status_line}\n\n"
        f"Detection method: {method}\n"
        f"Raw signal: {signal}\n\n"
        f"Book: https://www.irctc.co.in/nget/train-search\n"
        f"(Screenshot of IRCTC search results is attached.)\n"
    )


def cmd_test_email() -> int:
    import notifier
    notifier.send(
        subject="[TEST] Train watcher email setup OK",
        body=("If you got this, GMAIL_USER / GMAIL_APP_PASSWORD / ALERT_EMAIL "
              "are wired correctly. Daily emails will arrive ~5 PM IST."),
    )
    print("Test email sent.")
    return 0


def cmd_reset() -> int:
    from pathlib import Path
    p = Path(".state.json")
    if p.exists():
        p.unlink()
        print(f"Removed {p}")
    else:
        print("No state file to remove.")
    return 0


def _run_check() -> tuple[str, str, bool, bool, str | None, str | None]:
    """Returns (method, signal, train_found, booking_open, screenshot, error)."""
    # Try IRCTC (primary)
    try:
        from irctc_check import check_irctc
        r = check_irctc()
        # We use the IRCTC result if we got a screenshot OR a real signal,
        # even if train wasn't found (so the daily email still shows IRCTC's view).
        if r.screenshot_path or r.raw_signal not in ("irctc_load_timeout",
                                                     "form_fill_failed",
                                                     "results_not_rendered"):
            return ("irctc_playwright", r.raw_signal,
                    r.train_found, r.booking_open, r.screenshot_path, r.error)
        print(f"IRCTC primary failed cleanly: {r.error} ({r.raw_signal})")
    except Exception as e:
        print(f"IRCTC primary threw: {e}")
        traceback.print_exc()

    # Fallback (no screenshot)
    try:
        from confirmtkt_check import check_confirmtkt
        r2 = check_confirmtkt()
        return ("confirmtkt_fallback", r2.raw_signal,
                r2.train_found, r2.booking_open, None, r2.error)
    except Exception as e:
        print(f"Fallback also failed: {e}")
        return "all_failed", "error", False, False, None, str(e)


def cmd_daily(dry_run: bool = False) -> int:
    """One search, then always email with the screenshot."""
    s = state.load()

    method, signal, train_found, booking_open, screenshot, err = _run_check()
    status_str = ("OPEN" if booking_open
                  else "LISTED_NOT_OPEN" if train_found
                  else "ERROR" if err
                  else "NOT_LISTED")
    state.record_check(s, status_str, method, err)
    print(f"Method={method}  signal={signal}  found={train_found}  "
          f"open={booking_open}  err={err}")

    if dry_run:
        state.save(s)
        return 0

    try:
        import notifier
        notifier.send(
            subject=_subject(train_found, booking_open,
                             bool(err) and not train_found),
            body=_body(method, signal, train_found, booking_open, screenshot, err),
            attach_image=screenshot,
        )
        if booking_open:
            state.mark_alerted(s)
        print("Email sent.")
    except Exception as e:
        print(f"Email send failed: {e}", file=sys.stderr)
        s["last_error"] = f"email_failed: {e}"
        state.save(s)
        return 1

    state.save(s)
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if cmd in ("daily", "run"):
        return cmd_daily()
    if cmd == "once":
        return cmd_daily(dry_run=True)
    if cmd == "test-email":
        return cmd_test_email()
    if cmd == "reset":
        return cmd_reset()
    print(f"Unknown command: {cmd}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
