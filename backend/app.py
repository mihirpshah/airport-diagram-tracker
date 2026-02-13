"""
app.py - Flask web server for the Airport Diagram Change Tracker

This provides a REST API that the frontend can call to:
- List available airports
- Trigger PDF downloads
- Run extractions and comparisons
- Get comparison results as JSON

It also serves the frontend files (HTML, CSS, JS) and the PDF files
for side-by-side viewing.

Deployment: This app is designed to run on Render.com with gunicorn.
"""

import os
import json
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables from .env file (for local development)
load_dotenv()

# Import our modules - handle both direct execution and module import
try:
    from downloader import (
        AIRPORTS, download_airport_pair, download_diagram,
        get_current_cycle, get_previous_cycle
    )
    from pdf_extractor import extract_from_pdf, save_extraction, to_dict as extraction_to_dict
    from comparator import (
        compare_from_files, compare_extractions, save_comparison, to_dict as comparison_to_dict
    )
    from historical import get_historical_summary, find_last_change
except ImportError:
    from backend.downloader import (
        AIRPORTS, download_airport_pair, download_diagram,
        get_current_cycle, get_previous_cycle
    )
    from backend.pdf_extractor import extract_from_pdf, save_extraction, to_dict as extraction_to_dict
    from backend.comparator import (
        compare_from_files, compare_extractions, save_comparison, to_dict as comparison_to_dict
    )
    from backend.historical import get_historical_summary, find_last_change

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Allow frontend to call API from different port during development

# Paths - use environment variable for production, fallback to local for development
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = Path(os.environ.get('DATA_DIR', BASE_DIR / "data"))
FRONTEND_DIR = BASE_DIR / "frontend"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# API Endpoints
# =============================================================================

@app.route('/api/airports', methods=['GET'])
def list_airports():
    """
    GET /api/airports
    Returns list of configured airports with their FAA numbers.
    """
    airports = [
        {'code': code, 'faa_number': num, 'name': get_airport_name(code)}
        for code, num in AIRPORTS.items()
    ]
    return jsonify({
        'airports': airports,
        'current_cycle': get_current_cycle()
    })


@app.route('/api/cycles', methods=['GET'])
def get_cycles():
    """
    GET /api/cycles
    Returns current and previous AIRAC cycle codes.
    """
    current = get_current_cycle()
    previous = get_previous_cycle(current)
    return jsonify({
        'current': current,
        'previous': previous
    })


@app.route('/api/download/<airport_code>', methods=['POST'])
def download_airport(airport_code):
    """
    POST /api/download/<airport_code>
    Downloads current and previous cycle PDFs for the specified airport.
    """
    airport_code = airport_code.upper()

    if airport_code not in AIRPORTS:
        return jsonify({'error': f'Unknown airport: {airport_code}'}), 400

    current_path, previous_path = download_airport_pair(airport_code)

    return jsonify({
        'airport': airport_code,
        'current_pdf': str(current_path) if current_path else None,
        'previous_pdf': str(previous_path) if previous_path else None,
        'success': current_path is not None and previous_path is not None
    })


@app.route('/api/extract/<airport_code>', methods=['POST'])
def extract_airport(airport_code):
    """
    POST /api/extract/<airport_code>
    Extracts text from downloaded PDFs for the specified airport.
    """
    airport_code = airport_code.upper()
    cycle = request.args.get('cycle', get_current_cycle())

    # Find the PDF file
    pdf_path = DATA_DIR / f"{airport_code}_{cycle}.pdf"

    if not pdf_path.exists():
        return jsonify({'error': f'PDF not found: {pdf_path.name}'}), 404

    # Extract and save
    data = extract_from_pdf(str(pdf_path))
    if data is None:
        return jsonify({'error': 'Extraction failed'}), 500

    output_path = save_extraction(data)

    return jsonify({
        'airport': airport_code,
        'cycle': cycle,
        'output_file': output_path,
        'summary': {
            'taxiways': len(data.taxiways),
            'runways': len(data.runways),
            'frequencies': len(data.frequencies),
            'dimensions': len(data.dimensions),
            'notes': len(data.notes)
        }
    })


