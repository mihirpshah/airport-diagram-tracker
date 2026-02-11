"""
pdf_extractor.py - Extract taxiway/runway data from FAA Airport Diagram PDFs

This script uses PyMuPDF (fitz) to extract:
1. Taxiway designator labels (single letters or compounds like AA, YA, KD)
2. Runway designations and dimensions
3. Vector graphics (lines/paths) representing taxiway/runway geometry

The extraction focuses on the actual diagram content, filtering out:
- Margin text (notes, legends, title blocks)
- Body text that spells words letter-by-letter
"""

import json
import re
import fitz  # PyMuPDF
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict


@dataclass
class TaxiwayLabel:
    """A taxiway designator label extracted from the diagram."""
    designator: str      # The taxiway name (e.g., "A", "B", "YA", "KD")
    x: float            # Center X position
    y: float            # Center Y position
    bbox: Tuple[float, float, float, float]  # Bounding box (x0, y0, x1, y1)


@dataclass
class RunwayInfo:
    """Runway information extracted from the diagram."""
    designator: str      # e.g., "4L/22R"
    length_ft: int       # Length in feet
    width_ft: int        # Width in feet
    x: float = 0         # X position of the dimension text on the diagram
    y: float = 0         # Y position of the dimension text on the diagram
    surface: str = ""    # Surface type (e.g., "ASPH", "CONC")
    raw_text: str = ""   # Original text for debugging


@dataclass
class PathSegment:
    """A vector path segment (line) from the diagram."""
    x0: float
    y0: float
    x1: float
    y1: float
    width: float        # Line width (thicker = runway, thinner = taxiway)


@dataclass
class ExtractedDiagram:
    """All data extracted from an airport diagram PDF."""
    airport_code: str
    cycle: str
    source_file: str
    page_width: float
    page_height: float
    taxiway_labels: List[TaxiwayLabel] = field(default_factory=list)
    runway_info: List[RunwayInfo] = field(default_factory=list)
    paths: List[PathSegment] = field(default_factory=list)
    raw_runway_text: List[str] = field(default_factory=list)  # For debugging


# Known taxiway designator patterns at major airports
# Single letters: A-Z (excluding I and O which are rarely used)
# Compound: AA, BB, YA, KD, etc.
TAXIWAY_PATTERN = re.compile(r'^[A-HJ-NP-Z]{1,2}[A-Z]?$')

# Runway pattern: number with optional L/C/R suffix
RUNWAY_PATTERN = re.compile(r'^(\d{1,2})([LCR])?$')

# Runway dimension pattern: "12000 X 150" or similar
DIMENSION_PATTERN = re.compile(r'(\d{4,5})\s*[Xx]\s*(\d{2,3})')

# Runway designation with dimensions pattern
# Matches patterns like: "4L-22R   14572 X 150" or "13-31   7000 X 150"
# FAA diagrams typically show: "RWY 4L-22R" followed by dimensions on same or nearby line
RUNWAY_FULL_PATTERN = re.compile(
    r'(\d{1,2}[LCR]?)\s*[-/]\s*(\d{1,2}[LCR]?)\s+(\d{4,5})\s*[Xx]\s*(\d{2,3})'
)

# Alternative: just the dimension block which often includes runway designation nearby
# Pattern for data block text like "RWY 4L-22R S100, D200, 2S175, 2D400..."
RUNWAY_DATA_BLOCK = re.compile(
    r'RWY\s+(\d{1,2}[LCR]?[-/]\d{1,2}[LCR]?)'
)


def is_valid_taxiway_designator(text: str) -> bool:
    """
    Check if text is a valid taxiway designator.

    Valid designators:
    - Single letters A-Z (except I, O which are avoided)
    - Two-letter compounds: AA, BB, YA, KD, NA, etc.
    - Three-letter in some cases: TWY (but we filter this)
    """
    text = text.strip().upper()

    # Filter out common false positives
    false_positives = {
        'TWY', 'RWY', 'TWR', 'GND', 'DEL', 'APP', 'DEP',
        'NOT', 'FOR', 'USE', 'THE', 'AND', 'FEB', 'JAN',
        'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP',
        'OCT', 'NOV', 'DEC', 'FAA', 'USA', 'NYC', 'LAX'
    }

    if text in false_positives:
        return False

    # Must match taxiway pattern
    if not TAXIWAY_PATTERN.match(text):
        return False

    # Single letter taxiways are common
    if len(text) == 1:
        return True

    # Two-letter taxiways: allow if they look like taxiway names
    # (e.g., YA, KD, NA, GG, AA, BB - not random letter combinations)
    if len(text) == 2:
        # Common patterns: doubled letters (AA, BB), or letter+A combinations
        return True

    return False


