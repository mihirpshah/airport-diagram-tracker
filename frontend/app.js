/**
 * app.js - Frontend JavaScript for Airport Diagram Change Tracker
 *
 * Features:
 * - Loading airport list and cycle info from the API
 * - Triggering comparisons when an airport is selected
 * - Displaying change reports (taxiway additions/removals/renames)
 * - Rendering PDFs side-by-side with HIGHLIGHTED CHANGES
 */

// =============================================================================
// Configuration
// =============================================================================

const API_BASE = '';

pdfjsLib.GlobalWorkerOptions.workerSrc =
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

// Colors for different change types (with transparency for fills)
const CHANGE_COLORS = {
    'ADDED': { stroke: '#16a34a', fill: 'rgba(22, 163, 74, 0.25)' },      // Green
    'REMOVED': { stroke: '#dc2626', fill: 'rgba(220, 38, 38, 0.25)' },    // Red
    'RENAMED': { stroke: '#d97706', fill: 'rgba(217, 119, 6, 0.25)' },    // Orange
    'LENGTH_CHANGED': { stroke: '#7c3aed', fill: 'rgba(124, 58, 237, 0.25)' },  // Purple
    'WIDTH_CHANGED': { stroke: '#7c3aed', fill: 'rgba(124, 58, 237, 0.25)' }    // Purple
};

// =============================================================================
// State
// =============================================================================

let currentAirport = null;
let currentCycle = null;
let previousCycle = null;
let currentChanges = [];       // All taxiway changes from comparison
let currentRunwayChanges = []; // Runway changes
let lastChangeCycle = null;

// Store PDF metadata for coordinate mapping
let pdfMetadata = {
    pageWidth: 387,   // Default FAA diagram width in PDF points
    pageHeight: 594,  // Default FAA diagram height in PDF points
    scale: 1
};

// =============================================================================
// Initialization
// =============================================================================

document.addEventListener('DOMContentLoaded', () => {
    loadAirports();
    loadCycles();
});

async function loadAirports() {
    try {
        const response = await fetch(`${API_BASE}/api/airports`);
        const data = await response.json();

        const container = document.getElementById('airport-buttons');
        container.innerHTML = '';

        data.airports.forEach(airport => {
            const btn = document.createElement('button');
            btn.className = 'airport-btn';
            btn.textContent = airport.code;
            btn.title = airport.name;
            btn.onclick = () => selectAirport(airport.code);
            container.appendChild(btn);
        });
    } catch (error) {
        console.error('Failed to load airports:', error);
        document.getElementById('airport-buttons').innerHTML =
            '<p class="error-message">Failed to load airports. Is the server running?</p>';
    }
}

async function loadCycles() {
    try {
        const response = await fetch(`${API_BASE}/api/cycles`);
        const data = await response.json();

        currentCycle = data.current;
        previousCycle = data.previous;

        document.getElementById('current-cycle').textContent = currentCycle;
        document.getElementById('previous-cycle').textContent = previousCycle;
    } catch (error) {
        console.error('Failed to load cycles:', error);
    }
}

// =============================================================================
// Airport Selection and Comparison
// =============================================================================

async function selectAirport(code) {
    // Update button states
    document.querySelectorAll('.airport-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.textContent === code) {
            btn.classList.add('active', 'loading');
        }
    });
    document.getElementById('test-btn').classList.remove('active');

    currentAirport = code;

    // Show loading state
    document.getElementById('report-summary').innerHTML =
        '<p><span class="loading-spinner"></span> Analyzing diagrams...</p>';
    document.getElementById('report-details').innerHTML = '';

    try {
        const response = await fetch(`${API_BASE}/api/compare/${code}`);
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // Store changes for highlighting
        currentChanges = data.taxiway_changes || [];
        currentRunwayChanges = data.runway_changes || [];

        displayChangeReport(data);

        // Load PDFs with highlighting
        await loadPDFsWithHighlights(code, currentChanges, currentRunwayChanges);

        // Also fetch historical data
        loadHistoricalData(code);

    } catch (error) {
        console.error('Comparison failed:', error);
        document.getElementById('report-summary').innerHTML =
            `<p class="error-message">Failed to compare: ${error.message}</p>`;
    } finally {
        document.querySelectorAll('.airport-btn').forEach(btn => {
            btn.classList.remove('loading');
        });
    }
}

// =============================================================================
// Change Report Display
// =============================================================================

