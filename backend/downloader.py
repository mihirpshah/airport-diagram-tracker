"""
downloader.py - Download FAA Airport Diagram PDFs

This script fetches airport diagram PDFs from the FAA's aeronav website.
PDFs are published on a 28-day cycle (called AIRAC cycles).

URL pattern: https://aeronav.faa.gov/d-tpp/{cycle}/{airport_num}AD.PDF
- cycle: 4 digits = YY + cycle_number (01-13)
- airport_num: 5-digit FAA identifier for the airport
"""

import os
import requests
from datetime import datetime, timedelta
from pathlib import Path

# Airport codes and their FAA diagram numbers
AIRPORTS = {
    "JFK": "00610",   # John F. Kennedy International
    "LGA": "00289",   # LaGuardia
    "EWR": "00285",   # Newark Liberty International
    "TEB": "00890",   # Teterboro
    "SWF": "00450",   # Stewart International
    "SYR": "00411",   # Syracuse Hancock International
    "YIP": "00467",   # Willow Run (test - new taxiway completed Oct 2025)
}

# Base URL for FAA digital terminal procedures
FAA_BASE_URL = "https://aeronav.faa.gov/d-tpp"

# Where to save downloaded PDFs
# Use DATA_DIR environment variable if set (for production), otherwise use local data dir
DATA_DIR = Path(os.environ.get('DATA_DIR', Path(__file__).parent.parent / "data"))


def get_current_cycle():
    """
    Calculate the current AIRAC cycle number.

    AIRAC cycles are 28 days each, starting from a known reference date.
    The cycle code is: YY + NN where YY=year, NN=cycle number (01-13)

    Returns:
        str: 4-digit cycle code like "2602" (2026, cycle 02)
    """
    # Reference: Cycle 2601 started on 2025-12-26
    # Each cycle is exactly 28 days
    reference_date = datetime(2025, 12, 26)
    reference_cycle = 1
    reference_year = 26  # Last two digits of 2026

    today = datetime.now()
    days_since_reference = (today - reference_date).days

    # Calculate how many complete cycles have passed
    cycles_passed = days_since_reference // 28

    # Calculate current cycle number (1-13 per year)
    current_cycle = reference_cycle + cycles_passed
    current_year = reference_year

    # Handle year rollover (13 cycles per year)
    while current_cycle > 13:
        current_cycle -= 13
        current_year += 1

    # Format as 4-digit string: YYNN
    return f"{current_year:02d}{current_cycle:02d}"


def get_previous_cycle(current_cycle):
    """
    Get the previous AIRAC cycle code.

    Args:
        current_cycle: Current cycle as string like "2602"

    Returns:
        str: Previous cycle code like "2601" or "2513" if crossing year boundary
    """
    year = int(current_cycle[:2])
    cycle = int(current_cycle[2:])

    if cycle == 1:
        # Roll back to previous year's cycle 13
        return f"{year - 1:02d}13"
    else:
        return f"{year:02d}{cycle - 1:02d}"


def download_diagram(airport_code, cycle, force=False):
    """
    Download a single airport diagram PDF from the FAA website.

    Args:
        airport_code: 3-letter airport code like "JFK"
        cycle: 4-digit AIRAC cycle like "2602"
        force: If True, download even if file already exists

    Returns:
        Path: Path to the downloaded file, or None if download failed
    """
    if airport_code not in AIRPORTS:
        print(f"Error: Unknown airport code '{airport_code}'")
        print(f"Valid codes: {', '.join(AIRPORTS.keys())}")
        return None

    airport_num = AIRPORTS[airport_code]

    # Build the URL and local file path
    url = f"{FAA_BASE_URL}/{cycle}/{airport_num}AD.PDF"
    filename = f"{airport_code}_{cycle}.pdf"
    filepath = DATA_DIR / filename

    # Skip if already downloaded (unless force=True)
    if filepath.exists() and not force:
        print(f"Already exists: {filename}")
        return filepath

    # Create data directory if it doesn't exist
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {airport_code} cycle {cycle}...")
    print(f"  URL: {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Raise error for 404, 500, etc.

        # Save the PDF
        with open(filepath, 'wb') as f:
            f.write(response.content)

        print(f"  Saved: {filepath}")
        return filepath

    except requests.exceptions.HTTPError as e:
        print(f"  Error: HTTP {e.response.status_code} - diagram may not exist for this cycle")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  Error downloading: {e}")
        return None


def download_airport_pair(airport_code, current_cycle=None):
    """
    Download current and previous cycle diagrams for an airport.

    Args:
        airport_code: 3-letter airport code like "JFK"
        current_cycle: Optional cycle override (auto-calculated if not provided)

    Returns:
        tuple: (current_path, previous_path) or (None, None) on failure
    """
    if current_cycle is None:
        current_cycle = get_current_cycle()

    previous_cycle = get_previous_cycle(current_cycle)

    print(f"\n{'='*50}")
    print(f"Airport: {airport_code}")
    print(f"Current cycle: {current_cycle}")
    print(f"Previous cycle: {previous_cycle}")
    print('='*50)

    current_path = download_diagram(airport_code, current_cycle)
    previous_path = download_diagram(airport_code, previous_cycle)

    return current_path, previous_path


def download_all_airports():
    """Download current and previous diagrams for all configured airports."""
    current_cycle = get_current_cycle()

    print(f"FAA Airport Diagram Downloader")
    print(f"Current AIRAC cycle: {current_cycle}")
    print(f"Downloading diagrams for: {', '.join(AIRPORTS.keys())}")

    results = {}
    for airport_code in AIRPORTS:
        current_path, previous_path = download_airport_pair(airport_code, current_cycle)
        results[airport_code] = {
            'current': current_path,
            'previous': previous_path
        }

    return results


def get_historical_cycles(num_cycles: int = 13) -> list:
    """
    Get a list of historical cycle codes going back from current.

    Args:
        num_cycles: Number of cycles to go back (default 13 = ~1 year)

    Returns:
        List of cycle codes from current going backwards, e.g., ['2602', '2601', '2513', ...]
    """
    cycles = []
    current = get_current_cycle()
    cycles.append(current)

    for _ in range(num_cycles - 1):
        current = get_previous_cycle(current)
        cycles.append(current)

    return cycles


def download_historical_cycles(airport_code: str, num_cycles: int = 13, quiet: bool = False):
    """
    Download multiple historical cycles for an airport.

    Args:
        airport_code: 3-letter airport code
        num_cycles: Number of cycles to download (default 13 = ~1 year)
        quiet: If True, suppress most output

    Returns:
        List of (cycle, path) tuples for successfully downloaded files
    """
    cycles = get_historical_cycles(num_cycles)
    results = []

    if not quiet:
        print(f"Downloading {num_cycles} historical cycles for {airport_code}...")

    for cycle in cycles:
        path = download_diagram(airport_code, cycle)
        if path:
            results.append((cycle, path))
        else:
            # Stop if we hit a cycle that doesn't exist (too old)
            if not quiet:
                print(f"  Stopping at cycle {cycle} - not available")
            break

    return results


# When run directly, download JFK as a test
if __name__ == "__main__":
    print("Testing downloader with JFK airport...")
    current_path, previous_path = download_airport_pair("JFK")

    if current_path and previous_path:
        print(f"\nSuccess! Downloaded:")
        print(f"  Current:  {current_path}")
        print(f"  Previous: {previous_path}")
    else:
        print("\nSome downloads failed. Check the error messages above.")
