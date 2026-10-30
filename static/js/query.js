// Query Editor Utility Class
class QueryEditor {
    constructor(connectionManager) {
        this.connectionManager = connectionManager;
        this.jsonDataStore = new Map(); // Store JSON data by ID
        this.jsonIdCounter = 0;
        // Don't initialize anything - tabs handle their own editors now
    }

    // executeQuery is now handled by TabManager per tab

    displayResults(result) {
        const resultsGrid = document.getElementById('results-grid');
        const resultsInfo = document.getElementById('results-info');

        // Clear previous JSON data
        this.jsonDataStore.clear();
        this.jsonIdCounter = 0;

        if (!result.columns || result.columns.length === 0) {
            resultsGrid.innerHTML = '<div style="padding: 20px; text-align: center;">Query executed. No results to display.</div>';
            resultsInfo.textContent = `${result.row_count} row(s) affected`;
            return;
        }

        resultsInfo.textContent = `${result.row_count} row(s) returned`;

        // Create table
        let html = '<table class="data-table">';

        // Header with resize handles
        html += '<thead><tr>';
        result.columns.forEach(col => {
            html += `<th>
                <span class="th-content">${col}</span>
                <div class="resize-handle"></div>
            </th>`;
        });
        html += '</tr></thead>';

        // Body
        html += '<tbody>';
        result.rows.forEach(row => {
            html += '<tr>';
            result.columns.forEach(col => {
                const value = row[col];
                // Check for null, undefined, or empty string
                if (value === null || value === undefined || value === '') {
                    html += '<td class="null">NULL</td>';
                } else {
                    html += `<td>${this.formatCellValue(value)}</td>`;
                }
            });
            html += '</tr>';
        });
        html += '</tbody>';

        html += '</table>';

        resultsGrid.innerHTML = html;

        // Add click listeners for JSON cells
        this.attachJsonCellListeners();

        // Add resize functionality to table columns
        this.makeColumnsResizable(resultsGrid.querySelector('.data-table'));

        // Store results for export
        this.lastResults = result;
    }

    makeColumnsResizable(table) {
        if (!table) return;

        const headers = table.querySelectorAll('th');
        let currentResizing = null;

        // Start every column at the width its content needs (the table is laid out automatically), so a short
        // column stays short; dragging a handle then makes it wider or narrower from there

        headers.forEach((header, index) => {
            const resizeHandle = header.querySelector('.resize-handle');
            if (!resizeHandle) return;

            header.style.width = Math.max(56, header.offsetWidth) + 'px';
            header.style.minWidth = '56px';

            resizeHandle.addEventListener('mousedown', (e) => {
                e.preventDefault();
                e.stopPropagation();

                const startX = e.clientX;
                const startWidth = header.offsetWidth;

                // Add visual feedback
                header.classList.add('resizing');
                document.body.classList.add('col-resizing');

                currentResizing = {
                    header,
                    startX,
                    startWidth
                };

                const mouseMoveHandler = (e) => {
                    if (!currentResizing) return;

                    const diff = e.clientX - currentResizing.startX;
                    const newWidth = Math.max(80, currentResizing.startWidth + diff);

                    currentResizing.header.style.width = newWidth + 'px';
                };

                const mouseUpHandler = () => {
                    if (!currentResizing) return;

                    // Remove visual feedback
                    currentResizing.header.classList.remove('resizing');
                    document.body.classList.remove('col-resizing');

                    currentResizing = null;

                    // Remove handlers
                    document.removeEventListener('mousemove', mouseMoveHandler);
                    document.removeEventListener('mouseup', mouseUpHandler);
                };

                document.addEventListener('mousemove', mouseMoveHandler);
                document.addEventListener('mouseup', mouseUpHandler);
            });
        });
    }

    attachJsonCellListeners() {
        document.querySelectorAll('.json-cell').forEach(cell => {
            cell.addEventListener('click', (e) => {
                const jsonId = e.currentTarget.getAttribute('data-json-id');
                const jsonData = this.jsonDataStore.get(jsonId);
                if (jsonData) {
                    this.showJsonModal(jsonData);
                }
            });
        });
    }

