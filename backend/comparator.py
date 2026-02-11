"""
comparator.py - Compare airport diagram extractions to find real changes

This compares two ExtractedDiagram results and identifies:
1. New taxiway designators (taxiway added)
2. Removed taxiway designators (taxiway decommissioned)
3. Renamed taxiways (same location, different name)
4. Geometry changes (significant differences in vector paths)

Focuses on meaningful changes, not cosmetic label repositioning.
"""

import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional, Set
from math import sqrt


@dataclass
class TaxiwayChange:
    """A detected change in taxiway designators."""
    change_type: str      # ADDED, REMOVED, RENAMED
    designator: str       # The taxiway designator
    old_designator: str   # For RENAMED: what it was before
    x: float             # Position X
    y: float             # Position Y
    description: str     # Human-readable description


@dataclass
class RunwayChange:
    """A detected change in runway dimensions."""
    change_type: str      # LENGTH_CHANGED, WIDTH_CHANGED, RUNWAY_ADDED, RUNWAY_REMOVED
    designator: str       # Runway designator (e.g., "4L/22R")
    old_length: int       # Previous length in feet (0 if new runway)
    new_length: int       # New length in feet (0 if removed runway)
    old_width: int        # Previous width in feet
    new_width: int        # New width in feet
    old_x: float          # X position of dimension text in old diagram
    old_y: float          # Y position of dimension text in old diagram
    new_x: float          # X position of dimension text in new diagram
    new_y: float          # Y position of dimension text in new diagram
    description: str      # Human-readable description


@dataclass
class GeometryChange:
    """A detected change in taxiway/runway geometry."""
    change_type: str      # PATH_ADDED, PATH_REMOVED
    x: float             # Approximate center X
    y: float             # Approximate center Y
    description: str


@dataclass
class ComparisonResult:
    """Complete comparison between two diagram versions."""
    airport_code: str
    old_cycle: str
    new_cycle: str
    taxiway_changes: List[TaxiwayChange]
    runway_changes: List[RunwayChange]
    geometry_changes: List[GeometryChange]
    summary: Dict


# Distance threshold for considering two labels "at the same location"
LOCATION_THRESHOLD = 15.0  # PDF units (points)


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculate Euclidean distance between two points."""
    return sqrt((x2 - x1)**2 + (y2 - y1)**2)


def find_nearby_labels(label: dict, labels: List[dict], threshold: float = LOCATION_THRESHOLD) -> List[dict]:
    """Find all labels in the list that are near the given label's position."""
    nearby = []
    for other in labels:
        if distance(label['x'], label['y'], other['x'], other['y']) < threshold:
            nearby.append(other)
    return nearby


def compare_taxiway_labels(old_labels: List[dict], new_labels: List[dict]) -> List[TaxiwayChange]:
    """
    Compare taxiway labels between two diagram versions.

    Detects:
    - ADDED: Designator exists in new but not in old (at any location)
    - REMOVED: Designator exists in old but not in new (at any location)
    - RENAMED: Same location has different designator
    """
    changes = []

    # Get unique designators from each version
    old_designators = {label['designator'] for label in old_labels}
    new_designators = {label['designator'] for label in new_labels}

    # Find added designators (in new but not in old)
    added = new_designators - old_designators
    for designator in added:
        # Find where this designator appears
        for label in new_labels:
            if label['designator'] == designator:
                changes.append(TaxiwayChange(
                    change_type='ADDED',
                    designator=designator,
                    old_designator='',
                    x=label['x'],
                    y=label['y'],
                    description=f"New taxiway '{designator}' added"
                ))
                break  # Only report once per designator

    # Find removed designators (in old but not in new)
    removed = old_designators - new_designators
    for designator in removed:
        # Find where this designator was
        for label in old_labels:
            if label['designator'] == designator:
                changes.append(TaxiwayChange(
                    change_type='REMOVED',
                    designator=designator,
                    old_designator=designator,
                    x=label['x'],
                    y=label['y'],
                    description=f"Taxiway '{designator}' removed"
                ))
                break  # Only report once per designator

    # Check for renames (same location, different name)
    for old_label in old_labels:
        nearby_new = find_nearby_labels(old_label, new_labels)

        for new_label in nearby_new:
            # If there's a label at the same spot with a different name
            if (old_label['designator'] != new_label['designator'] and
                old_label['designator'] not in new_designators and
                new_label['designator'] not in old_designators):

                # This might be a rename
                changes.append(TaxiwayChange(
                    change_type='RENAMED',
                    designator=new_label['designator'],
                    old_designator=old_label['designator'],
                    x=new_label['x'],
                    y=new_label['y'],
                    description=f"Taxiway renamed from '{old_label['designator']}' to '{new_label['designator']}'"
                ))

    return changes