function displayChangeReport(data) {
    const summaryEl = document.getElementById('report-summary');
    const detailsEl = document.getElementById('report-details');

    const summary = data.summary;
    const runwayChangeCount = summary.runway_changes || 0;

    summaryEl.innerHTML = `
        <h3>${data.airport_code}: Cycle ${data.old_cycle} → ${data.new_cycle}</h3>
        <div class="summary-stats">
            <span class="stat info">
                ${summary.old_unique_designators} → ${summary.new_unique_designators} taxiway designators
            </span>
            <span class="stat added">+${summary.taxiways_added} Added</span>
            <span class="stat removed">-${summary.taxiways_removed} Removed</span>
            <span class="stat renamed">${summary.taxiways_renamed} Renamed</span>
            ${runwayChangeCount > 0 ? `<span class="stat runway">${runwayChangeCount} Runway</span>` : ''}
        </div>
    `;

    const taxiwayChanges = data.taxiway_changes || [];
    const runwayChanges = data.runway_changes || [];
    const geometryChanges = data.geometry_changes || [];

    if (taxiwayChanges.length === 0 && runwayChanges.length === 0 && geometryChanges.length === 0) {
        detailsEl.innerHTML = `
            <div class="no-changes">
                No changes detected between cycles.
                <p class="note">The diagrams appear identical for taxiway designators and runway dimensions.</p>
            </div>
        `;
        return;
    }

    let html = '';

    // Show taxiway changes
    taxiwayChanges.forEach(change => {
        html += `
            <div class="change-item ${change.change_type}">
                <span class="change-type">${change.change_type}</span>
                <span class="change-description">${change.description}</span>
            </div>
        `;
    });

    // Show runway changes
    runwayChanges.forEach(change => {
        html += `
            <div class="change-item ${change.change_type}">
                <span class="change-type">RUNWAY</span>
                <span class="change-description">${change.description}</span>
            </div>
        `;
    });

    // Show geometry changes
    geometryChanges.forEach(change => {
        html += `
            <div class="change-item GEOMETRY">
                <span class="change-type">GEOMETRY</span>
                <span class="change-description">${change.description}</span>
            </div>
        `;
    });

    detailsEl.innerHTML = html;
}

// =============================================================================
// Historical Data Loading
// =============================================================================

async function loadHistoricalData(airportCode) {
    document.getElementById('pdf-last-change-cycle').textContent = 'Searching...';
    document.getElementById('last-change-info').textContent = 'Analyzing historical cycles...';
    document.getElementById('last-change-info').className = 'pdf-info';

    try {
        const response = await fetch(`${API_BASE}/api/historical/${airportCode}`);
        const data = await response.json();

        if (data.error) {
            document.getElementById('pdf-last-change-cycle').textContent = 'Error';
            document.getElementById('last-change-info').textContent = data.error;
            return;
        }

        if (data.found && data.last_change_cycle) {
            lastChangeCycle = data.last_change_cycle;
            document.getElementById('pdf-last-change-cycle').textContent = lastChangeCycle;

            const added = data.taxiways_added || [];
            const removed = data.taxiways_removed || [];
            let infoText = `Changes since ${lastChangeCycle}: `;
            if (added.length > 0) {
                infoText += `+${added.join(', ')} `;
            }
            if (removed.length > 0) {
                infoText += `-${removed.join(', ')}`;
            }
            document.getElementById('last-change-info').textContent = infoText;
            document.getElementById('last-change-info').className = 'pdf-info has-changes';

            await renderPDF(`/pdf/${airportCode}_${lastChangeCycle}.pdf`, 'pdf-canvas-last-change');

        } else {
            lastChangeCycle = null;
            document.getElementById('pdf-last-change-cycle').textContent = 'None found';
            document.getElementById('last-change-info').textContent =
                data.message || `No changes in last ${data.cycles_searched || 13} cycles (~${(data.cycles_searched || 13) * 28} days)`;

            const canvas = document.getElementById('pdf-canvas-last-change');
            const ctx = canvas.getContext('2d');
            canvas.width = 300;
            canvas.height = 100;
            ctx.fillStyle = '#f0fdf4';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = '#16a34a';
            ctx.font = '14px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('No changes detected', canvas.width / 2, 40);
            ctx.fillText('in recent history', canvas.width / 2, 60);
        }

    } catch (error) {
        console.error('Historical analysis failed:', error);
        document.getElementById('pdf-last-change-cycle').textContent = 'Error';
        document.getElementById('last-change-info').textContent = `Failed: ${error.message}`;
    }
}