def extract_diagram_bounds(page) -> Tuple[float, float, float, float]:
    """
    Estimate the bounds of the actual airport diagram area,
    excluding margins, title blocks, and notes.

    Returns (x_min, y_min, x_max, y_max) in page coordinates.
    """
    # For FAA diagrams, the main diagram is typically in the center
    # with margins on all sides containing notes and legends
    width = page.rect.width
    height = page.rect.height

    # Approximate diagram bounds (these work for most FAA diagrams)
    # The diagram itself is usually about 60-70% of the page
    margin_x = width * 0.12   # ~12% margin on each side
    margin_top = height * 0.10  # Top has title
    margin_bottom = height * 0.08  # Bottom has notes

    return (margin_x, margin_top, width - margin_x, height - margin_bottom)


def extract_taxiway_labels(page, bounds: Tuple[float, float, float, float]) -> List[TaxiwayLabel]:
    """
    Extract taxiway designator labels from the diagram.

    Focuses on short uppercase text in the diagram area that matches
    taxiway naming patterns.
    """
    x_min, y_min, x_max, y_max = bounds
    labels = []
    seen_positions = set()  # Avoid duplicates at same position

    # Get text with detailed formatting info
    blocks = page.get_text('dict')['blocks']

    for block in blocks:
        if 'lines' not in block:
            continue

        for line in block['lines']:
            for span in line['spans']:
                text = span['text'].strip().upper()
                bbox = span['bbox']
                x_center = (bbox[0] + bbox[2]) / 2
                y_center = (bbox[1] + bbox[3]) / 2
                font_size = span['size']

                # Skip if outside diagram bounds
                if not (x_min < x_center < x_max and y_min < y_center < y_max):
                    continue

                # Skip very small or very large text (labels are typically 5-8pt)
                if font_size < 4.0 or font_size > 10.0:
                    continue

                # Check if it's a valid taxiway designator
                if not is_valid_taxiway_designator(text):
                    continue

                # Avoid duplicates at nearly the same position
                pos_key = (round(x_center, 0), round(y_center, 0))
                if pos_key in seen_positions:
                    continue
                seen_positions.add(pos_key)

                labels.append(TaxiwayLabel(
                    designator=text,
                    x=x_center,
                    y=y_center,
                    bbox=bbox
                ))

    return labels