    showJsonModal(jsonStr) {
        // Create modal if it doesn't exist
        let modal = document.getElementById('json-viewer-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'json-viewer-modal';
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content" style="max-width: 900px;">
                    <div class="modal-header">
                        <h3>JSON Editor</h3>
                        <div style="display: flex; gap: 10px; align-items: center;">
                            <input type="text" id="json-search-input" placeholder="Search..." class="form-control" style="flex: 1;">
                            <button class="btn btn-sm" id="format-json-btn">✨ Format</button>
                            <button class="btn btn-sm" id="copy-json-btn">📋 Copy</button>
                            <button class="btn btn-sm btn-primary" id="save-json-btn">💾 Save</button>
                            <span class="modal-close" id="json-modal-close">×</span>
                        </div>
                    </div>
                    <div class="modal-body">
                        <textarea id="json-editor" style="width: 100%; height: 60vh; background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 4px; padding: 15px; color: #ddd; font-family: 'SF Mono', 'Consolas', 'Monaco', monospace; font-size: 13px; line-height: 1.5; resize: vertical;"></textarea>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            // Close button
            modal.querySelector('#json-modal-close').addEventListener('click', () => {
                modal.classList.remove('active');
            });

            // Copy button
            modal.querySelector('#copy-json-btn').addEventListener('click', () => {
                const content = modal.querySelector('#json-editor').value;
                navigator.clipboard.writeText(content).then(() => {
                    const btn = modal.querySelector('#copy-json-btn');
                    const originalText = btn.textContent;
                    btn.textContent = '✓ Copied!';
                    btn.style.backgroundColor = '#28a745';
                    setTimeout(() => {
                        btn.textContent = originalText;
                        btn.style.backgroundColor = '';
                    }, 2000);
                });
            });

            // Format button
            modal.querySelector('#format-json-btn').addEventListener('click', () => {
                const editor = modal.querySelector('#json-editor');
                try {
                    const parsed = JSON.parse(editor.value);
                    editor.value = JSON.stringify(parsed, null, 2);
                } catch (e) {
                    ui.notify('Invalid JSON: ' + e.message);
                }
            });

            // Save button (placeholder - will be overridden)
            modal.querySelector('#save-json-btn').addEventListener('click', () => {
                ui.notify('JSON saved to clipboard. Close and paste to update the cell.');
                const content = modal.querySelector('#json-editor').value;
                navigator.clipboard.writeText(content);
            });

            // Search functionality
            let searchTimeout;
            modal.querySelector('#json-search-input').addEventListener('input', (e) => {
                const searchTerm = e.target.value.toLowerCase();
                const editor = modal.querySelector('#json-editor');

                // Clear previous timeout
                clearTimeout(searchTimeout);

                if (!searchTerm) {
                    // Clear selection
                    return;
                }

                // Debounce search to avoid interrupting typing
                searchTimeout = setTimeout(() => {
                    const text = editor.value;
                    const index = text.toLowerCase().indexOf(searchTerm);

                    if (index !== -1) {
                        // Calculate line number and scroll
                        const beforeText = text.substring(0, index);
                        const lines = beforeText.split('\n').length;
                        const lineHeight = 20; // approximate

                        // Store current focus
                        const activeElement = document.activeElement;

                        // Scroll and select
                        editor.scrollTop = (lines - 1) * lineHeight;
                        editor.setSelectionRange(index, index + searchTerm.length);

                        // Restore focus to search input if it was focused
                        if (activeElement === e.target) {
                            e.target.focus();
                        }
                    }
                }, 300); // Wait 300ms after user stops typing
            });

            // Close on background click
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.classList.remove('active');
                }
            });

            // Keyboard shortcuts for JSON editor
            modal.addEventListener('keydown', (e) => {
                // Cmd/Ctrl + S to save
                if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                    e.preventDefault();
                    modal.querySelector('#save-json-btn').click();
                }
                // Cmd/Ctrl + F to focus search
                else if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
                    e.preventDefault();
                    modal.querySelector('#json-search-input').focus();
                }
                // Esc to close
                else if (e.key === 'Escape') {
                    modal.classList.remove('active');
                }
            });
        }

        // Set content in editor
        const jsonEditor = modal.querySelector('#json-editor');
        try {
            const parsed = JSON.parse(jsonStr);
            jsonEditor.value = JSON.stringify(parsed, null, 2);
        } catch (e) {
            jsonEditor.value = jsonStr;
        }

        // Show modal
        modal.classList.add('active');
    }

    syntaxHighlightJson(json) {
        // Add syntax highlighting to JSON
        json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, (match) => {
            let cls = 'number';
            if (/^"/.test(match)) {
                if (/:$/.test(match)) {
                    cls = 'key';
                } else {
                    cls = 'string';
                }
            } else if (/true|false/.test(match)) {
                cls = 'boolean';
            } else if (/null/.test(match)) {
                cls = 'null';
            }
            return '<span class="json-' + cls + '">' + match + '</span>';
        });
    }

    // displayError is now handled by TabManager per tab

    // These methods are now handled by TabManager

    exportResults(format) {
        if (!this.lastResults || !this.lastResults.rows || this.lastResults.rows.length === 0) {
            ui.notify('No results to export');
            return;
        }

        let content, filename, mimeType;

        if (format === 'csv') {
            content = this.resultsToCSV(this.lastResults);
            filename = 'query_results.csv';
            mimeType = 'text/csv';
        } else if (format === 'json') {
            content = JSON.stringify(this.lastResults.rows, null, 2);
            filename = 'query_results.json';
            mimeType = 'application/json';
        }

        // Create download link
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    resultsToCSV(result) {
        let csv = '';

        // Header
        csv += result.columns.map(col => `"${col}"`).join(',') + '\n';

        // Rows
        result.rows.forEach(row => {
            const values = result.columns.map(col => {
                const value = row[col];
                if (value === null || value === undefined) {
                    return '';
                }
                // Handle objects by converting to JSON
                const strValue = typeof value === 'object' ? JSON.stringify(value) : String(value);
                return `"${strValue.replace(/"/g, '""')}"`;
            });
            csv += values.join(',') + '\n';
        });

        return csv;
    }

    // loadDatabases, clearDatabases, showMessage handled by TabManager

    formatCellValue(value) {
        // Handle objects (JSON data)
        if (typeof value === 'object' && value !== null) {
            const jsonStr = JSON.stringify(value, null, 2);
            const compactJson = JSON.stringify(value);

            // Store JSON data with unique ID
            const jsonId = `json-${this.jsonIdCounter++}`;
            this.jsonDataStore.set(jsonId, jsonStr);

            // Create a clickable element to view full JSON
            const preview = compactJson.length > 50
                ? this.escapeHtml(compactJson.substring(0, 50)) + '...'
                : this.escapeHtml(compactJson);

            return `<span class="json-cell" data-json-id="${jsonId}">
                        <span class="json-preview">${preview}</span>
                        <span class="json-icon">🔍</span>
                    </span>`;
        }
        // Handle regular values
        return this.escapeHtml(String(value));
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}