// =============================================================================
// PDF Display with Highlighting
// =============================================================================

async function loadPDFsWithHighlights(airportCode, taxiwayChanges, runwayChanges) {
    document.getElementById('pdf-old-cycle').textContent = previousCycle;
    document.getElementById('pdf-new-cycle').textContent = currentCycle;

    // Render PDFs
    const [oldMeta, newMeta] = await Promise.all([
        renderPDF(`/pdf/${airportCode}_${previousCycle}.pdf`, 'pdf-canvas-old'),
        renderPDF(`/pdf/${airportCode}_${currentCycle}.pdf`, 'pdf-canvas-new')
    ]);

    // Draw highlights on the OLD diagram (for REMOVED items - they existed in old)
    // Also show runway changes on both diagrams
    if (oldMeta) {
        const removedChanges = taxiwayChanges.filter(c => c.change_type === 'REMOVED');
        drawHighlights('pdf-canvas-old', removedChanges, oldMeta, 'old', runwayChanges);
    }

    // Draw highlights on the NEW diagram (for ADDED items - they exist in new)
    if (newMeta) {
        const addedChanges = taxiwayChanges.filter(c => c.change_type === 'ADDED');
        drawHighlights('pdf-canvas-new', addedChanges, newMeta, 'new', runwayChanges);
    }
}

async function renderPDF(url, canvasId) {
    const canvas = document.getElementById(canvasId);
    const ctx = canvas.getContext('2d');

    try {
        const pdf = await pdfjsLib.getDocument(url).promise;
        const page = await pdf.getPage(1);

        const containerWidth = canvas.parentElement.clientWidth - 10;
        const viewport = page.getViewport({ scale: 1 });
        const scale = containerWidth / viewport.width;
        const scaledViewport = page.getViewport({ scale });

        canvas.width = scaledViewport.width;
        canvas.height = scaledViewport.height;

        await page.render({
            canvasContext: ctx,
            viewport: scaledViewport
        }).promise;

        // Return metadata for highlight coordinate mapping
        return {
            pageWidth: viewport.width,
            pageHeight: viewport.height,
            canvasWidth: scaledViewport.width,
            canvasHeight: scaledViewport.height,
            scale: scale
        };

    } catch (error) {
        console.error(`Failed to render PDF ${url}:`, error);
        canvas.width = 300;
        canvas.height = 100;
        ctx.fillStyle = '#fee2e2';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#dc2626';
        ctx.font = '14px sans-serif';
        ctx.fillText('PDF not available', 20, 50);
        return null;
    }
}

/**
 * Draw highlight circles/boxes on the PDF canvas at change locations
 *
 * @param {string} canvasId - ID of the canvas element
 * @param {Array} changes - Array of change objects with x, y coordinates
 * @param {Object} meta - PDF metadata with scale info
 * @param {string} whichDiagram - 'old' or 'new' to determine coordinate source
 * @param {Array} runwayChanges - Optional array of runway change objects
 */
