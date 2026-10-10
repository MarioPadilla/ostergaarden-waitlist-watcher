"""Check whether the Østergården external waiting list is open; notify via ntfy on change."""
from __future__ import annotations

import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

URL = "https://findbolig.nu/da-dk/udlejere/oestergaarden/ekstern-venteliste"
PAGE_MARKER = "ekstern venteliste"  # must be present, otherwise the page did not render
CLOSED_MARKER = "lukket for opskrivning"

BURST_COUNT = 3        # messages sent in a row when the list first opens
BURST_GAP_SECONDS = 5  # pause between them so the phone sounds each one
MAX_REMINDERS = 5      # extra alerts on later runs while the list stays open

# STATE_DIR lets tests run against a throwaway directory
BASE = Path(os.environ.get("STATE_DIR", Path(__file__).parent))
STATE_FILE = BASE / "state.txt"
HISTORY_FILE = BASE / "history.csv"
DEBUG_DIR = BASE / "debug"


def fetch_page_text() -> str:
    """Render the page headless and return the lowercased visible body text."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(locale="da-DK")
            page.goto(URL, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(3_000)  # extra time for late client-side rendering
            text = page.inner_text("body").lower()
            if PAGE_MARKER not in text:
                # Layout changed or page failed to render: keep evidence and fail loudly
                DEBUG_DIR.mkdir(exist_ok=True)
                page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)
                (DEBUG_DIR / "page.txt").write_text(text, encoding="utf-8")
                print(f"ERROR: '{PAGE_MARKER}' not found on page; saved debug info to {DEBUG_DIR}/")
                sys.exit(1)
            return text
        finally:
            browser.close()


def notify(topic: str, status: str, test: bool, note: str = "") -> None:
    """Send the ntfy message for the new status; raises on failure."""
    prefix = "[TEST] " if test else ""
    if status == "open":
        headers = {"Title": "Østergården", "Priority": "urgent", "Click": URL}
        message = prefix + "Ekstern venteliste is OPEN - sign up now!" + note
    else:
        headers = {"Title": "Østergården"}
        message = prefix + "Ekstern venteliste closed again"
    # ntfy reads header values as UTF-8 (the default would send latin-1 and garble "Ø")
    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={k: v.encode("utf-8") for k, v in headers.items()},
        timeout=30,
    )
    resp.raise_for_status()


def read_state() -> tuple[str, int]:
    """Return (status, reminders_sent). state.txt: line 1 status, optional line 2 count."""
    if not STATE_FILE.exists():
        return "unknown", 0
    lines = STATE_FILE.read_text().split()
    count = int(lines[1]) if len(lines) > 1 and lines[1].isdigit() else 0
    return (lines[0] if lines else "unknown"), count


def write_state(status: str, reminders: int = 0) -> None:
    STATE_FILE.write_text(f"{status}\n{reminders}\n")


def notify_burst(topic: str) -> None:
    """Open alert sent several times a few seconds apart; only the first must succeed."""
    for i in range(1, BURST_COUNT + 1):
        note = f" ({i}/{BURST_COUNT})"
        if i == 1:
            notify(topic, "open", test=False, note=note)  # raises -> state not updated -> retried
        else:
            time.sleep(BURST_GAP_SECONDS)
            try:
                notify(topic, "open", test=False, note=note)
            except requests.RequestException as e:
                print(f"WARNING: burst message {i} failed: {e}")


def append_history(status: str) -> None:
    """Append a row to history.csv, creating it with a header if needed."""
    now = datetime.now(timezone.utc)
    new_file = not HISTORY_FILE.exists()
    with HISTORY_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp_utc", "timestamp_copenhagen", "status"])
        w.writerow([
            now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            now.astimezone(ZoneInfo("Europe/Copenhagen")).strftime("%Y-%m-%dT%H:%M:%S%z"),
            status,
        ])


def main() -> None:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        sys.exit("ERROR: NTFY_TOPIC environment variable is missing")

    forced = os.environ.get("FORCE_STATUS", "").strip().lower()
    if forced not in ("", "open", "closed"):
        sys.exit(f"ERROR: FORCE_STATUS must be empty, 'open' or 'closed', got '{forced}'")

    if forced:
        # Simulated run: send a [TEST] notification, never touch state or history
        print(f"FORCED status: {forced} (test run, state/history untouched)")
        notify(topic, forced, test=True)
        print("Test notification sent.")
        return

    text = fetch_page_text()
    status = "closed" if CLOSED_MARKER in text else "open"
    print(f"Detected status: {status}")

    previous, reminders = read_state()
    print(f"Previous status: {previous} (reminders sent: {reminders})")

    if status == previous:
        # Still open: repeat the alert a limited number of times in case it was missed
        if status == "open" and reminders < MAX_REMINDERS:
            n = reminders + 1
            notify(topic, "open", test=False, note=f" (still open, reminder {n}/{MAX_REMINDERS})")
            write_state(status, n)
            print(f"Reminder {n}/{MAX_REMINDERS} sent.")
        else:
            print("No change.")
        return

    # First-ever run finding 'closed' is not news
    if previous == "unknown" and status == "closed":
        print("First run and closed: no notification.")
    elif status == "open":
        notify_burst(topic)
        print("Open notifications sent.")
    else:
        notify(topic, status, test=False)  # raises on failure -> state not updated -> retried
        print("Notification sent.")

    write_state(status)
    append_history(status)
    print(f"State updated to '{status}' and logged to {HISTORY_FILE.name}.")

if __name__ == "__main__":
    main()
