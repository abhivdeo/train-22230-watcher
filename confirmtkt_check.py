"""
Fallback checker: scrapes ConfirmTkt's public results page.
Used only if the IRCTC Playwright path fails. Simpler, faster, but a
secondary signal — IRCTC is the source of truth.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from config import (
    DEST_CODE,
    JOURNEY_DATE_ISO,
    SOURCE_CODE,
    TRAIN_NUMBER,
    TRAVEL_CLASS_CODE,
)


@dataclass
class FallbackResult:
    train_found: bool
    booking_open: bool
    raw_signal: str
    error: str | None = None


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def check_confirmtkt() -> FallbackResult:
    # ConfirmTkt's user-facing results URL. Date format is dd-mm-yyyy.
    yyyy, mm, dd = JOURNEY_DATE_ISO.split("-")
    date_dmy = f"{dd}-{mm}-{yyyy}"
    url = (
        "https://www.confirmtkt.com/rbooking-train-search"
        f"?source={SOURCE_CODE}&destination={DEST_CODE}"
        f"&onward_date={date_dmy}&class={TRAVEL_CLASS_CODE}&quota=GN"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
    except requests.RequestException as e:
        return FallbackResult(False, False, "network_error", error=str(e))

    if r.status_code != 200:
        return FallbackResult(False, False, f"http_{r.status_code}",
                              error=f"non-200 from confirmtkt")

    html = r.text
    train_found = bool(re.search(rf"\b{TRAIN_NUMBER}\b", html))
    if not train_found:
        return FallbackResult(False, False, "train_not_in_response")

    # Booking-state hints in ConfirmTkt's HTML
    near = html
    idx = html.find(TRAIN_NUMBER)
    if idx != -1:
        near = html[max(0, idx - 500): idx + 3000]

    if re.search(r"ARP|advance reservation|not\s+open|booking\s+not", near, re.I):
        return FallbackResult(True, False, "arp_or_not_open")
    if re.search(r"AVAILABLE|AVL|RAC|WL\s*\d+", near, re.I):
        return FallbackResult(True, True, "available_or_waitlist")

    # Train is mentioned but status unclear (could be schedule info, not booking)
    return FallbackResult(True, False, "train_listed_status_unclear")