def normalize_runway_designator(designator: str) -> str:
    """
    Normalize runway designator for comparison.

    Handles variations like "4L-22R" vs "4L/22R" vs "22R/4L"
    Returns a canonical form with the lower number first.
    """
    # Replace dash with slash
    designator = designator.replace('-', '/')

    # Split into two ends
    parts = designator.split('/')
    if len(parts) != 2:
        return designator.upper()

    # Extract numeric parts for sorting
    def get_number(s):
        num = ''.join(c for c in s if c.isdigit())
        return int(num) if num else 0

    # Sort so lower number comes first
    if get_number(parts[0]) > get_number(parts[1]):
        parts = [parts[1], parts[0]]

    return f"{parts[0].upper()}/{parts[1].upper()}"


def compare_runway_dimensions(old_runways: List[dict], new_runways: List[dict]) -> List[RunwayChange]:
    """
    Compare runway dimensions between two diagram versions.

    Detects:
    - LENGTH_CHANGED: Runway length increased or decreased
    - WIDTH_CHANGED: Runway width increased or decreased
    - RUNWAY_ADDED: New runway added
    - RUNWAY_REMOVED: Runway removed
    """
    changes = []

    # Build lookup dictionaries by normalized designator
    old_by_designator = {}
    for rwy in old_runways:
        norm = normalize_runway_designator(rwy.get('designator', ''))
        if norm and norm != 'UNKNOWN':
            old_by_designator[norm] = rwy

    new_by_designator = {}
    for rwy in new_runways:
        norm = normalize_runway_designator(rwy.get('designator', ''))
        if norm and norm != 'UNKNOWN':
            new_by_designator[norm] = rwy

    # Find added runways
    for designator, rwy in new_by_designator.items():
        if designator not in old_by_designator:
            changes.append(RunwayChange(
                change_type='RUNWAY_ADDED',
                designator=designator,
                old_length=0,
                new_length=rwy.get('length_ft', 0),
                old_width=0,
                new_width=rwy.get('width_ft', 0),
                old_x=0,
                old_y=0,
                new_x=rwy.get('x', 0),
                new_y=rwy.get('y', 0),
                description=f"New runway {designator}: {rwy.get('length_ft', 0)} x {rwy.get('width_ft', 0)} ft"
            ))

    # Find removed runways
    for designator, rwy in old_by_designator.items():
        if designator not in new_by_designator:
            changes.append(RunwayChange(
                change_type='RUNWAY_REMOVED',
                designator=designator,
                old_length=rwy.get('length_ft', 0),
                new_length=0,
                old_width=rwy.get('width_ft', 0),
                new_width=0,
                old_x=rwy.get('x', 0),
                old_y=rwy.get('y', 0),
                new_x=0,
                new_y=0,
                description=f"Runway {designator} removed (was {rwy.get('length_ft', 0)} x {rwy.get('width_ft', 0)} ft)"
            ))

    # Find dimension changes
    for designator, new_rwy in new_by_designator.items():
        if designator in old_by_designator:
            old_rwy = old_by_designator[designator]

            old_length = old_rwy.get('length_ft', 0)
            new_length = new_rwy.get('length_ft', 0)
            old_width = old_rwy.get('width_ft', 0)
            new_width = new_rwy.get('width_ft', 0)

            # Get positions from the runway data
            old_x = old_rwy.get('x', 0)
            old_y = old_rwy.get('y', 0)
            new_x = new_rwy.get('x', 0)
            new_y = new_rwy.get('y', 0)

            # Check for length change
            if old_length != new_length and old_length > 0 and new_length > 0:
                diff = new_length - old_length
                direction = "extended" if diff > 0 else "shortened"
                changes.append(RunwayChange(
                    change_type='LENGTH_CHANGED',
                    designator=designator,
                    old_length=old_length,
                    new_length=new_length,
                    old_width=old_width,
                    new_width=new_width,
                    old_x=old_x,
                    old_y=old_y,
                    new_x=new_x,
                    new_y=new_y,
                    description=f"Runway {designator} {direction} by {abs(diff)} ft ({old_length} → {new_length} ft)"
                ))

            # Check for width change
            if old_width != new_width and old_width > 0 and new_width > 0:
                diff = new_width - old_width
                direction = "widened" if diff > 0 else "narrowed"
                changes.append(RunwayChange(
                    change_type='WIDTH_CHANGED',
                    designator=designator,
                    old_length=old_length,
                    new_length=new_length,
                    old_width=old_width,
                    new_width=new_width,
                    old_x=old_x,
                    old_y=old_y,
                    new_x=new_x,
                    new_y=new_y,
                    description=f"Runway {designator} {direction} by {abs(diff)} ft ({old_width} → {new_width} ft wide)"
                ))

    return changes