def extract_runway_info(page) -> Tuple[List[RunwayInfo], List[str]]:
    """
    Extract runway information from the diagram, including positions.

    FAA airport diagrams contain runway data in a "data block" area,
    typically showing patterns like:
    - "RWY 04L-22R" on one line, with dimensions on a line below
    - Or combined: "4L-22R   12000 X 150"

    The dimensions (e.g., "14511 X 200") are usually listed in the same
    order as the runway designators listed above them.

    Looks for:
    - Runway designations (4L/22R, 13/31, etc.)
    - Runway dimensions (length x width in feet)
    - Position of the dimension text for highlighting
    """
    runways = []
    raw_text = []

    # Get full text from the page
    full_text = page.get_text()

    # Store some raw text for debugging
    raw_text.append(full_text[:1500])

    # First, build a map of dimension text to positions by searching the page
    # This finds where dimension strings like "7200 X 150" appear on the page
    dimension_positions = {}
    blocks = page.get_text('dict')['blocks']

    for block in blocks:
        if 'lines' not in block:
            continue
        for line in block['lines']:
            # Combine all spans in a line to catch "7200 X 150" across spans
            line_text = ""
            line_spans = []
            for span in line['spans']:
                line_text += span['text']
                line_spans.append(span)

            # Search for dimension patterns in this line
            for match in DIMENSION_PATTERN.finditer(line_text):
                length = int(match.group(1))
                width = int(match.group(2))

                if length >= 2000:  # Only runway-sized dimensions
                    # Find position - use center of the line's spans
                    if line_spans:
                        # Get bounding box of entire line
                        x0 = min(s['bbox'][0] for s in line_spans)
                        y0 = min(s['bbox'][1] for s in line_spans)
                        x1 = max(s['bbox'][2] for s in line_spans)
                        y1 = max(s['bbox'][3] for s in line_spans)
                        x_center = (x0 + x1) / 2
                        y_center = (y0 + y1) / 2

                        # Store position keyed by dimension values
                        dim_key = (length, width)
                        if dim_key not in dimension_positions:
                            dimension_positions[dim_key] = (x_center, y_center)

    # Method 1: Look for combined runway designation + dimensions pattern
    # e.g., "4L-22R   14572 X 150" or "13-31   7000 X 150"
    for match in RUNWAY_FULL_PATTERN.finditer(full_text):
        rwy_end1, rwy_end2, length, width = match.groups()
        designator = f"{rwy_end1}/{rwy_end2}"
        length_int = int(length)
        width_int = int(width)

        # Get position if available
        pos = dimension_positions.get((length_int, width_int), (0, 0))

        runways.append(RunwayInfo(
            designator=designator,
            length_ft=length_int,
            width_ft=width_int,
            x=pos[0],
            y=pos[1],
            raw_text=match.group(0)
        ))

    # Method 2: Find all runway designators and dimensions separately,
    # then match them by order of appearance
    if not runways:
        # Find all runway designator patterns
        # Matches "RWY 04L-22R" or "RWYS 04L-22R, 13L-31R"
        rwy_pattern = re.compile(r'RWYS?\s+([\d]{1,2}[LCR]?[-/][\d]{1,2}[LCR]?(?:\s*,\s*[\d]{1,2}[LCR]?[-/][\d]{1,2}[LCR]?)*)')

        all_designators = []
        for match in rwy_pattern.finditer(full_text):
            # Extract individual runway pairs from comma-separated list
            rwy_text = match.group(1)
            pairs = re.findall(r'(\d{1,2}[LCR]?)[-/](\d{1,2}[LCR]?)', rwy_text)
            for end1, end2 in pairs:
                designator = f"{end1}/{end2}"
                if designator not in all_designators:
                    all_designators.append(designator)

        # Find all dimension patterns with positions
        all_dimensions = []
        for match in DIMENSION_PATTERN.finditer(full_text):
            length, width = int(match.group(1)), int(match.group(2))
            # Only include if it looks like a runway (length > 2000 ft)
            if length >= 2000:
                pos = dimension_positions.get((length, width), (0, 0))
                all_dimensions.append((length, width, pos[0], pos[1]))

        # Match designators to dimensions by order
        # (FAA diagrams typically list them in corresponding order)
        for i, designator in enumerate(all_designators):
            if i < len(all_dimensions):
                length, width, x, y = all_dimensions[i]
                runways.append(RunwayInfo(
                    designator=designator,
                    length_ft=length,
                    width_ft=width,
                    x=x,
                    y=y,
                    raw_text=f"{designator}: {length} x {width}"
                ))

        # If we have extra dimensions without designators, add them as unknown
        for i in range(len(all_designators), len(all_dimensions)):
            length, width, x, y = all_dimensions[i]
            runways.append(RunwayInfo(
                designator="Unknown",
                length_ft=length,
                width_ft=width,
                x=x,
                y=y,
                raw_text=f"Unknown: {length} x {width}"
            ))

    # Method 3: If still no runways, just find all dimensions
    if not runways:
        for match in DIMENSION_PATTERN.finditer(full_text):
            length, width = int(match.group(1)), int(match.group(2))
            if length >= 2000:
                pos = dimension_positions.get((length, width), (0, 0))
                runways.append(RunwayInfo(
                    designator="Unknown",
                    length_ft=length,
                    width_ft=width,
                    x=pos[0],
                    y=pos[1],
                    raw_text=match.group(0)
                ))

    return runways, raw_text


def extract_vector_paths(page, bounds: Tuple[float, float, float, float]) -> List[PathSegment]:
    """
    Extract vector line segments from the diagram.

    These represent taxiway and runway geometry.
    Thicker lines = runways, thinner lines = taxiways.
    """
    x_min, y_min, x_max, y_max = bounds
    paths = []

    # Get drawing commands from the page
    drawings = page.get_drawings()

    for drawing in drawings:
        # Process line segments
        if 'items' in drawing:
            for item in drawing['items']:
                if item[0] == 'l':  # Line segment
                    x0, y0 = item[1].x, item[1].y
                    x1, y1 = item[2].x, item[2].y

                    # Check if line is within diagram bounds
                    if (x_min < x0 < x_max and x_min < x1 < x_max and
                        y_min < y0 < y_max and y_min < y1 < y_max):

                        width = drawing.get('width', 1.0)
                        paths.append(PathSegment(
                            x0=x0, y0=y0, x1=x1, y1=y1, width=width
                        ))

    return paths


