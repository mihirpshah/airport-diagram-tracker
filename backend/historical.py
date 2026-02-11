"""
historical.py - Find historical changes in airport diagrams

This module analyzes multiple past cycles to find when the last change occurred.
It downloads and extracts diagrams going back in time until it finds a difference.
"""

import json
from pathlib import Path
from typing import Optional, Tuple, Dict, List

from downloader import (
    AIRPORTS, download_diagram, get_current_cycle,
    get_previous_cycle, get_historical_cycles, DATA_DIR
)
from pdf_extractor import extract_from_pdf, save_extraction, to_dict as extraction_to_dict
from comparator import compare_extractions, to_dict as comparison_to_dict


def get_extraction(airport_code: str, cycle: str) -> Optional[dict]:
    """
    Get extraction data for an airport/cycle, extracting if needed.

    Returns:
        Extraction dict or None if unavailable
    """
    extract_path = DATA_DIR / f"{airport_code}_{cycle}_extracted.json"

    # Return cached extraction if exists
    if extract_path.exists():
        with open(extract_path, 'r') as f:
            return json.load(f)

    # Download PDF if needed
    pdf_path = DATA_DIR / f"{airport_code}_{cycle}.pdf"
    if not pdf_path.exists():
        downloaded = download_diagram(airport_code, cycle)
        if not downloaded:
            return None

    # Extract
    data = extract_from_pdf(str(pdf_path))
    if data:
        save_extraction(data)
        return extraction_to_dict(data)

    return None


def find_last_change(airport_code: str, max_cycles: int = 13) -> Dict:
    """
    Find the last cycle where a change occurred for an airport.

    Compares the current diagram against progressively older versions
    until it finds one that differs.

    Args:
        airport_code: 3-letter airport code
        max_cycles: Maximum number of cycles to search back

    Returns:
        Dict with:
            - found: bool - whether a change was found
            - current_cycle: current cycle code
            - last_change_cycle: cycle where last change occurred (or None)
            - cycles_searched: number of cycles checked
            - changes: list of changes found (if any)
            - error: error message if failed
    """
    airport_code = airport_code.upper()

    if airport_code not in AIRPORTS:
        return {'found': False, 'error': f'Unknown airport: {airport_code}'}

    current_cycle = get_current_cycle()
    print(f"\nSearching for last change in {airport_code} diagrams...")
    print(f"Current cycle: {current_cycle}")

    # Get current extraction
    current_data = get_extraction(airport_code, current_cycle)
    if not current_data:
        return {'found': False, 'error': 'Could not extract current diagram'}

    current_designators = set(
        label['designator'] for label in current_data.get('taxiway_labels', [])
    )
    print(f"Current diagram has {len(current_designators)} unique taxiway designators")

    # Get current runway dimensions for comparison
    current_runways = {
        rwy.get('designator', ''): (rwy.get('length_ft', 0), rwy.get('width_ft', 0))
        for rwy in current_data.get('runway_info', [])
        if rwy.get('designator', '') != 'Unknown'
    }
    print(f"Current diagram has {len(current_runways)} runways with dimensions")

    # Search backwards through cycles
    cycles_searched = 0
    cycle = get_previous_cycle(current_cycle)

    while cycles_searched < max_cycles:
        cycles_searched += 1
        print(f"  Checking cycle {cycle}...")

        old_data = get_extraction(airport_code, cycle)
        if not old_data:
            print(f"    Cycle {cycle} not available - stopping search")
            break

        old_designators = set(
            label['designator'] for label in old_data.get('taxiway_labels', [])
        )

        # Get old runway dimensions
        old_runways = {
            rwy.get('designator', ''): (rwy.get('length_ft', 0), rwy.get('width_ft', 0))
            for rwy in old_data.get('runway_info', [])
            if rwy.get('designator', '') != 'Unknown'
        }

        # Check for taxiway differences
        taxiway_added = current_designators - old_designators
        taxiway_removed = old_designators - current_designators

        # Check for runway dimension differences
        runway_changes = []
        for rwy, (cur_len, cur_wid) in current_runways.items():
            if rwy in old_runways:
                old_len, old_wid = old_runways[rwy]
                if old_len != cur_len:
                    runway_changes.append(f"{rwy} length: {old_len} → {cur_len} ft")
                if old_wid != cur_wid:
                    runway_changes.append(f"{rwy} width: {old_wid} → {cur_wid} ft")

        # Check for added/removed runways
        for rwy in set(current_runways.keys()) - set(old_runways.keys()):
            runway_changes.append(f"{rwy} added")
        for rwy in set(old_runways.keys()) - set(current_runways.keys()):
            runway_changes.append(f"{rwy} removed")

        if taxiway_added or taxiway_removed or runway_changes:
            print(f"    FOUND CHANGE at cycle {cycle}!")
            if taxiway_added:
                print(f"    Taxiways added since {cycle}: {taxiway_added}")
            if taxiway_removed:
                print(f"    Taxiways removed since {cycle}: {taxiway_removed}")
            if runway_changes:
                print(f"    Runway changes since {cycle}: {runway_changes}")

            # Get full comparison
            comparison = compare_extractions(old_data, current_data)

            return {
                'found': True,
                'current_cycle': current_cycle,
                'last_change_cycle': cycle,
                'cycles_searched': cycles_searched,
                'taxiways_added': list(taxiway_added),
                'taxiways_removed': list(taxiway_removed),
                'runway_changes': runway_changes,
                'comparison': comparison_to_dict(comparison)
            }

        cycle = get_previous_cycle(cycle)

    print(f"  No changes found in last {cycles_searched} cycles")
    return {
        'found': False,
        'current_cycle': current_cycle,
        'last_change_cycle': None,
        'cycles_searched': cycles_searched,
        'message': f'No changes found in last {cycles_searched} cycles (~{cycles_searched * 28} days)'
    }


def get_historical_summary(airport_code: str) -> Dict:
    """
    Get a summary of historical changes for an airport.

    Returns cached result if available, otherwise runs analysis.
    """
    airport_code = airport_code.upper()
    cache_path = DATA_DIR / f"{airport_code}_historical.json"

    # Check for cached result (valid for current cycle)
    if cache_path.exists():
        with open(cache_path, 'r') as f:
            cached = json.load(f)
        if cached.get('current_cycle') == get_current_cycle():
            print(f"Using cached historical analysis for {airport_code}")
            return cached

    # Run fresh analysis
    result = find_last_change(airport_code)

    # Cache the result
    with open(cache_path, 'w') as f:
        json.dump(result, f, indent=2)

    return result


if __name__ == "__main__":
    import sys

    airport = sys.argv[1] if len(sys.argv) > 1 else "JFK"

    print(f"Finding last change for {airport}...")
    result = find_last_change(airport, max_cycles=13)

    print(f"\n{'='*60}")
    print("RESULT:")
    print(f"{'='*60}")

    if result.get('found'):
        print(f"Last change found at cycle: {result['last_change_cycle']}")
        print(f"Cycles searched: {result['cycles_searched']}")
        print(f"Taxiways added since then: {result.get('taxiways_added', [])}")
        print(f"Taxiways removed since then: {result.get('taxiways_removed', [])}")
    else:
        print(f"No changes found")
        print(f"Cycles searched: {result.get('cycles_searched', 0)}")
        if result.get('error'):
            print(f"Error: {result['error']}")
        if result.get('message'):
            print(f"Note: {result['message']}")