@app.route('/api/compare/<airport_code>', methods=['GET'])
def compare_airport(airport_code):
    """
    GET /api/compare/<airport_code>
    Returns comparison between current and previous cycle for an airport.
    Automatically downloads and extracts if needed.
    """
    airport_code = airport_code.upper()

    if airport_code not in AIRPORTS:
        return jsonify({'error': f'Unknown airport: {airport_code}'}), 400

    current_cycle = get_current_cycle()
    previous_cycle = get_previous_cycle(current_cycle)

    print(f"Comparing {airport_code}: {previous_cycle} -> {current_cycle}")
    print(f"DATA_DIR: {DATA_DIR}")

    # Check for existing comparison file first
    comparison_file = DATA_DIR / f"{airport_code}_comparison_{previous_cycle}_to_{current_cycle}.json"
    if comparison_file.exists():
        print(f"Using cached comparison: {comparison_file}")
        with open(comparison_file, 'r') as f:
            return jsonify(json.load(f))

    # Check for extraction files
    current_extract = DATA_DIR / f"{airport_code}_{current_cycle}_extracted.json"
    previous_extract = DATA_DIR / f"{airport_code}_{previous_cycle}_extracted.json"

    # Download PDFs if needed
    current_pdf = DATA_DIR / f"{airport_code}_{current_cycle}.pdf"
    previous_pdf = DATA_DIR / f"{airport_code}_{previous_cycle}.pdf"

    print(f"Current PDF exists: {current_pdf.exists()} - {current_pdf}")
    print(f"Previous PDF exists: {previous_pdf.exists()} - {previous_pdf}")

    if not current_pdf.exists() or not previous_pdf.exists():
        print(f"Downloading PDFs for {airport_code}...")
        download_airport_pair(airport_code)
        print(f"After download - Current: {current_pdf.exists()}, Previous: {previous_pdf.exists()}")

    # Extract if needed
    if not current_extract.exists():
        if current_pdf.exists():
            print(f"Extracting {current_pdf}...")
            data = extract_from_pdf(str(current_pdf))
            if data:
                save_extraction(data, str(current_extract))
                print(f"Saved extraction to {current_extract}")
            else:
                print(f"Extraction returned None for {current_pdf}")
        else:
            print(f"Cannot extract - PDF not found: {current_pdf}")

    if not previous_extract.exists():
        if previous_pdf.exists():
            print(f"Extracting {previous_pdf}...")
            data = extract_from_pdf(str(previous_pdf))
            if data:
                save_extraction(data, str(previous_extract))
                print(f"Saved extraction to {previous_extract}")
            else:
                print(f"Extraction returned None for {previous_pdf}")
        else:
            print(f"Cannot extract - PDF not found: {previous_pdf}")

    # Now compare
    print(f"Current extract exists: {current_extract.exists()}")
    print(f"Previous extract exists: {previous_extract.exists()}")

    if current_extract.exists() and previous_extract.exists():
        result = compare_from_files(str(previous_extract), str(current_extract))
        save_comparison(result)
        return jsonify(comparison_to_dict(result))
    else:
        return jsonify({
            'error': 'Could not extract PDF data',
            'current_extract_exists': current_extract.exists(),
            'previous_extract_exists': previous_extract.exists()
        }), 500


@app.route('/api/status/<airport_code>', methods=['GET'])
def airport_status(airport_code):
    """
    GET /api/status/<airport_code>
    Returns what files exist for this airport.
    """
    airport_code = airport_code.upper()
    current_cycle = get_current_cycle()
    previous_cycle = get_previous_cycle(current_cycle)

    return jsonify({
        'airport': airport_code,
        'current_cycle': current_cycle,
        'previous_cycle': previous_cycle,
        'files': {
            'current_pdf': (DATA_DIR / f"{airport_code}_{current_cycle}.pdf").exists(),
            'previous_pdf': (DATA_DIR / f"{airport_code}_{previous_cycle}.pdf").exists(),
            'current_extract': (DATA_DIR / f"{airport_code}_{current_cycle}_extracted.json").exists(),
            'previous_extract': (DATA_DIR / f"{airport_code}_{previous_cycle}_extracted.json").exists(),
            'comparison': (DATA_DIR / f"{airport_code}_comparison_{previous_cycle}_to_{current_cycle}.json").exists()
        }
    })


@app.route('/api/historical/<airport_code>', methods=['GET'])
def historical_analysis(airport_code):
    """
    GET /api/historical/<airport_code>
    Find the last cycle where a change occurred.
    Searches back up to 13 cycles (~1 year).
    """
    airport_code = airport_code.upper()

    if airport_code not in AIRPORTS:
        return jsonify({'error': f'Unknown airport: {airport_code}'}), 400

    # Get number of cycles to search (default 13 = ~1 year)
    max_cycles = request.args.get('max_cycles', 13, type=int)

    result = get_historical_summary(airport_code)
    return jsonify(result)


