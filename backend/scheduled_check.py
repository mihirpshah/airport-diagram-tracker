"""
scheduled_check.py - Daily scheduled check for airport diagram changes

This script is designed to run as a cron job on Render.com.
It checks all configured airports for changes and sends email alerts.

Usage:
    python -m backend.scheduled_check

Environment variables:
    - GMAIL_ADDRESS: Your Gmail address
    - GMAIL_APP_PASSWORD: Gmail App Password
    - ALERT_RECIPIENT_EMAIL: Where to send alerts
    - APP_URL: (optional) URL to the deployed web app
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from backend.downloader import AIRPORTS, download_airport_pair, get_current_cycle, get_previous_cycle
    from backend.pdf_extractor import extract_from_pdf, save_extraction
    from backend.comparator import compare_extractions, to_dict as comparison_to_dict
    from backend.email_alerts import send_change_alert, send_daily_summary, is_email_configured
except ImportError:
    from downloader import AIRPORTS, download_airport_pair, get_current_cycle, get_previous_cycle
    from pdf_extractor import extract_from_pdf, save_extraction
    from comparator import compare_extractions, to_dict as comparison_to_dict
    from email_alerts import send_change_alert, send_daily_summary, is_email_configured

import json


def get_data_dir() -> Path:
    """Get the data directory path."""
    # Use environment variable if set (for production), otherwise use local data dir
    data_dir = Path(os.environ.get('DATA_DIR', Path(__file__).parent.parent / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


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


def run_scheduled_check():
    """
    Run the scheduled check for all airports.
    Downloads PDFs, extracts data, compares, and sends email alerts.
    """
    print("=" * 60)
    print("Airport Diagram Change Tracker - Scheduled Check")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # Check email configuration
    if not is_email_configured():
        print("\n⚠️  Warning: Email alerts not configured.")
        print("   Set GMAIL_ADDRESS, GMAIL_APP_PASSWORD, ALERT_RECIPIENT_EMAIL")
        print("   Continuing without email alerts...\n")

    data_dir = get_data_dir()
    app_url = os.environ.get('APP_URL', '')

    print(f"\nData directory: {data_dir}")
    print(f"Airports to check: {list(AIRPORTS.keys())}")
    print()

    # Check each airport
    changes_by_airport = {}
    no_change_airports = []

    for airport_code in AIRPORTS.keys():
        result = check_airport_for_changes(airport_code, data_dir)

        if result['error']:
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

    # Send daily summary
    print()
    print("-" * 60)
    print("Summary:")
    print(f"  Airports with changes: {len(changes_by_airport)}")
    print(f"  Airports without changes: {len(no_change_airports)}")

    if is_email_configured():
        send_daily_summary(
            changes_by_airport=changes_by_airport,
            no_change_airports=no_change_airports,
            app_url=app_url
        )

    print("=" * 60)
    print("Scheduled check complete.")
    print("=" * 60)

    return changes_by_airport


if __name__ == "__main__":
    run_scheduled_check()