function drawHighlights(canvasId, changes, meta, whichDiagram, runwayChanges = []) {
    const canvas = document.getElementById(canvasId);
    const ctx = canvas.getContext('2d');

    // Draw taxiway highlights
    if (changes && changes.length > 0) {
        changes.forEach(change => {
            // Get coordinates - taxiway changes have x, y from extraction
            let x = change.x || 0;
            let y = change.y || 0;

            // Skip if no valid coordinates
            if (x === 0 && y === 0) return;

            // Scale coordinates from PDF points to canvas pixels
            const canvasX = x * meta.scale;
            const canvasY = y * meta.scale;

            // Get color based on change type
            const colors = CHANGE_COLORS[change.change_type] || CHANGE_COLORS['ADDED'];

            // Draw a highlighted circle around the taxiway label
            const radius = 15 * meta.scale;

            // Draw filled circle with transparency
            ctx.beginPath();
            ctx.arc(canvasX, canvasY, radius, 0, 2 * Math.PI);
            ctx.fillStyle = colors.fill;
            ctx.fill();

            // Draw circle border
            ctx.strokeStyle = colors.stroke;
            ctx.lineWidth = 3;
            ctx.stroke();

            // Draw the designator label above the circle
            ctx.font = `bold ${12 * meta.scale}px sans-serif`;
            ctx.fillStyle = colors.stroke;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';

            const label = change.designator || change.change_type;
            const labelY = canvasY - radius - 5;

            // Draw label background
            const textWidth = ctx.measureText(label).width;
            ctx.fillStyle = 'white';
            ctx.fillRect(canvasX - textWidth/2 - 3, labelY - 14, textWidth + 6, 16);

            // Draw label text
            ctx.fillStyle = colors.stroke;
            ctx.fillText(label, canvasX, labelY);
        });
    }

    // Draw runway change highlights at the dimension text positions (on the diagram, not in margins)
    if (runwayChanges && runwayChanges.length > 0) {
        runwayChanges.forEach(change => {
            // Get the appropriate x,y based on which diagram we're drawing on
            // old diagram uses old_x/old_y, new diagram uses new_x/new_y
            let x, y;
            if (whichDiagram === 'old') {
                x = change.old_x || 0;
                y = change.old_y || 0;
            } else {
                x = change.new_x || 0;
                y = change.new_y || 0;
            }

            // Skip if no valid coordinates
            if (x === 0 && y === 0) return;

            // Scale coordinates from PDF points to canvas pixels
            const canvasX = x * meta.scale;
            const canvasY = y * meta.scale;

            // Get color based on change type (purple for runway changes)
            const colors = CHANGE_COLORS[change.change_type] || CHANGE_COLORS['LENGTH_CHANGED'];

            // Draw a highlighted rectangle around the dimension text
            // Runway dimension text is wider than taxiway labels
            const rectWidth = 80 * meta.scale;
            const rectHeight = 20 * meta.scale;

            // Draw filled rectangle with transparency
            ctx.fillStyle = colors.fill;
            ctx.fillRect(canvasX - rectWidth/2, canvasY - rectHeight/2, rectWidth, rectHeight);

            // Draw rectangle border
            ctx.strokeStyle = colors.stroke;
            ctx.lineWidth = 3;
            ctx.strokeRect(canvasX - rectWidth/2, canvasY - rectHeight/2, rectWidth, rectHeight);

            // Draw a label above the highlight showing what changed
            ctx.font = `bold ${10 * meta.scale}px sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';

            // Build the label text
            let label = change.designator || 'RWY';
            if (change.change_type === 'LENGTH_CHANGED') {
                if (whichDiagram === 'old') {
                    label = `${change.old_length} ft`;
                } else {
                    label = `${change.old_length}→${change.new_length} ft`;
                }
            } else if (change.change_type === 'WIDTH_CHANGED') {
                if (whichDiagram === 'old') {
                    label = `${change.old_width} ft wide`;
                } else {
                    label = `${change.old_width}→${change.new_width} ft`;
                }
            }

            const labelY = canvasY - rectHeight/2 - 5;

            // Draw label background
            const textWidth = ctx.measureText(label).width;
            ctx.fillStyle = 'white';
            ctx.fillRect(canvasX - textWidth/2 - 3, labelY - 12, textWidth + 6, 14);

            // Draw label text
            ctx.fillStyle = colors.stroke;
            ctx.fillText(label, canvasX, labelY);
        });
    }

    // Draw a legend in the corner if there are highlights
    if ((changes && changes.length > 0) || (runwayChanges && runwayChanges.length > 0)) {
        drawLegend(ctx, changes || [], meta, runwayChanges);
    }
}

// drawRunwayChangePanel removed - runway highlights now drawn directly on the diagram
// at the actual dimension text positions using drawHighlights()

/**
 * Draw a legend showing what the highlight colors mean
 */
function drawLegend(ctx, changes, meta, runwayChanges = []) {
    const changeTypes = [...new Set(changes.map(c => c.change_type))];

    // Add runway change types if present
    const runwayTypes = [...new Set(runwayChanges.map(c => c.change_type))];

    const allTypes = [...changeTypes, ...runwayTypes];
    if (allTypes.length === 0) return;

    const legendX = 10;
    const legendY = 10;
    const lineHeight = 20;

    // Draw legend background
    ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
    ctx.fillRect(legendX, legendY, 140, allTypes.length * lineHeight + 10);
    ctx.strokeStyle = '#ccc';
    ctx.lineWidth = 1;
    ctx.strokeRect(legendX, legendY, 140, allTypes.length * lineHeight + 10);

    allTypes.forEach((type, index) => {
        const colors = CHANGE_COLORS[type] || CHANGE_COLORS['ADDED'];
        const y = legendY + 15 + index * lineHeight;

        // Draw color circle
        ctx.beginPath();
        ctx.arc(legendX + 15, y, 6, 0, 2 * Math.PI);
        ctx.fillStyle = colors.fill;
        ctx.fill();
        ctx.strokeStyle = colors.stroke;
        ctx.lineWidth = 2;
        ctx.stroke();

        // Draw label - format nicely
        ctx.fillStyle = '#333';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';

        // Make labels more readable
        let label = type;
        if (type === 'LENGTH_CHANGED') label = 'RWY LENGTH';
        else if (type === 'WIDTH_CHANGED') label = 'RWY WIDTH';
        else if (type === 'RUNWAY_ADDED') label = 'RWY ADDED';
        else if (type === 'RUNWAY_REMOVED') label = 'RWY REMOVED';

        ctx.fillText(label, legendX + 30, y);
    });
}

// =============================================================================
// Test Mode - Load synthetic comparison data with highlights
// =============================================================================

async function loadTestComparison() {
    // Update button states
    document.querySelectorAll('.airport-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.getElementById('test-btn').classList.add('active');

    currentAirport = 'TEST';

    document.getElementById('report-summary').innerHTML =
        '<p><span class="loading-spinner"></span> Loading test data...</p>';
    document.getElementById('report-details').innerHTML = '';

    try {
        const response = await fetch(`${API_BASE}/api/test-compare`);
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // Store changes for highlighting
        currentChanges = data.taxiway_changes || [];
        currentRunwayChanges = data.runway_changes || [];

        // Display the comparison
        displayChangeReport(data);

        // Add test mode banner
        const summaryEl = document.getElementById('report-summary');
        summaryEl.innerHTML = `
            <div class="test-mode-banner">TEST MODE - Synthetic Data</div>
            ${summaryEl.innerHTML}
            <p class="test-description">${data.test_description || 'Demonstrating change detection with simulated taxiway and runway changes'}</p>
        `;

        // Load SYR PDFs with highlights
        // Use previous cycle for "old" (real PDF) and current cycle for "new"
        // The test compares synthetic 2601_TEST data against real current cycle
        const testOldCycle = previousCycle || '2601';
        const testNewCycle = data.new_cycle || currentCycle || '2602';

        document.getElementById('pdf-old-cycle').textContent = `${testOldCycle} (TEST data)`;
        document.getElementById('pdf-new-cycle').textContent = testNewCycle;

        const [oldMeta, newMeta] = await Promise.all([
            renderPDF(`/pdf/SYR_${testOldCycle}.pdf`, 'pdf-canvas-old'),
            renderPDF(`/pdf/SYR_${testNewCycle}.pdf`, 'pdf-canvas-new')
        ]);

        // Draw highlights - REMOVED on old diagram, ADDED on new diagram
        // Include runway changes on both diagrams
        if (oldMeta) {
            const removedChanges = currentChanges.filter(c => c.change_type === 'REMOVED');
            drawHighlights('pdf-canvas-old', removedChanges, oldMeta, 'old', currentRunwayChanges);
        }

        if (newMeta) {
            const addedChanges = currentChanges.filter(c => c.change_type === 'ADDED');
            drawHighlights('pdf-canvas-new', addedChanges, newMeta, 'new', currentRunwayChanges);
        }

        // Show test info in last-change panel
        document.getElementById('pdf-last-change-cycle').textContent = 'N/A';
        document.getElementById('last-change-info').textContent = 'Test mode - highlights shown on PDFs';
        document.getElementById('last-change-info').className = 'pdf-info';

        // Draw test indicator on last-change canvas
        const canvas = document.getElementById('pdf-canvas-last-change');
        const ctx = canvas.getContext('2d');
        canvas.width = 300;
        canvas.height = 150;
        ctx.fillStyle = '#fef3c7';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#d97706';
        ctx.font = 'bold 16px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('TEST MODE', canvas.width / 2, 40);
        ctx.font = '12px sans-serif';
        ctx.fillStyle = '#92400e';
        ctx.fillText('Synthetic changes:', canvas.width / 2, 70);
        ctx.fillText('+ Taxiway Y (green)', canvas.width / 2, 90);
        ctx.fillText('- Taxiway Z (red)', canvas.width / 2, 110);
        ctx.fillText('RWY 10/28: 7200→7499 ft (purple)', canvas.width / 2, 130);

    } catch (error) {
        console.error('Test comparison failed:', error);
        document.getElementById('report-summary').innerHTML =
            `<p class="error-message">Failed to load test data: ${error.message}</p>`;
    } finally {
        document.getElementById('test-btn').classList.remove('loading');
    }
}