@app.route('/api/test-compare', methods=['GET'])
def test_comparison():
    """
    GET /api/test-compare
    Returns a test comparison using synthetic data to demonstrate change detection.
    Uses modified SYR data that shows:
    - Taxiway Y added
    - Taxiway Z removed
    - Runway 10/28 extended by 299 ft
    """
    # The test_old file is shipped with the repo (synthetic data)
    # Look in both DATA_DIR and the repo's data directory
    repo_data_dir = Path(__file__).parent.parent / "data"

    test_old = DATA_DIR / "SYR_2601_TEST_extracted.json"
    if not test_old.exists():
        test_old = repo_data_dir / "SYR_2601_TEST_extracted.json"

    test_new = DATA_DIR / "SYR_2602_extracted.json"

    if not test_old.exists():
        return jsonify({
            'error': 'Test data not found. The SYR_2601_TEST_extracted.json file is missing.',
            'instructions': 'This file should be included in the repository.'
        }), 404

    # Download and extract SYR_2602 if needed (on-demand)
    if not test_new.exists():
        current_cycle = get_current_cycle()
        syr_pdf = DATA_DIR / f"SYR_{current_cycle}.pdf"

        # Download the current SYR diagram
        if not syr_pdf.exists():
            download_diagram("SYR", current_cycle)

        # Extract it
        if syr_pdf.exists():
            data = extract_from_pdf(str(syr_pdf))
            if data:
                save_extraction(data, str(DATA_DIR / f"SYR_{current_cycle}_extracted.json"))
                test_new = DATA_DIR / f"SYR_{current_cycle}_extracted.json"

    if not test_new.exists():
        return jsonify({'error': 'Could not download/extract SYR diagram for comparison.'}), 500

    # Load and compare
    with open(test_old, 'r') as f:
        old_data = json.load(f)
    with open(test_new, 'r') as f:
        new_data = json.load(f)

    result = compare_extractions(old_data, new_data)
    result_dict = comparison_to_dict(result)

    # Add test metadata
    result_dict['test_mode'] = True
    result_dict['test_description'] = 'Synthetic test data showing taxiway and runway changes'
    result_dict['old_cycle'] = '2601_TEST'
    result_dict['new_cycle'] = get_current_cycle()

    return jsonify(result_dict)


# =============================================================================
# File Serving
# =============================================================================

@app.route('/pdf/<filename>')
def serve_pdf(filename):
    """
    Serve PDF files from the data directory.
    Downloads from FAA on-demand if not present.

    Expected filename format: AIRPORT_CYCLE.pdf (e.g., SYR_2602.pdf)
    """
    pdf_path = DATA_DIR / filename

    # If file doesn't exist, try to download it
    if not pdf_path.exists():
        # Parse airport code and cycle from filename
        # Format: AIRPORT_CYCLE.pdf
        try:
            name_part = filename.replace('.pdf', '').replace('.PDF', '')
            parts = name_part.split('_')
            if len(parts) >= 2:
                airport_code = parts[0].upper()
                cycle = parts[1]

                # Only download if it's a known airport
                if airport_code in AIRPORTS:
                    print(f"Downloading {airport_code} cycle {cycle} on demand...")
                    download_diagram(airport_code, cycle)
        except Exception as e:
            print(f"Error parsing/downloading PDF {filename}: {e}")

    # Try to serve the file
    if pdf_path.exists():
        return send_from_directory(DATA_DIR, filename)
    else:
        return jsonify({'error': f'PDF not found: {filename}'}), 404


@app.route('/')
def serve_index():
    """Serve the main frontend page."""
    return send_from_directory(FRONTEND_DIR, 'index.html')


@app.route('/<path:filename>')
def serve_static(filename):
    """Serve other frontend files (CSS, JS, etc.)."""
    return send_from_directory(FRONTEND_DIR, filename)


# =============================================================================
# Helper Functions
# =============================================================================

def get_airport_name(code):
    """Get full airport name from code."""
    names = {
        'JFK': 'John F. Kennedy International',
        'ORD': "O'Hare International (Chicago)",
        'LAX': 'Los Angeles International',
        'ATL': 'Hartsfield-Jackson Atlanta',
        'DFW': 'Dallas/Fort Worth International',
        'SFO': 'San Francisco International',
        'MIA': 'Miami International',
        'SYR': 'Syracuse Hancock International'
    }
    return names.get(code, code)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == '__main__':
    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Airport Diagram Change Tracker")
    print("=" * 60)
    print(f"Current AIRAC Cycle: {get_current_cycle()}")
    print(f"Data Directory: {DATA_DIR}")
    print(f"Frontend Directory: {FRONTEND_DIR}")
    print()
    print("Starting web server...")
    print("Open http://localhost:5000 in your browser")
    print("=" * 60)

    # Run the development server
    app.run(debug=True, host='0.0.0.0', port=5000)