def compare_geometry(old_paths: List[dict], new_paths: List[dict]) -> List[GeometryChange]:
    """
    Compare vector paths between diagram versions.

    This is a simplified comparison - a full implementation would need
    to cluster paths into taxiway segments and compare those.

    For now, we report significant differences in path counts/coverage.
    """
    changes = []

    # Simple comparison: significant difference in number of paths
    path_diff = len(new_paths) - len(old_paths)
    if abs(path_diff) > 50:  # Threshold for "significant"
        if path_diff > 0:
            changes.append(GeometryChange(
                change_type='GEOMETRY_ADDED',
                x=0, y=0,
                description=f"Approximately {path_diff} new path segments added (possible new taxiway geometry)"
            ))
        else:
            changes.append(GeometryChange(
                change_type='GEOMETRY_REMOVED',
                x=0, y=0,
                description=f"Approximately {-path_diff} path segments removed (possible taxiway removal)"
            ))

    return changes


def compare_extractions(old_data: dict, new_data: dict) -> ComparisonResult:
    """
    Compare two extracted diagram datasets.
    """
    # Compare taxiway labels
    old_labels = old_data.get('taxiway_labels', [])
    new_labels = new_data.get('taxiway_labels', [])
    taxiway_changes = compare_taxiway_labels(old_labels, new_labels)

    # Compare runway dimensions
    old_runways = old_data.get('runway_info', [])
    new_runways = new_data.get('runway_info', [])
    runway_changes = compare_runway_dimensions(old_runways, new_runways)

    # Compare geometry
    old_paths = old_data.get('paths', [])
    new_paths = new_data.get('paths', [])
    geometry_changes = compare_geometry(old_paths, new_paths)

    # Build summary
    summary = {
        'total_changes': len(taxiway_changes) + len(runway_changes) + len(geometry_changes),
        'taxiways_added': sum(1 for c in taxiway_changes if c.change_type == 'ADDED'),
        'taxiways_removed': sum(1 for c in taxiway_changes if c.change_type == 'REMOVED'),
        'taxiways_renamed': sum(1 for c in taxiway_changes if c.change_type == 'RENAMED'),
        'runway_changes': len(runway_changes),
        'runway_length_changes': sum(1 for c in runway_changes if c.change_type == 'LENGTH_CHANGED'),
        'runway_width_changes': sum(1 for c in runway_changes if c.change_type == 'WIDTH_CHANGED'),
        'geometry_changes': len(geometry_changes),
        'old_label_count': len(old_labels),
        'new_label_count': len(new_labels),
        'old_unique_designators': len(set(l['designator'] for l in old_labels)),
        'new_unique_designators': len(set(l['designator'] for l in new_labels)),
        'old_runway_count': len(old_runways),
        'new_runway_count': len(new_runways)
    }

    return ComparisonResult(
        airport_code=new_data.get('airport_code', 'UNKNOWN'),
        old_cycle=old_data.get('cycle', 'UNKNOWN'),
        new_cycle=new_data.get('cycle', 'UNKNOWN'),
        taxiway_changes=taxiway_changes,
        runway_changes=runway_changes,
        geometry_changes=geometry_changes,
        summary=summary
    )


