"""
scheduled_check.py - Scheduled check for airport diagram changes

This script checks all configured hub airports for diagram changes
and sends email alerts when changes are detected.

It's designed to run:
1. On a schedule (e.g., daily via cron) to catch new AIRAC cycles
2. Manually when you want to check for updates

The script detects when a new AIRAC cycle is published (every 28 days)
and compares the new diagrams against the previous cycle.

Usage:
    python -m backend.scheduled_check          # Normal check
    python -m backend.scheduled_check --force  # Force check even if already run

Environment variables:
    - GMAIL_ADDRESS: Your Gmail address
    - GMAIL_APP_PASSWORD: Gmail App Password
    - ALERT_RECIPIENTS: Comma-separated list of email addresses
    - APP_URL: (optional) URL to the deployed web app
    - DATA_DIR: (optional) Directory to store PDFs and extractions
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from backend.downloader import (
        AIRPORTS, download_airport_pair, get_current_cycle,
        get_previous_cycle, get_latest_available_cycle
    )
    from backend.pdf_extractor import extract_from_pdf, save_extraction
    from backend.comparator import compare_extractions, to_dict as comparison_to_dict
    from backend.email_alerts import send_change_alert, send_daily_summary, is_email_configured
except ImportError:
    from downloader import (
        AIRPORTS, download_airport_pair, get_current_cycle,
        get_previous_cycle, get_latest_available_cycle
    )
    from pdf_extractor import extract_from_pdf, save_extraction
    from comparator import compare_extractions, to_dict as comparison_to_dict
    from email_alerts import send_change_alert, send_daily_summary, is_email_configured


# File to track the last checked cycle
LAST_CHECK_FILE = "last_checked_cycle.txt"


def get_data_dir() -> Path:
    """Get the data directory path."""
    # Use environment variable if set (for production), otherwise use local data dir
    data_dir = Path(os.environ.get('DATA_DIR', Path(__file__).parent.parent / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_last_checked_cycle(data_dir: Path) -> str:
    """
    Get the last AIRAC cycle that was checked.
    Returns empty string if never checked before.
    """
    check_file = data_dir / LAST_CHECK_FILE
    if check_file.exists():
        return check_file.read_text().strip()
    return ""


def save_last_checked_cycle(data_dir: Path, cycle: str):
    """Save the current cycle as the last checked cycle."""
    check_file = data_dir / LAST_CHECK_FILE
    check_file.write_text(cycle)
    print(f"  Saved last checked cycle: {cycle}")


def is_new_cycle_available(data_dir: Path) -> tuple:
    """
    Check if a new AIRAC cycle is available that hasn't been checked yet.

    Returns:
        (is_new, current_cycle, last_checked_cycle)
    """
    current_cycle = get_latest_available_cycle()
    last_checked = get_last_checked_cycle(data_dir)

    if not last_checked:
        # First time running - this is "new"
        return (True, current_cycle, last_checked)

    # Compare cycles (format: YYNN where YY=year, NN=cycle 01-13)
    is_new = current_cycle != last_checked
    return (is_new, current_cycle, last_checked)


def check_airport_for_changes(airport_code: str, data_dir: Path) -> dict:
    """
    Check a single airport for diagram changes.

    Returns dict with:
        - has_changes: bool
        - taxiway_changes: list
        - runway_changes: list
        - old_cycle: str
        - new_cycle: str
        - error: str (if any)
    """
    result = {
        'airport_code': airport_code,
        'has_changes': False,
        'taxiway_changes': [],
        'runway_changes': [],
        'old_cycle': '',
        'new_cycle': '',
        'error': None
    }

    try:
        current_cycle = get_current_cycle()
        previous_cycle = get_previous_cycle(current_cycle)
        result['old_cycle'] = previous_cycle
        result['new_cycle'] = current_cycle

        print(f"  Checking {airport_code}: {previous_cycle} → {current_cycle}")

        # Download PDFs if needed
        current_pdf = data_dir / f"{airport_code}_{current_cycle}.pdf"
        previous_pdf = data_dir / f"{airport_code}_{previous_cycle}.pdf"

        if not current_pdf.exists() or not previous_pdf.exists():
            print(f"    Downloading PDFs...")
            download_airport_pair(airport_code)

        # Extract if needed
        current_extract = data_dir / f"{airport_code}_{current_cycle}_extracted.json"
        previous_extract = data_dir / f"{airport_code}_{previous_cycle}_extracted.json"

        if not current_extract.exists() and current_pdf.exists():
            print(f"    Extracting {current_cycle}...")
            data = extract_from_pdf(str(current_pdf))
            if data:
                save_extraction(data, str(current_extract))

        if not previous_extract.exists() and previous_pdf.exists():
            print(f"    Extracting {previous_cycle}...")
            data = extract_from_pdf(str(previous_pdf))
            if data:
                save_extraction(data, str(previous_extract))

        # Compare
        if current_extract.exists() and previous_extract.exists():
            with open(previous_extract, 'r') as f:
                old_data = json.load(f)
            with open(current_extract, 'r') as f:
                new_data = json.load(f)

            comparison = compare_extractions(old_data, new_data)
            comparison_dict = comparison_to_dict(comparison)

            result['taxiway_changes'] = comparison_dict.get('taxiway_changes', [])
            result['runway_changes'] = comparison_dict.get('runway_changes', [])
            result['has_changes'] = len(result['taxiway_changes']) > 0 or len(result['runway_changes']) > 0

            if result['has_changes']:
                print(f"    ⚠️  Changes detected: {len(result['taxiway_changes'])} taxiway, {len(result['runway_changes'])} runway")
            else:
                print(f"    ✓ No changes")
        else:
            result['error'] = "Could not extract PDF data"
            print(f"    ❌ Error: {result['error']}")

    except Exception as e:
        result['error'] = str(e)
        print(f"    ❌ Error: {e}")

    return result


def run_scheduled_check(force: bool = False):
    """
    Run the scheduled check for all airports.
    Downloads PDFs, extracts data, compares, and sends email alerts.

    Args:
        force: If True, run check even if the cycle was already checked
    """
    print("=" * 60)
    print("Airport Diagram Change Tracker - Scheduled Check")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    data_dir = get_data_dir()
    app_url = os.environ.get('APP_URL', 'https://airport-tracker-hubs.onrender.com')

    # Check if a new cycle is available
    is_new, current_cycle, last_checked = is_new_cycle_available(data_dir)

    print(f"\nCurrent AIRAC cycle: {current_cycle}")
    print(f"Last checked cycle:  {last_checked or '(never)'}")

    if not is_new and not force:
        print(f"\n✓ Cycle {current_cycle} was already checked.")
        print("  No new cycle available. Use --force to check anyway.")
        print("=" * 60)
        return {}

    if force and not is_new:
        print(f"\n⚠️  Force mode: Re-checking cycle {current_cycle}")

    # Check email configuration
    if not is_email_configured():
        print("\n⚠️  Warning: Email alerts not configured.")
        print("   Set GMAIL_ADDRESS, GMAIL_APP_PASSWORD, ALERT_RECIPIENTS")
        print("   Continuing without email alerts...\n")

    print(f"\nData directory: {data_dir}")
    print(f"Airports to check: {list(AIRPORTS.keys())}")
    print()

    # Check each airport
    changes_by_airport = {}
    no_change_airports = []
    errors = []

    for airport_code in AIRPORTS.keys():
        result = check_airport_for_changes(airport_code, data_dir)

        if result['error']:
            errors.append((airport_code, result['error']))
            continue

        if result['has_changes']:
            changes_by_airport[airport_code] = result

            # Send individual alert for this airport
            if is_email_configured():
                send_change_alert(
                    airport_code=airport_code,
                    old_cycle=result['old_cycle'],
                    new_cycle=result['new_cycle'],
                    taxiway_changes=result['taxiway_changes'],
                    runway_changes=result['runway_changes'],
                    app_url=app_url
                )
        else:
            no_change_airports.append(airport_code)

    # Print summary (no email if no changes)
    print()
    print("-" * 60)
    print("Summary:")
    print(f"  Airports with changes: {len(changes_by_airport)}")
    print(f"  Airports without changes: {len(no_change_airports)}")
    if errors:
        print(f"  Errors: {len(errors)}")
        for code, err in errors:
            print(f"    - {code}: {err}")

    # Only send summary email if there were changes
    # (Individual airport alerts are already sent above)
    if len(changes_by_airport) > 0 and is_email_configured():
        print("\n📧 Sending summary email (changes detected)...")
        send_daily_summary(
            changes_by_airport=changes_by_airport,
            no_change_airports=no_change_airports,
            app_url=app_url
        )
    elif len(changes_by_airport) == 0:
        print("\n✓ No changes detected - no email sent.")

    # Save the current cycle as checked
    save_last_checked_cycle(data_dir, current_cycle)

    print("=" * 60)
    print("Scheduled check complete.")
    print("=" * 60)

    return changes_by_airport


def main():
    """Entry point with command-line argument parsing."""
    parser = argparse.ArgumentParser(
        description='Check airport diagrams for changes and send email alerts.'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Force check even if the current cycle was already checked'
    )
    parser.add_argument(
        '--test-email',
        action='store_true',
        help='Send a test email to verify configuration'
    )

    args = parser.parse_args()

    if args.test_email:
        # Send a test email
        if not is_email_configured():
            print("❌ Email not configured. Set these environment variables:")
            print("   - GMAIL_ADDRESS")
            print("   - GMAIL_APP_PASSWORD")
            print("   - ALERT_RECIPIENTS")
            sys.exit(1)

        print("Sending test email...")
        from email_alerts import send_change_alert
        result = send_change_alert(
            airport_code="TEST",
            old_cycle="2601",
            new_cycle="2602",
            taxiway_changes=[
                {"change_type": "ADDED", "designator": "Y", "description": "Test: Taxiway Y added"},
            ],
            runway_changes=[],
            app_url=os.environ.get('APP_URL', 'https://airport-tracker-hubs.onrender.com')
        )
        sys.exit(0 if result else 1)

    run_scheduled_check(force=args.force)


if __name__ == "__main__":
    main()