def extract_from_pdf(pdf_path: str) -> Optional[ExtractedDiagram]:
    """
    Extract all diagram data from an airport diagram PDF.
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        print(f"Error: File not found: {pdf_path}")
        return None

    # Parse airport code and cycle from filename
    filename = pdf_path.stem
    parts = filename.split('_')
    airport_code = parts[0] if len(parts) >= 1 else "UNKNOWN"
    cycle = parts[1] if len(parts) >= 2 else "UNKNOWN"

    print(f"Extracting from: {pdf_path.name}")

    try:
        doc = fitz.open(str(pdf_path))
        page = doc[0]

        # Get diagram bounds
        bounds = extract_diagram_bounds(page)
        print(f"  Page size: {page.rect.width:.0f} x {page.rect.height:.0f}")
        print(f"  Diagram bounds: ({bounds[0]:.0f}, {bounds[1]:.0f}) to ({bounds[2]:.0f}, {bounds[3]:.0f})")

        # Extract components
        taxiway_labels = extract_taxiway_labels(page, bounds)
        runway_info, raw_runway_text = extract_runway_info(page)
        paths = extract_vector_paths(page, bounds)

        # Store dimensions before closing
        page_width = page.rect.width
        page_height = page.rect.height

        doc.close()

        result = ExtractedDiagram(
            airport_code=airport_code,
            cycle=cycle,
            source_file=str(pdf_path),
            page_width=page_width,
            page_height=page_height,
            taxiway_labels=taxiway_labels,
            runway_info=runway_info,
            paths=paths,
            raw_runway_text=raw_runway_text
        )

        # Print summary
        print(f"  Taxiway labels: {len(result.taxiway_labels)}")
        print(f"  Runways found: {len(result.runway_info)}")
        print(f"  Vector paths: {len(result.paths)}")

        # Show unique taxiway designators found
        designators = sorted(set(t.designator for t in result.taxiway_labels))
        print(f"  Unique designators: {', '.join(designators)}")

        # Show runway dimensions
        if result.runway_info:
            print(f"  Runway dimensions:")
            for rwy in result.runway_info:
                print(f"    {rwy.designator}: {rwy.length_ft} x {rwy.width_ft} ft")

        return result

    except Exception as e:
        print(f"Error reading PDF: {e}")
        import traceback
        traceback.print_exc()
        return None


def to_dict(data: ExtractedDiagram) -> dict:
    """Convert ExtractedDiagram to dictionary for JSON serialization."""
    return {
        'airport_code': data.airport_code,
        'cycle': data.cycle,
        'source_file': data.source_file,
        'page_width': data.page_width,
        'page_height': data.page_height,
        'taxiway_labels': [asdict(t) for t in data.taxiway_labels],
        'runway_info': [asdict(r) for r in data.runway_info],
        'paths': [asdict(p) for p in data.paths],
        'raw_runway_text': data.raw_runway_text
    }


def save_extraction(data: ExtractedDiagram, output_path: str = None) -> str:
    """Save extracted data to a JSON file."""
    if output_path is None:
        data_dir = Path(__file__).parent.parent / "data"
        output_path = data_dir / f"{data.airport_code}_{data.cycle}_extracted.json"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(to_dict(data), f, indent=2)

    print(f"Saved extraction to: {output_path}")
    return str(output_path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        pdf_file = sys.argv[1]
    else:
        data_dir = Path(__file__).parent.parent / "data"
        pdf_files = list(data_dir.glob("JFK_*.pdf"))

        if not pdf_files:
            print("No JFK PDF found. Run downloader.py first.")
            exit(1)

        pdf_file = pdf_files[0]

    print(f"\nPDF Extractor Test")
    print("=" * 50)

    data = extract_from_pdf(pdf_file)
    if data:
        save_extraction(data)

        print(f"\nTaxiway labels found:")
        for label in sorted(data.taxiway_labels, key=lambda x: x.designator):
            print(f"  {label.designator:3} at ({label.x:.0f}, {label.y:.0f})")