def to_dict(result: ComparisonResult) -> dict:
    """Convert ComparisonResult to dictionary for JSON/API."""
    return {
        'airport_code': result.airport_code,
        'old_cycle': result.old_cycle,
        'new_cycle': result.new_cycle,
        'taxiway_changes': [asdict(c) for c in result.taxiway_changes],
        'runway_changes': [asdict(c) for c in result.runway_changes],
        'geometry_changes': [asdict(c) for c in result.geometry_changes],
        'summary': result.summary,
        # For backwards compatibility with frontend
        'changes': [
            {
                'change_type': c.change_type,
                'category': 'taxiway',
                'old_text': c.old_designator,
                'new_text': c.designator,
                'old_position': (c.x, c.y, c.x + 10, c.y + 10) if c.change_type == 'REMOVED' else (0, 0, 0, 0),
                'new_position': (c.x, c.y, c.x + 10, c.y + 10) if c.change_type != 'REMOVED' else (0, 0, 0, 0),
                'description': c.description
            }
            for c in result.taxiway_changes
        ] + [
            {
                'change_type': c.change_type,
                'category': 'runway',
                'old_text': f"{c.old_length} x {c.old_width}",
                'new_text': f"{c.new_length} x {c.new_width}",
                'old_position': (0, 0, 0, 0),
                'new_position': (0, 0, 0, 0),
                'description': c.description
            }
            for c in result.runway_changes
        ] + [
            {
                'change_type': c.change_type,
                'category': 'geometry',
                'old_text': '',
                'new_text': '',
                'old_position': (0, 0, 0, 0),
                'new_position': (0, 0, 0, 0),
                'description': c.description
            }
            for c in result.geometry_changes
        ]
    }


def compare_from_files(old_json_path: str, new_json_path: str) -> ComparisonResult:
    """Compare two extraction JSON files."""
    with open(old_json_path, 'r') as f:
        old_data = json.load(f)

    with open(new_json_path, 'r') as f:
        new_data = json.load(f)

    return compare_extractions(old_data, new_data)


def save_comparison(result: ComparisonResult, output_path: str = None) -> str:
    """Save comparison results to a JSON file."""
    if output_path is None:
        data_dir = Path(__file__).parent.parent / "data"
        output_path = data_dir / f"{result.airport_code}_comparison_{result.old_cycle}_to_{result.new_cycle}.json"

    output_path = Path(output_path)
    with open(output_path, 'w') as f:
        json.dump(to_dict(result), f, indent=2)

    print(f"Saved comparison to: {output_path}")
    return str(output_path)


def print_report(result: ComparisonResult):
    """Print a human-readable change report."""
    print(f"\n{'='*60}")
    print(f"AIRPORT DIAGRAM CHANGE REPORT")
    print(f"{'='*60}")
    print(f"Airport:        {result.airport_code}")
    print(f"Old Cycle:      {result.old_cycle}")
    print(f"New Cycle:      {result.new_cycle}")
    print(f"{'='*60}")

    s = result.summary
    print(f"\nSummary:")
    print(f"  Old diagram: {s['old_unique_designators']} unique taxiway designators")
    print(f"  New diagram: {s['new_unique_designators']} unique taxiway designators")
    print(f"  Taxiways added:   {s['taxiways_added']}")
    print(f"  Taxiways removed: {s['taxiways_removed']}")
    print(f"  Taxiways renamed: {s['taxiways_renamed']}")
    print(f"  Runway changes:   {s.get('runway_changes', 0)}")
    print(f"  Geometry changes: {s['geometry_changes']}")

    if result.taxiway_changes:
        print(f"\nTaxiway Changes:")
        print("-" * 60)
        for change in result.taxiway_changes:
            print(f"  [{change.change_type:8}] {change.description}")
            print(f"             Location: ({change.x:.0f}, {change.y:.0f})")

    if result.runway_changes:
        print(f"\nRunway Changes:")
        print("-" * 60)
        for change in result.runway_changes:
            print(f"  [{change.change_type:15}] {change.description}")

    if result.geometry_changes:
        print(f"\nGeometry Changes:")
        print("-" * 60)
        for change in result.geometry_changes:
            print(f"  [{change.change_type}] {change.description}")

    if not result.taxiway_changes and not result.runway_changes and not result.geometry_changes:
        print(f"\n  No significant changes detected between cycles.")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    from pathlib import Path

    data_dir = Path(__file__).parent.parent / "data"
    json_files = sorted(data_dir.glob("JFK_*_extracted.json"))

    if len(json_files) < 2:
        print("Need at least 2 extraction files to compare.")
        print("Run the extractor on both cycle PDFs first.")
        exit(1)

    old_file = json_files[0]
    new_file = json_files[1]

    print(f"Comparing:")
    print(f"  Old: {old_file.name}")
    print(f"  New: {new_file.name}")

    result = compare_from_files(str(old_file), str(new_file))
    print_report(result)
    save_comparison(result)
