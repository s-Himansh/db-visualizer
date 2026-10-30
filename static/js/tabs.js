// Tab Management System

class TabManager {
    constructor() {
        this.tabs = new Map();              // tabId → Tab object
        this.tabsByConnection = new Map();   // connectionId → Set of tabIds
        this.activeTabId = null;            // Currently visible tab
        this.activeTabByConnection = new Map(); // connectionId → last active tabId
        this.tabIdCounter = 0;              // Counter for generating unique tab IDs
        this.saveTimeout = null;            // Debounce timeout for localStorage saves
        this.SAVE_DELAY = 500;              // ms to wait before saving
        this.SESSION_KEY = 'db_visualizer_session';
        this.HISTORY_KEY = 'db_visualizer_query_history';
        this.jsonDataStore = new Map();     // Store JSON data for table tabs
        this.jsonIdCounter = 0;             // Counter for JSON IDs

        this.init();
        this.setupGlobalKeyboardShortcuts();
    }

    init() {
        // Initialize tab event listeners
        this.attachGlobalListeners();
    }

    attachGlobalListeners() {
        // New query tab button
        const newTabBtn = document.getElementById('new-query-tab-btn');
        if (newTabBtn) {
            newTabBtn.addEventListener('click', () => {
                const activeConn = window.app.connectionManager.getActiveConnection();
                if (activeConn) {
                    this.createTab('query', activeConn.id, { query: '' });
                } else {
                    ui.notify('Please connect to a database first');
                }
            });
        }

        // Tab header click delegation for tab switching and closing
        const tabsHeader = document.getElementById('tabs-header');
        if (tabsHeader) {
            tabsHeader.addEventListener('click', (e) => {
                const tabElement = e.target.closest('.tab');
                const closeButton = e.target.closest('.tab-close');

                if (closeButton) {
                    // Close tab
                    e.stopPropagation();
                    const tabId = closeButton.getAttribute('data-tab-id');
                    this.closeTab(tabId);
                } else if (tabElement) {
                    // Switch tab
                    const tabId = tabElement.getAttribute('data-tab-id');
                    this.switchTab(tabId);
                }
            });
        }
    }

    /**
     * Create a new tab
     * @param {string} type - 'query' | 'table' | 'schema'
     * @param {string} connectionId - ID of the connection this tab belongs to
     * @param {object} initialState - Initial state for the tab
     * @returns {string} The created tab ID
     */
    createTab(type, connectionId, initialState = {}) {
        const tabId = `tab_${this.tabIdCounter++}`;

        // Generate tab title
        let title = '';
        if (type === 'query') {
            const queryNum = this.getTabsByConnection(connectionId).filter(t => t.type === 'query').length + 1;
            title = `Query ${queryNum}`;
        } else if (type === 'table') {
            title = initialState.tableName || 'Table';
            if (initialState.filter) {
                const v = String(initialState.filter.value);
                title += ` · ${initialState.filter.column} = ${v.length > 14 ? v.slice(0, 13) + '…' : v}`;
            }
        } else if (type === 'map') {
            title = 'Schema map';
        } else if (type === 'schema') {
            title = initialState.tableName ? `${initialState.tableName} Schema` : 'Schema';
        }

        // Create tab object
        const tab = {
            id: tabId,
            type: type,
            title: title,
            connectionId: connectionId,
            state: initialState
        };


        // Store tab
        this.tabs.set(tabId, tab);

        // Add to connection mapping
        if (!this.tabsByConnection.has(connectionId)) {
            this.tabsByConnection.set(connectionId, new Set());
        }
        this.tabsByConnection.get(connectionId).add(tabId);

        // Render tab in UI
        this.renderTab(tab);

        // Switch to the new tab
        this.switchTab(tabId);

        // Save to localStorage
        this.persistToStorage();

        return tabId;
    }

    /**
     * Close and remove a tab
     * @param {string} tabId - ID of tab to close
     */
    hasUnsavedChanges(tab) {
        const grid = document.getElementById(`table-data-grid-${tab.id}`);
        return !!(grid && grid.querySelector('td.modified, tr.new-row'));
    }

    // True when it is safe to leave the current table state: nothing is pending, or the user agreed to lose it
    async guardUnsaved(tab, action) {
        if (!this.hasUnsavedChanges(tab)) return true;
        return ui.confirm(`This table has unsaved changes. If you ${action}, they are lost.`,
            { title: 'Unsaved changes', confirmLabel: 'Discard changes', danger: true });
    }

    async closeTab(tabId) {
        const tab = this.tabs.get(tabId);
        if (tab && tab.type === 'table' && !(await this.guardUnsaved(tab, 'close this tab'))) return;
        this.closeTabNow(tabId);
    }

    closeTabNow(tabId) {
        const tab = this.tabs.get(tabId);
        if (!tab) return;

        // Remove from connection mapping
        const connectionTabs = this.tabsByConnection.get(tab.connectionId);
        if (connectionTabs) {
            connectionTabs.delete(tabId);
        }

        // Remove from tabs map
        this.tabs.delete(tabId);

        // Remove DOM elements
        const tabElement = document.querySelector(`[data-tab-id="${tabId}"]`);
        if (tabElement) {
            tabElement.remove();
        }

        const contentElement = document.querySelector(`[data-content-for="${tabId}"]`);
        if (contentElement) {
            contentElement.remove();
        }

        // If this was the active tab, switch to another tab
        if (this.activeTabId === tabId) {
            const remainingTabs = this.getTabsByConnection(tab.connectionId);
            if (remainingTabs.length > 0) {
                this.switchTab(remainingTabs[0].id);
            } else {
                // No tabs left for this connection, create a default query tab
                this.createTab('query', tab.connectionId, { query: '' });
            }
        }

        // Save to localStorage
        this.persistToStorage();
    }

    /**
     * Switch to a different tab
     * @param {string} tabId - ID of tab to switch to
     */
    switchTab(tabId) {
        if (!this.tabs.has(tabId)) return;

        const tab = this.tabs.get(tabId);

        // Update UI - remove active class from all tabs
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));

        // Add active class to clicked tab
        const tabElement = document.querySelector(`[data-tab-id="${tabId}"]`);
        if (tabElement) {
            tabElement.classList.add('active');
        }

        // Hide all content areas
        document.querySelectorAll('.tab-content').forEach(c => { c.style.display = 'none'; c.classList.remove('active'); });

        // Show content for this tab (or create it if doesn't exist)
        let contentElement = document.querySelector(`[data-content-for="${tabId}"]`);
        if (!contentElement) {
            contentElement = this.createTabContent(tab);
        }

        if (contentElement) {
            contentElement.style.display = 'flex';
            contentElement.classList.add('active');
        }

        this.activeTabId = tabId;

        // Remember this as the active tab for this connection
        this.activeTabByConnection.set(tab.connectionId, tabId);

        // Save active tab for this connection
        this.persistToStorage();
    }

    /**
     * Render a tab in the tab bar
     * @param {object} tab - Tab object to render
     */
    renderTab(tab) {
        const tabsHeader = document.getElementById('tabs-header');
        if (!tabsHeader) return;

        // Create tab element
        const tabElement = document.createElement('div');
        tabElement.className = 'tab';
        tabElement.setAttribute('data-tab-id', tab.id);
        tabElement.setAttribute('data-tab-type', tab.type);

        // Tab icon based on type
        const iconSpan = document.createElement('span');
        iconSpan.className = `tab-icon tab-icon-${tab.type}`;

        // Tab label
        const labelSpan = document.createElement('span');
        labelSpan.className = 'tab-label';
        labelSpan.textContent = tab.title;

        // Close button
        const closeSpan = document.createElement('span');
        closeSpan.className = 'tab-close';
        closeSpan.textContent = '×';
        closeSpan.setAttribute('data-tab-id', tab.id);

        tabElement.appendChild(iconSpan);
        tabElement.appendChild(labelSpan);
        tabElement.appendChild(closeSpan);

        // Insert before the "new tab" button
        tabsHeader.appendChild(tabElement);
    }

    /**
     * Create content area for a tab
     * @param {object} tab - Tab object
     * @returns {HTMLElement} The created content element
     */
    createTabContent(tab) {
        const contentElement = document.createElement('div');
        contentElement.className = 'tab-content';
        contentElement.setAttribute('data-content-for', tab.id);
        contentElement.style.display = 'none';

        if (tab.type === 'query') {
            // Get connection type for database-specific UI
            const connection = window.app.connectionManager.connections.find(c => c.id === tab.connectionId);
            const dbType = connection ? connection.type : 'postgresql';

            // Database-specific button labels
            let executeLabel = 'Run';
            if (dbType === 'redis') {
                executeLabel = 'Run';
            } else if (dbType === 'mongodb') {
                executeLabel = 'Find';
            }

            // Create query editor content
            contentElement.innerHTML = `
                <div class="query-editor-container">
                    <div class="query-editor-toolbar">
                        <select class="database-selector" data-tab-id="${tab.id}">
                            <option value="">Select Database</option>
                        </select>
                        <button type="button" class="btn btn-primary" data-tab-id="${tab.id}" data-action="execute" title="Execute query (Cmd+Enter). Runs selected text if any, otherwise runs entire query.">${executeLabel}</button>
                        ${ColumnInsights.supported(dbType) ? `<button type="button" class="btn" data-tab-id="${tab.id}" data-action="ask" title="Describe what you want and get SQL (optional, uses the Anthropic API)">Ask</button>` : ''}
                        <button type="button" class="btn" data-tab-id="${tab.id}" data-action="clear">Clear</button>
                        <button type="button" class="btn" data-tab-id="${tab.id}" data-action="history">History</button>
                        <button type="button" class="btn" data-tab-id="${tab.id}" data-action="export-csv">Export CSV</button>
                        <button type="button" class="btn" data-tab-id="${tab.id}" data-action="export-json">Export JSON</button>
                    </div>
                    <div class="ai-panel" id="ai-panel-${tab.id}" style="display: none;">
                        <div class="ai-row">
                            <textarea class="ai-input" id="ai-input-${tab.id}" rows="2" maxlength="2000" aria-label="Describe what you want"
                                placeholder="Describe what you want, for example: total sales per country last month"></textarea>
                            <div class="ai-actions">
                                <button type="button" class="btn btn-primary" data-action="ai-generate" title="⌘/Ctrl + Enter">Write SQL</button>
                                <button type="button" class="btn" data-action="ai-preview" title="See exactly what would be sent, without sending it">Show what's sent</button>
                                <button type="button" class="btn" data-action="ai-settings">Settings</button>
                                <button type="button" class="btn" data-action="ai-close">Close</button>
                            </div>
                        </div>
                        <div class="ai-result" id="ai-result-${tab.id}" aria-live="polite"></div>
                    </div>
                    <div class="query-editor" id="query-editor-${tab.id}"></div>
                </div>
                <div class="results-container">
                    <div class="results-toolbar">
                        <span class="results-info" id="results-info-${tab.id}">Ready</span>
                        <div class="table-search-controls" id="results-search-controls-${tab.id}" style="display: none;">
                            <input type="text" class="table-search-input" id="results-search-${tab.id}" placeholder="Search results">
                            <select class="table-search-columns" id="results-search-columns-${tab.id}">
                                <option value="all">All Columns</option>
                            </select>
                            <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="search-results">Search</button>
                            <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="clear-results-search" style="display: none;">Clear</button>
                        </div>
                        <div class="pagination-controls" id="results-pagination-${tab.id}" style="display: none;">
                            <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="results-prev-page">Previous</button>
                            <span id="results-page-info-${tab.id}">Page 1</span>
                            <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="results-next-page">Next</button>
                        </div>
                    </div>
                    <div class="results-grid" id="results-grid-${tab.id}"></div>
                </div>
            `;

            // Initialize CodeMirror for this tab
            setTimeout(() => {
                this.initializeQueryEditor(tab);
                window.app.assistant.bind(tab);
            }, 0);
        } else if (tab.type === 'table') {
            // Create table viewer content
            contentElement.innerHTML = `
                <div class="table-data-container">
                    <div class="table-toolbar">
                        <button class="btn btn-sm btn-success" data-tab-id="${tab.id}" data-action="add-row">Add row</button>
                        <button class="btn btn-sm btn-danger" data-tab-id="${tab.id}" data-action="delete-row">Delete rows</button>
                        <button class="btn btn-sm btn-primary" data-tab-id="${tab.id}" data-action="save-changes" style="display: none;">Save changes</button>
                        <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="discard-changes" style="display: none;">Discard</button>
                        <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="export-table-csv">Export CSV</button>
                        <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="export-table-json">Export JSON</button>
                        <span class="results-info" id="table-info-${tab.id}">${this.escapeHtml(tab.state.tableName)}</span>
                        <span class="filter-chip" id="filter-chip-${tab.id}" style="display: none;"></span>
                        <div class="table-search-controls">
                            <input type="text" class="table-search-input" id="table-search-${tab.id}" placeholder="Search this table">
                            <select class="table-search-columns" id="table-search-columns-${tab.id}">
                                <option value="all">All Columns</option>
                            </select>
                            <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="search-table">Search</button>
                            <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="clear-search" style="display: none;">Clear</button>
                        </div>
                        <div class="pagination-controls">
                            <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="prev-page">Previous</button>
                            <span id="page-info-${tab.id}">Page 1</span>
                            <button class="btn btn-sm" data-tab-id="${tab.id}" data-action="next-page">Next</button>
                        </div>
                    </div>
                    <div class="table-data-grid" id="table-data-grid-${tab.id}"></div>
                </div>
            `;

            // Load table data
            setTimeout(() => {
                this.loadTableData(tab);
                this.attachTableEditorListeners(tab);
            }, 0);
        } else if (tab.type === 'map') {
            contentElement.innerHTML = `
                <div class="map-container" id="map-${tab.id}">
                    <div class="table-toolbar">
                        <input type="text" class="table-search-input map-search" placeholder="Find a table" aria-label="Find a table">
                        <button class="btn btn-sm" data-map="fit" title="Fit the whole map in view">Fit</button>
                        <button class="btn btn-sm" data-map="zoom-out" title="Zoom out" aria-label="Zoom out">−</button>
                        <button class="btn btn-sm" data-map="zoom-in" title="Zoom in" aria-label="Zoom in">+</button>
                        <button class="btn btn-sm" data-map="refresh" title="Read the relationships again">Refresh</button>
                        <span class="results-info map-info"></span>
                        <span class="map-hint">Scroll to zoom, drag to pan, click a table to open it</span>
                    </div>
                    <div class="map-canvas"></div>
                    <div class="map-loose"></div>
                </div>`;
            setTimeout(() => window.app.relations.renderMap(tab), 0);
        } else if (tab.type === 'schema') {
            // Create schema viewer content
            contentElement.innerHTML = `
                <div class="table-data-container">
                    <div class="table-toolbar">
                        <span class="results-info" id="schema-info-${tab.id}">Schema: ${tab.state.tableName}</span>
                    </div>
                    <div class="table-data-grid" id="schema-grid-${tab.id}">
                        <div class="spinner"></div>
                    </div>
                </div>
            `;

            // Load schema data
            setTimeout(() => {
                this.loadSchemaData(tab);
            }, 0);
        }

        // Append to main content area (use ID to target inner container)
        const mainContent = document.getElementById('main-content');
        if (mainContent) {
            mainContent.appendChild(contentElement);
        }

        return contentElement;
    }

    /**
     * Initialize CodeMirror editor for a query tab
     * @param {object} tab - Tab object
     */
    initializeQueryEditor(tab) {
        const editorElement = document.getElementById(`query-editor-${tab.id}`);
        if (!editorElement || editorElement.classList.contains('CodeMirror')) return;

        // Get connection type to determine editor mode
        const connection = window.app.connectionManager.connections.find(c => c.id === tab.connectionId);
        const dbType = connection ? connection.type : 'postgresql';

        // Determine CodeMirror mode and placeholder based on database type
        let mode, placeholder;

        if (dbType === 'mongodb') {
            mode = 'application/json';
            placeholder = '{\n  "collection": "users",\n  "filter": { "age": { "$gt": 25 } },\n  "limit": 100\n}';
        } else if (dbType === 'redis') {
            mode = 'text/plain';
            placeholder = '# Redis command - Example:\nKEYS *\nGET mykey\nHGETALL myhash';
        } else {
            // SQL databases (PostgreSQL, MySQL, SQLite, SQL Server, Oracle)
            mode = 'text/x-sql';
            placeholder = '-- Write your SQL query here\nSELECT * FROM table_name LIMIT 100;';
        }

        const editor = CodeMirror(editorElement, {
            mode: mode,
            theme: 'monokai',
            lineNumbers: true,
            lineWrapping: true,
            autoCloseBrackets: true,
            matchBrackets: true,
            indentWithTabs: true,
            indentUnit: 2,
            tabSize: 2,
            extraKeys: {
                'Ctrl-Enter': () => this.executeQuery(tab.id),
                'Cmd-Enter': () => this.executeQuery(tab.id),
                'Ctrl-Space': (cm) => {
                    if (cm.getOption('mode') === 'text/x-sql') {
                        const hintOpts = cm.getOption('hintOptions') || {};
                        CodeMirror.showHint(cm, CodeMirror.hint.sql, {
                            completeSingle: false,
                            tables: hintOpts.tables || {},
                            disableKeywords: false
                        });
                    } else {
                        CodeMirror.commands.autocomplete(cm);
                    }
                }
            },
            hintOptions: {
                completeSingle: false,
                tables: {},  // Will be populated with table/column data
                defaultTable: '',
                disableKeywords: false
            }
        });

        // Restore saved query text or set placeholder
        if (tab.state.query && tab.state.query.trim() !== '') {
            // Only restore if there's actual saved content
            editor.setValue(tab.state.query);
        } else {
            // Set placeholder based on database type
            editor.setValue(placeholder);
            tab.templateText = placeholder;   // lets the assistant tell an untouched template from the user's own text
            tab.state.query = placeholder;
        }

        // Save editor instance to tab
        tab.editor = editor;

        // Auto-save query text on change
        editor.on('change', () => {
            tab.state.query = editor.getValue();
            this.persistToStorage();
        });

        // Show autocomplete on input
        if (mode === 'text/x-sql') {
            editor.on('inputRead', (cm, change) => {
                // Trigger autocomplete when typing letters or after certain characters
                if (!cm.state.completionActive) {
                    const text = change.text[0];
                    if (text.match(/[a-zA-Z_]/)) {
                        // Get the hint options with table data
                        const hintOpts = cm.getOption('hintOptions') || {};
                        CodeMirror.commands.autocomplete(cm, CodeMirror.hint.sql, {
                            completeSingle: false,
                            tables: hintOpts.tables || {},
                            disableKeywords: false
                        });
                    }
                }
            });
        } else if (mode === 'application/json') {
            editor.on('inputRead', (cm, change) => {
                if (!cm.state.completionActive) {
                    const text = change.text[0];
                    if (text.match(/[a-zA-Z_"]/)) {
                        CodeMirror.commands.autocomplete(cm, null, { completeSingle: false });
                    }
                }
            });
        }

        // Populate database selector
        const selector = document.querySelector(`[data-tab-id="${tab.id}"].database-selector`);
        if (selector) {
            this.populateDatabaseSelector(tab, selector);
        }

        // Load autocomplete hints for current database
        if (tab.state.database && (mode === 'text/x-sql' || mode === 'application/json')) {
            this.loadAutocompleteHints(tab, mode);
        }

        // Attach button event listeners
        this.attachQueryEditorListeners(tab);
    }

    /**
     * Populate database selector dropdown for a query tab
     * @param {object} tab - Tab object
     * @param {HTMLElement} selector - Select element
     */
    async populateDatabaseSelector(tab, selector) {
        const activeConn = window.app.connectionManager.getActiveConnection();
        if (!activeConn) return;

        try {
            const response = await fetch(`/api/databases?connection_id=${activeConn.id}`);
            const data = await response.json();

            if (data.success) {
                selector.innerHTML = '<option value="">Select Database</option>';

                // Auto-select first database if none is selected
                if (!tab.state.database && data.databases.length > 0) {
                    tab.state.database = data.databases[0];
                }

                data.databases.forEach(db => {
                    const option = document.createElement('option');
                    option.value = db;
                    option.textContent = db.split(/[\\/]/).pop() || db;
                    option.title = db;
                    if (db === tab.state.database) {
                        option.selected = true;
                    }
                    selector.appendChild(option);
                });

                selector.addEventListener('change', (e) => {
                    tab.state.database = e.target.value;
                    this.persistToStorage();
                    // Reload autocomplete hints for new database
                    if (tab.editor) {
                        const mode = tab.editor.getOption('mode');
                        if (mode === 'text/x-sql' || mode === 'application/json') {
                            this.loadAutocompleteHints(tab, mode);
                        }
                    }
                });

                // Load hints immediately if database is selected
                if (tab.state.database && tab.editor) {
                    const mode = tab.editor.getOption('mode');
                    if (mode === 'text/x-sql' || mode === 'application/json') {
                        this.loadAutocompleteHints(tab, mode);
                    }
                }
            }
        } catch (error) {
            console.error('Error loading databases:', error);
        }
    }

    /**
     * Load autocomplete hints (table/collection names and column names) for editor
     * @param {object} tab - Tab object
     * @param {string} mode - Editor mode (text/x-sql or application/json)
     */
    // ---- autocomplete schema ------------------------------------------------------------
    // One cache entry per connection+database, shared by every query tab. Table names load once;
    // columns load in a single batched request: all of them for a small schema, otherwise only
    // for the tables the query actually mentions.
    getSchemaEntry(connectionId, database) {
        this.schemaCache = this.schemaCache || new Map();
        const key = `${connectionId}|${database}`;
        if (!this.schemaCache.has(key)) {
            this.schemaCache.set(key, (async () => {
                const data = await (await fetch(`/api/tables?connection_id=${connectionId}&database=${encodeURIComponent(database)}`)).json();
                if (!data.success) throw new Error(data.error || 'Could not list tables');
                const entry = { tables: data.tables.map(t => t.name), columns: {}, requested: new Set() };
                entry.tables.forEach(name => { entry.columns[name] = []; });
                return entry;
            })().catch(err => { this.schemaCache.delete(key); throw err; }));
        }
        return this.schemaCache.get(key);
    }

    invalidateSchemaCache(connectionId) {
        if (!this.schemaCache) return;
        for (const key of [...this.schemaCache.keys()]) {
            if (key.startsWith(`${connectionId}|`)) this.schemaCache.delete(key);
        }
    }

    async fetchColumns(connectionId, database, entry, names) {
        const wanted = (names || entry.tables).filter(n => !entry.requested.has(n));
        if (!wanted.length) return false;
        wanted.forEach(n => entry.requested.add(n));
        let url = `/api/columns?connection_id=${connectionId}&database=${encodeURIComponent(database)}`;
        if (names) url += wanted.map(n => `&tables=${encodeURIComponent(n)}`).join('');
        try {
            const data = await (await fetch(url)).json();
            if (!data.success) throw new Error(data.error);
            Object.entries(data.columns).forEach(([table, cols]) => { entry.columns[table] = cols; });
            return true;
        } catch (err) {
            wanted.forEach(n => entry.requested.delete(n));  // let a later keystroke retry
            console.error('Error loading columns:', err);
            return false;
        }
    }

    async loadAutocompleteHints(tab, mode) {
        const activeConn = window.app.connectionManager.getActiveConnection();
        if (!activeConn || !tab.state.database || !tab.editor) {
            return;
        }

        try {
            const entry = await this.getSchemaEntry(activeConn.id, tab.state.database);

            if (mode === 'text/x-sql') {
                // columns is mutated in place as batches arrive, so every tab sharing it sees the update
                tab.editor.setOption('hintOptions', {
                    completeSingle: false,
                    tables: entry.columns,
                    defaultTable: '',
                    disableKeywords: false
                });

                const SMALL_SCHEMA = 60;
                if (entry.tables.length <= SMALL_SCHEMA) {
                    await this.fetchColumns(activeConn.id, tab.state.database, entry, null);
                } else {
                    let timer;
                    const loadMentioned = () => {
                        const words = new Set((tab.editor.getValue().toLowerCase().match(/[a-z_][\w$]*/g)) || []);
                        const names = entry.tables.filter(n => words.has(n.toLowerCase()) && !entry.requested.has(n)).slice(0, 20);
                        if (names.length) this.fetchColumns(activeConn.id, tab.state.database, entry, names);
                    };
                    tab.editor.on('change', () => { clearTimeout(timer); timer = setTimeout(loadMentioned, 400); });
                    loadMentioned();
                }

            } else if (mode === 'application/json') {
                // For MongoDB: Create simple keyword list with collection names
                const mongoKeywords = [
                    'collection', 'filter', 'projection', 'limit', 'skip', 'sort',
                    '$gt', '$gte', '$lt', '$lte', '$eq', '$ne', '$in', '$nin',
                    '$and', '$or', '$not', '$exists', '$regex', '$text',
                    ...entry.tables
                ];

                // Store keywords for anyword hint
                tab.mongoHints = mongoKeywords;
            }

        } catch (error) {
            console.error('Error loading autocomplete hints:', error);
        }
    }

    /**
     * Attach event listeners for query editor buttons
     * @param {object} tab - Tab object
     */
    attachQueryEditorListeners(tab) {
        const editorElement = document.querySelector(`#query-editor-${tab.id}`);

        if (!editorElement) {
            console.error('Could not find editor element for tab:', tab.id);
            return;
        }

        const container = editorElement.closest('.query-editor-container');

        if (!container) {
            console.error('Could not find query-editor-container for tab:', tab.id);
            return;
        }

        const toolbar = container.querySelector('.query-editor-toolbar');

        if (!toolbar) {
            console.error('Could not find query-editor-toolbar for tab:', tab.id);
            return;
        }


        toolbar.addEventListener('click', (e) => {
            const button = e.target.closest('button');
            if (!button) return;

            const action = button.getAttribute('data-action');

            // Prevent any default button behavior
            e.preventDefault();
            e.stopPropagation();

            switch (action) {
                case 'execute':
                    if (tab.running) this.cancelQuery(tab); else this.executeQuery(tab.id);
                    break;
                case 'ask':
                    window.app.assistant.toggle(tab);
                    break;
                case 'clear':
                    if (tab.editor) {
                        tab.editor.setValue('');
                    }
                    break;
                case 'history':
                    this.showQueryHistory(tab);
                    break;
                case 'export-csv':
                    this.exportResults(tab, 'csv');
                    break;
                case 'export-json':
                    this.exportResults(tab, 'json');
                    break;
            }
        });
    }

    /**
     * Execute query for a tab
     * @param {string} tabId - Tab ID
     */
    // While a query runs, the Run button becomes Cancel
    setRunButton(tab, running) {
        const btn = document.querySelector(`[data-tab-id="${tab.id}"][data-action="execute"]`);
        if (!btn) return;
        if (!btn.dataset.label) btn.dataset.label = btn.textContent;
        btn.textContent = running ? 'Cancel' : btn.dataset.label;
        btn.classList.toggle('btn-danger', running);
        btn.classList.toggle('btn-primary', !running);
    }

    async cancelQuery(tab) {
        const activeConn = window.app.connectionManager.getActiveConnection();
        if (!activeConn) return;
        try {
            const result = await (await fetch('/api/query/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ connection_id: activeConn.id })
            })).json();
            if (!result.success) this.showNotification(result.error, 'warning');
        } catch (error) {
            this.showNotification('Could not reach the server to cancel the query.', 'error');
        }
    }

    async executeQuery(tabId) {
        const tab = this.tabs.get(tabId);
        if (!tab || !tab.editor || tab.running) return;

        // Execute selected text if there's a selection, otherwise execute all
        const selectedText = tab.editor.getSelection();
        const query = (selectedText ? selectedText : tab.editor.getValue()).trim();

        if (!query) {
            ui.notify('Please enter a query');
            return;
        }

        const activeConn = window.app.connectionManager.getActiveConnection();
        if (!activeConn) {
            ui.notify('Please connect to a database first');
            return;
        }

        const resultsGrid = document.getElementById(`results-grid-${tabId}`);
        const resultsInfo = document.getElementById(`results-info-${tabId}`);

        // Start timing
        const startTime = Date.now();
        let statusInterval;

        // Update status every 100ms to show elapsed time
        statusInterval = setInterval(() => {
            const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
            resultsInfo.textContent = `⏱ Executing query... ${elapsed}s`;
        }, 100);

        resultsGrid.innerHTML = '<div class="spinner"></div>';
        tab.running = true;
        this.setRunButton(tab, true);

        try {
            const send = async (confirmed) => (await fetch('/api/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ connection_id: activeConn.id, query: query, confirmed })
            })).json();

            let data = await send(false);
            if (data.needs_confirmation) {
                // The server refuses risky statements until the user agrees; nothing has run yet
                if (!(await ui.confirm(`${data.reason}.\n\nRun it anyway?`, { title: window.app.connectionManager.isProduction(activeConn.id) ? 'Run this on PRODUCTION?' : 'Run this statement?', confirmLabel: window.app.connectionManager.isProduction(activeConn.id) ? 'Run on production' : 'Run it', danger: true }))) {
                    clearInterval(statusInterval);
                    resultsGrid.innerHTML = '';
                    resultsInfo.textContent = 'Cancelled. Nothing was run.';
                    return;
                }
                data = await send(true);
            }
            const executionTime = ((Date.now() - startTime) / 1000).toFixed(2);

            // Stop status updates
            clearInterval(statusInterval);

            if (data.success && !data.result.error) {
                tab.state.results = data.result;

                // Show immediate feedback
                resultsInfo.textContent = `✓ Query completed in ${executionTime}s - Processing ${data.result.row_count} rows...`;

                // Start rendering immediately
                this.displayQueryResultsProgressive(tab, data.result, executionTime);
                this.addToQueryHistory(tab.connectionId, query);
                if (/^\s*(create|alter|drop|rename)\b/i.test(query)) { this.invalidateSchemaCache(activeConn.id); window.app.relations.invalidate(activeConn.id); }
            } else {
                this.displayError(tab, data.result?.error || data.error);
                resultsInfo.textContent = `✗ Query failed in ${executionTime}s`;
            }
        } catch (error) {
            clearInterval(statusInterval);
            console.error('Error executing query:', error);
            this.displayError(tab, error.message);
            resultsInfo.textContent = '✗ Error executing query';
        } finally {
            tab.running = false;
            this.setRunButton(tab, false);
        }
    }

    /**
     * Display query results in a tab
     * @param {object} tab - Tab object
     * @param {object} result - Query result
     */
    displayQueryResults(tab, result) {
        const resultsGrid = document.getElementById(`results-grid-${tab.id}`);
        const resultsInfo = document.getElementById(`results-info-${tab.id}`);

        if (!result.columns || result.columns.length === 0) {
            resultsGrid.innerHTML = '<div style="padding: 20px; text-align: center;">Query ran. It returned no rows.</div>';
            resultsInfo.textContent = 'No results';
            this.hideResultsPagination(tab);
            return;
        }

        // Store full result set on tab
        tab.queryResult = result;

        // Initialize pagination state
        if (!tab.queryPagination) {
            tab.queryPagination = {
                currentPage: 1,
                rowsPerPage: 100
            };
        } else {
            // Reset to page 1 for new query results
            tab.queryPagination.currentPage = 1;
        }

        // Update results info
        resultsInfo.textContent = `${result.rows.length} row(s) returned`;

        // Show/hide pagination based on result size
        if (result.rows.length > tab.queryPagination.rowsPerPage) {
            this.showResultsPagination(tab);
        } else {
            this.hideResultsPagination(tab);
        }

        // Render current page
        this.renderQueryResultsPage(tab);
    }

    displayQueryResultsProgressive(tab, result, executionTime) {
        const resultsGrid = document.getElementById(`results-grid-${tab.id}`);
        const resultsInfo = document.getElementById(`results-info-${tab.id}`);

        if (!result.columns || result.columns.length === 0) {
            resultsGrid.innerHTML = '<div style="padding: 20px; text-align: center;">Query ran. It returned no rows.</div>';
            resultsInfo.textContent = `✓ Completed in ${executionTime}s - No results`;
            this.hideResultsPagination(tab);
            return;
        }

        // Store full result set on tab (unfiltered)
        tab.queryResult = result;
        tab.unfilteredQueryResult = result; // Store original for search reset

        // Reset any active search
        tab.queryResultSearch = null;

        // Initialize pagination state
        if (!tab.queryPagination) {
            tab.queryPagination = {
                currentPage: 1,
                rowsPerPage: 100
            };
        } else {
            // Reset to page 1 for new query results
            tab.queryPagination.currentPage = 1;
        }

        // Show search controls
        this.showResultsSearchControls(tab);
        this.populateResultsSearchColumns(tab, result.columns);
        this.attachResultsSearchListeners(tab);

        // Show/hide pagination based on result size
        if (result.rows.length > tab.queryPagination.rowsPerPage) {
            this.showResultsPagination(tab);
        } else {
            this.hideResultsPagination(tab);
        }

        // Render first page immediately with progressive status
        this.renderQueryResultsPageProgressive(tab, executionTime);
    }

    renderQueryResultsPage(tab) {
        const result = tab.queryResult;
        if (!result) return;

        const { currentPage, rowsPerPage } = tab.queryPagination;
        const startIdx = (currentPage - 1) * rowsPerPage;
        const endIdx = Math.min(startIdx + rowsPerPage, result.rows.length);

        // Create page subset
        const pageResult = {
            columns: result.columns,
            rows: result.rows.slice(startIdx, endIdx)
        };

        // Update page info
        const totalPages = Math.ceil(result.rows.length / rowsPerPage);
        const pageInfo = document.getElementById(`results-page-info-${tab.id}`);
        if (pageInfo) {
            pageInfo.textContent = `Page ${currentPage} of ${totalPages} (${startIdx + 1}-${endIdx} of ${result.rows.length})`;
        }

        // Render the page
        const resultsGrid = document.getElementById(`results-grid-${tab.id}`);
        this.renderQueryResultsBatched(tab, pageResult, resultsGrid);
    }

    renderQueryResultsPageProgressive(tab, executionTime) {
        const result = tab.queryResult;
        if (!result) return;

        const { currentPage, rowsPerPage } = tab.queryPagination;
        const startIdx = (currentPage - 1) * rowsPerPage;
        const endIdx = Math.min(startIdx + rowsPerPage, result.rows.length);

        // Create page subset
        const pageResult = {
            columns: result.columns,
            rows: result.rows.slice(startIdx, endIdx)
        };

        // Update page info
        const totalPages = Math.ceil(result.rows.length / rowsPerPage);
        const pageInfo = document.getElementById(`results-page-info-${tab.id}`);
        if (pageInfo) {
            pageInfo.textContent = `Page ${currentPage} of ${totalPages} (${startIdx + 1}-${endIdx} of ${result.rows.length})`;
        }

        // Render the page with progressive status updates
        const resultsGrid = document.getElementById(`results-grid-${tab.id}`);
        const resultsInfo = document.getElementById(`results-info-${tab.id}`);

        this.renderQueryResultsBatchedProgressive(tab, pageResult, resultsGrid, () => {
            // Callback when rendering completes
            resultsInfo.textContent = `✓ ${result.rows.length} row(s) in ${executionTime}s` +
                (result.truncated ? `. Only the first ${result.rows.length.toLocaleString()} rows are shown: add a WHERE or LIMIT to see the rest.` : '');
        });
    }

    showResultsPagination(tab) {
        const pagination = document.getElementById(`results-pagination-${tab.id}`);
        if (pagination) {
            pagination.style.display = 'flex';

            // Attach pagination event listeners (only once)
            if (!tab.resultsPaginationListenersAttached) {
                this.attachResultsPaginationListeners(tab);
                tab.resultsPaginationListenersAttached = true;
            }
        }
    }

    hideResultsPagination(tab) {
        const pagination = document.getElementById(`results-pagination-${tab.id}`);
        if (pagination) {
            pagination.style.display = 'none';
        }
    }

    attachResultsPaginationListeners(tab) {
        const toolbar = document.getElementById(`results-pagination-${tab.id}`).closest('.results-toolbar');

        toolbar.addEventListener('click', (e) => {
            const button = e.target.closest('button');
            if (!button) return;

            const action = button.getAttribute('data-action');

            if (action === 'results-prev-page') {
                if (tab.queryPagination.currentPage > 1) {
                    tab.queryPagination.currentPage--;
                    this.renderQueryResultsPage(tab);
                }
            } else if (action === 'results-next-page') {
                const totalPages = Math.ceil(tab.queryResult.rows.length / tab.queryPagination.rowsPerPage);
                if (tab.queryPagination.currentPage < totalPages) {
                    tab.queryPagination.currentPage++;
                    this.renderQueryResultsPage(tab);
                }
            }
        });
    }

    showResultsSearchControls(tab) {
        const searchControls = document.getElementById(`results-search-controls-${tab.id}`);
        if (searchControls) {
            searchControls.style.display = 'flex';
        }
    }

    populateResultsSearchColumns(tab, columns) {
        const select = document.getElementById(`results-search-columns-${tab.id}`);
        if (!select || !columns) return;

        // Clear and add "All Columns" option
        select.innerHTML = '<option value="all">All Columns</option>';

        // Add each column as an option
        columns.forEach(col => {
            const option = document.createElement('option');
            option.value = col;
            option.textContent = col;
            select.appendChild(option);
        });
    }

    attachResultsSearchListeners(tab) {
        const toolbar = document.querySelector(`#results-search-controls-${tab.id}`).closest('.results-toolbar');
        const searchInput = document.getElementById(`results-search-${tab.id}`);

        // Avoid attaching multiple listeners
        if (tab.resultsSearchListenersAttached) return;
        tab.resultsSearchListenersAttached = true;

        toolbar.addEventListener('click', (e) => {
            const button = e.target.closest('button');
            if (!button) return;

            const action = button.getAttribute('data-action');

            if (action === 'search-results') {
                this.searchQueryResults(tab);
            } else if (action === 'clear-results-search') {
                this.clearQueryResultsSearch(tab);
            }
        });

        // Add Enter key support for search input
        if (searchInput) {
            searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.searchQueryResults(tab);
                }
            });
        }
    }

    searchQueryResults(tab) {
        const searchInput = document.getElementById(`results-search-${tab.id}`);
        const columnSelect = document.getElementById(`results-search-columns-${tab.id}`);
        const clearBtn = document.querySelector(`[data-tab-id="${tab.id}"][data-action="clear-results-search"]`);
        const resultsInfo = document.getElementById(`results-info-${tab.id}`);

        if (!searchInput || !columnSelect) return;

        const searchTerm = searchInput.value.trim().toLowerCase();
        if (!searchTerm) {
            ui.notify('Please enter a search term');
            return;
        }

        const selectedColumn = columnSelect.value;

        // Filter results client-side
        const unfilteredResult = tab.unfilteredQueryResult;
        const filteredRows = unfilteredResult.rows.filter(row => {
            if (selectedColumn === 'all') {
                // Search all columns
                return unfilteredResult.columns.some(col => {
                    const value = row[col];
                    if (value === null || value === undefined) return false;
                    const strValue = String(value).toLowerCase();
                    return strValue.includes(searchTerm);
                });
            } else {
                // Search specific column
                const value = row[selectedColumn];
                if (value === null || value === undefined) return false;
                const strValue = String(value).toLowerCase();
                return strValue.includes(searchTerm);
            }
        });

        // Update query result with filtered rows
        tab.queryResult = {
            columns: unfilteredResult.columns,
            rows: filteredRows
        };

        // Store search state
        tab.queryResultSearch = {
            term: searchTerm,
            column: selectedColumn
        };

        // Reset to page 1
        tab.queryPagination.currentPage = 1;

        // Show clear button
        if (clearBtn) {
            clearBtn.style.display = 'inline-block';
        }

        // Update info
        const searchInfo = selectedColumn !== 'all' ? ` in ${selectedColumn}` : '';
        resultsInfo.textContent = `${filteredRows.length} of ${unfilteredResult.rows.length} rows (filtered by "${searchTerm}"${searchInfo})`;

        // Update pagination visibility
        if (filteredRows.length > tab.queryPagination.rowsPerPage) {
            this.showResultsPagination(tab);
        } else {
            this.hideResultsPagination(tab);
        }

        // Re-render results
        this.renderQueryResultsPage(tab);
    }

    clearQueryResultsSearch(tab) {
        const searchInput = document.getElementById(`results-search-${tab.id}`);
        const clearBtn = document.querySelector(`[data-tab-id="${tab.id}"][data-action="clear-results-search"]`);
        const resultsInfo = document.getElementById(`results-info-${tab.id}`);

        // Restore unfiltered results
        tab.queryResult = tab.unfilteredQueryResult;
        tab.queryResultSearch = null;

        // Reset to page 1
        tab.queryPagination.currentPage = 1;

        // Clear UI
        if (searchInput) searchInput.value = '';
        if (clearBtn) clearBtn.style.display = 'none';

        // Update info
        resultsInfo.textContent = `${tab.queryResult.rows.length} row(s) returned`;

        // Update pagination visibility
        if (tab.queryResult.rows.length > tab.queryPagination.rowsPerPage) {
            this.showResultsPagination(tab);
        } else {
            this.hideResultsPagination(tab);
        }

        // Re-render results
        this.renderQueryResultsPage(tab);
    }

    renderQueryResultsBatched(tab, result, resultsGrid) {
        // Build table header first
        let headerHtml = '<table class="data-table"><thead><tr>';
        result.columns.forEach(col => {
            headerHtml += `<th>
                <span class="th-content">${this.escapeHtml(col)}</span>
                <div class="resize-handle"></div>
            </th>`;
        });
        headerHtml += `</tr></thead><tbody id="tbody-${tab.id}"></tbody></table>`;

        resultsGrid.innerHTML = headerHtml;
        const tbody = document.getElementById(`tbody-${tab.id}`);

        // Render rows in batches to avoid UI freeze
        const BATCH_SIZE = 50; // Render 50 rows at a time (pagination limits total rows anyway)
        let currentIndex = 0;

        const renderBatch = () => {
            const endIndex = Math.min(currentIndex + BATCH_SIZE, result.rows.length);
            let batchHtml = '';

            for (let rowIndex = currentIndex; rowIndex < endIndex; rowIndex++) {
                const row = result.rows[rowIndex];
                batchHtml += `<tr data-row-index="${rowIndex}">`;

                result.columns.forEach(col => {
                    const value = row[col];
                    batchHtml += this.renderCellHtml(value, col);
                });

                batchHtml += '</tr>';
            }

            tbody.insertAdjacentHTML('beforeend', batchHtml);
            currentIndex = endIndex;

            // Continue rendering if more rows remain
            if (currentIndex < result.rows.length) {
                // Use setTimeout instead of requestAnimationFrame for better control
                setTimeout(renderBatch, 0);
            } else {
                // All rows rendered - attach listeners
                this.attachJsonCellListeners();
                this.attachQueryResultEditListeners(tab, resultsGrid);

                // Make columns resizable
                const table = resultsGrid.querySelector('.data-table');
                if (table && window.app.queryEditor) {
                    window.app.queryEditor.makeColumnsResizable(table);
                }
            }
        };

        // Start rendering
        setTimeout(renderBatch, 0);
    }

    renderQueryResultsBatchedProgressive(tab, result, resultsGrid, onComplete) {
        // Build table header first
        let headerHtml = '<table class="data-table"><thead><tr>';
        result.columns.forEach(col => {
            headerHtml += `<th>
                <span class="th-content">${this.escapeHtml(col)}</span>
                <div class="resize-handle"></div>
            </th>`;
        });
        headerHtml += `</tr></thead><tbody id="tbody-${tab.id}"></tbody></table>`;

        resultsGrid.innerHTML = headerHtml;
        const tbody = document.getElementById(`tbody-${tab.id}`);
        const resultsInfo = document.getElementById(`results-info-${tab.id}`);

        // Render rows in batches to avoid UI freeze
        const BATCH_SIZE = 50;
        let currentIndex = 0;

        const renderBatch = () => {
            const endIndex = Math.min(currentIndex + BATCH_SIZE, result.rows.length);
            let batchHtml = '';

            for (let rowIndex = currentIndex; rowIndex < endIndex; rowIndex++) {
                const row = result.rows[rowIndex];
                batchHtml += `<tr data-row-index="${rowIndex}">`;

                result.columns.forEach(col => {
                    const value = row[col];
                    batchHtml += this.renderCellHtml(value, col);
                });

                batchHtml += '</tr>';
            }

            tbody.insertAdjacentHTML('beforeend', batchHtml);
            currentIndex = endIndex;

            // Update status
            if (resultsInfo) {
                const totalRows = tab.queryResult.rows.length;
                const progress = Math.round((currentIndex / result.rows.length) * 100);
                resultsInfo.textContent = `📊 Rendering page... ${currentIndex}/${result.rows.length} rows (${progress}%) | Total: ${totalRows} rows`;
            }

            // Continue rendering if more rows remain
            if (currentIndex < result.rows.length) {
                setTimeout(renderBatch, 0);
            } else {
                // All rows rendered - attach listeners
                this.attachJsonCellListeners();
                this.attachQueryResultEditListeners(tab, resultsGrid);

                // Make columns resizable
                const table = resultsGrid.querySelector('.data-table');
                if (table && window.app.queryEditor) {
                    window.app.queryEditor.makeColumnsResizable(table);
                }

                // Call completion callback
                if (onComplete) {
                    onComplete();
                }
            }
        };

        // Start rendering
        setTimeout(renderBatch, 0);
    }

    renderCellHtml(value, col) {
        if (value === null || value === undefined || value === '') {
            return `<td class="null editable" contenteditable="true" data-column="${this.escapeHtml(col)}" data-original-value="">NULL</td>`;
        } else if (typeof value === 'object') {
            // Handle JSON objects - read-only, edit via modal
            const compactJson = JSON.stringify(value);
            const jsonId = `json-${this.jsonIdCounter++}`;
            this.jsonDataStore.set(jsonId, JSON.stringify(value, null, 2));

            const previewText = compactJson.length > 50
                ? compactJson.substring(0, 50) + '...'
                : compactJson;
            const preview = this.escapeHtml(previewText);

            return `<td class="json-editable" contenteditable="false" data-column="${this.escapeHtml(col)}" data-original-value="${this.escapeHtml(previewText)}" style="position: relative;">
                <span class="json-preview">${preview}</span>
                <span class="json-view-icon" data-json-id="${jsonId}" contenteditable="false" title="View full value">{ }</span>
            </td>`;
        } else {
            const strValue = String(value);
            const len = strValue.length;

            // Skip JSON validation for very short strings or strings that clearly aren't JSON
            if (len < 2 || (strValue[0] !== '{' && strValue[0] !== '[')) {
                if (len > 100) {
                    // Long non-JSON string
                    const jsonId = `json-${this.jsonIdCounter++}`;
                    this.jsonDataStore.set(jsonId, strValue);
                    const previewText = strValue.substring(0, 100) + '...';
                    const preview = this.escapeHtml(previewText);

                    return `<td class="long-text-editable" contenteditable="false" data-column="${this.escapeHtml(col)}" data-original-value="${this.escapeHtml(previewText)}" style="position: relative;" title="Click 🔍 to view/edit">
                        <span class="json-preview">${preview}</span>
                        <span class="json-view-icon" data-json-id="${jsonId}" contenteditable="false" title="View full value">{ }</span>
                    </td>`;
                } else {
                    // Short regular string
                    return `<td class="editable" contenteditable="true" data-column="${this.escapeHtml(col)}" data-original-value="${this.escapeHtml(strValue)}" title="${this.escapeHtml(strValue)}">${this.escapeHtml(strValue)}</td>`;
                }
            }

            // Only validate JSON for strings that look like JSON
            const trimmed = strValue.trim();
            if ((trimmed[0] === '{' && trimmed[len - 1] === '}') || (trimmed[0] === '[' && trimmed[len - 1] === ']')) {
                try {
                    const parsedJson = JSON.parse(strValue);
                    // Valid JSON
                    const compactJson = JSON.stringify(parsedJson);
                    const jsonId = `json-${this.jsonIdCounter++}`;
                    this.jsonDataStore.set(jsonId, JSON.stringify(parsedJson, null, 2));

                    const previewText = compactJson.length > 50
                        ? compactJson.substring(0, 50) + '...'
                        : compactJson;
                    const preview = this.escapeHtml(previewText);

                    return `<td class="json-editable" contenteditable="false" data-column="${this.escapeHtml(col)}" data-original-value="${this.escapeHtml(previewText)}" style="position: relative;">
                        <span class="json-preview">${preview}</span>
                        <span class="json-view-icon" data-json-id="${jsonId}" contenteditable="false" title="View full value">{ }</span>
                    </td>`;
                } catch (e) {
                    // Not valid JSON, treat as regular string
                }
            }

            // Default: regular string
            if (len > 100) {
                const jsonId = `json-${this.jsonIdCounter++}`;
                this.jsonDataStore.set(jsonId, strValue);
                const previewText = strValue.substring(0, 100) + '...';
                const preview = this.escapeHtml(previewText);

                return `<td class="long-text-editable" contenteditable="false" data-column="${this.escapeHtml(col)}" data-original-value="${this.escapeHtml(previewText)}" style="position: relative;" title="Click 🔍 to view/edit">
                    <span class="json-preview">${preview}</span>
                    <span class="json-view-icon" data-json-id="${jsonId}" contenteditable="false" title="View full value">{ }</span>
                </td>`;
            } else {
                return `<td class="editable" contenteditable="true" data-column="${this.escapeHtml(col)}" data-original-value="${this.escapeHtml(strValue)}" title="${this.escapeHtml(strValue)}">${this.escapeHtml(strValue)}</td>`;
            }
        }
    }

    /**
     * Attach edit listeners to query result cells
     * @param {object} tab - Tab object
     * @param {HTMLElement} gridElement - Grid element
     */
    attachQueryResultEditListeners(tab, gridElement) {
        const editableCells = gridElement.querySelectorAll('td.editable');

        editableCells.forEach(cell => {
            // Clear "NULL" text when focusing on empty cell
            cell.addEventListener('focus', (e) => {
                if (e.target.textContent === 'NULL') {
                    e.target.textContent = '';
                    e.target.classList.remove('null');
                }
            });

            // Track changes on blur (visual feedback only for query results)
            cell.addEventListener('blur', (e) => {
                // For cells with json-view-icon, get text from preview span only
                let newValue;
                const previewSpan = e.target.querySelector('.json-preview');
                if (previewSpan) {
                    // JSON or long text cell - only compare preview text
                    newValue = previewSpan.textContent.trim();
                } else {
                    // Regular cell - use full text content
                    newValue = e.target.textContent.trim();
                }

                const originalValue = e.target.getAttribute('data-original-value');

                if (newValue !== originalValue) {
                    // Mark cell as modified (visual feedback)
                    e.target.classList.add('modified');
                } else {
                    e.target.classList.remove('modified');
                }

                // If empty, show NULL (only for non-JSON cells)
                if (newValue === '' && !previewSpan) {
                    e.target.textContent = 'NULL';
                    e.target.classList.add('null');
                }
            });
        });
    }

    /**
     * Display error in a tab
     * @param {object} tab - Tab object
     * @param {string} error - Error message
     */
    displayError(tab, error) {
        const resultsGrid = document.getElementById(`results-grid-${tab.id}`);
        resultsGrid.innerHTML = `
            <div class="error-message" role="alert"><strong>The query failed</strong><pre>${this.escapeHtml(error)}</pre></div>`;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Load table data for a table tab
     * @param {object} tab - Tab object
     */
    // Plain loads are searches with no term, so there is one code path for paging, search and sort
    async loadTableData(tab) {
        return this.loadTableDataWithSearch(tab);
    }

    renderTableData(tab, tableData, gridElement) {
        if (!tableData || !tableData.columns || tableData.columns.length === 0) {
            gridElement.innerHTML = '<div style="padding: 20px;">No data available</div>';
            return;
        }

        // Store original data for change tracking
        tab.originalTableData = JSON.parse(JSON.stringify(tableData.rows));
        tab.tableColumns = tableData.columns;
        tab.modifiedRows = new Set();

        const conn = window.app.connectionManager.connections.find(c => c.id === tab.connectionId);
        const insights = !!conn && ColumnInsights.supported(conn.type);   // column insights read through SQL
        let html = '<table class="data-table selectable">';

        // Header with resize handles and checkbox for selection
        html += '<thead><tr>';
        html += `<th style="width: 40px;"><input type="checkbox" class="select-all" aria-label="Select all rows"></th>`;
        tableData.columns.forEach(col => {
            const sorted = tab.state.sortBy === col ? (tab.state.sortOrder || 'ASC').toLowerCase() : '';
            html += `<th data-col="${this.escapeHtml(col)}" ${sorted ? `data-sort="${sorted}" aria-sort="${sorted === 'asc' ? 'ascending' : 'descending'}"` : ''}>
                <span class="th-content" title="Click to sort">${this.escapeHtml(col)}</span>${insights ? `<button type="button" class="th-insight" title="What is in this column?" aria-label="About column ${this.escapeHtml(col)}">▾</button>` : ''}
                <div class="resize-handle"></div>
            </th>`;
        });
        html += '</tr></thead>';

        // Body
        html += '<tbody>';
        tableData.rows.forEach((row, rowIndex) => {
            html += `<tr data-row-index="${rowIndex}">`;
            html += `<td style="width: 40px;"><input type="checkbox" class="row-checkbox" data-row-index="${rowIndex}"></td>`;
            tableData.columns.forEach(col => {
                const value = row[col];

                if (value === '') {
                    html += `<td class="empty editable" contenteditable="true" data-column="${this.escapeHtml(col)}" data-original-value="" title="Empty string"></td>`;
                } else if (value === null || value === undefined) {
                    html += `<td class="null editable" contenteditable="true" data-column="${this.escapeHtml(col)}" data-original-value="">NULL</td>`;
                } else if (typeof value === 'object') {
                    // Handle JSON objects
                    const jsonStr = JSON.stringify(value, null, 2);
                    const compactJson = JSON.stringify(value);
                    const jsonId = `json-${this.jsonIdCounter++}`;
                    this.jsonDataStore.set(jsonId, jsonStr);

                    const preview = compactJson.length > 50
                        ? this.escapeHtml(compactJson.substring(0, 50)) + '...'
                        : this.escapeHtml(compactJson);

                    html += `<td>
                        <span class="json-cell" data-json-id="${jsonId}">
                            <span class="json-preview">${preview}</span>
                            <span class="json-icon" title="View full value">{ }</span>
                        </span>
                    </td>`;
                } else {
                    // Check if string value is valid JSON
                    const strValue = String(value);
                    let isValidJson = false;
                    let parsedJson = null;

                    if (strValue.trim().startsWith('{') || strValue.trim().startsWith('[')) {
                        try {
                            parsedJson = JSON.parse(strValue);
                            isValidJson = true;
                        } catch (e) {
                            isValidJson = false;
                        }
                    }

                    if (isValidJson) {
                        // Treat as JSON - show with viewer
                        const jsonStr = JSON.stringify(parsedJson, null, 2);
                        const compactJson = JSON.stringify(parsedJson);
                        const jsonId = `json-${this.jsonIdCounter++}`;
                        this.jsonDataStore.set(jsonId, jsonStr);

                        const preview = compactJson.length > 50
                            ? this.escapeHtml(compactJson.substring(0, 50)) + '...'
                            : this.escapeHtml(compactJson);

                        html += `<td>
                            <span class="json-cell" data-json-id="${jsonId}">
                                <span class="json-preview">${preview}</span>
                                <span class="json-icon" title="View full value">{ }</span>
                            </span>
                        </td>`;
                    } else if (strValue.length > 100) {
                        // Handle long non-JSON strings - make them expandable
                        const jsonId = `json-${this.jsonIdCounter++}`;
                        this.jsonDataStore.set(jsonId, strValue);
                        const preview = this.escapeHtml(strValue.substring(0, 100)) + '...';

                        html += `<td>
                            <span class="json-cell" data-json-id="${jsonId}" title="Click to view full content">
                                <span class="json-preview">${preview}</span>
                                <span class="json-icon" title="View full value">{ }</span>
                            </span>
                        </td>`;
                    } else {
                        // Short regular strings - make editable
                        html += `<td class="editable" contenteditable="true" data-column="${this.escapeHtml(col)}" data-original-value="${this.escapeHtml(strValue)}" title="${this.escapeHtml(strValue)}">${this.escapeHtml(strValue)}</td>`;
                    }
                }
            });
            html += '</tr>';
        });
        html += '</tbody></table>';

        gridElement.innerHTML = html;

        // Attach JSON cell listeners (using TabManager's jsonDataStore)
        this.attachJsonCellListeners();

        gridElement.querySelector('.select-all').addEventListener('change', (e) => {
            gridElement.querySelectorAll('.row-checkbox').forEach(cb => { cb.checked = e.target.checked; });
        });

        // Header click cycles sort: ascending, descending, off. Sorting happens in the database, across all pages.
        gridElement.querySelectorAll('th[data-col] .th-content').forEach(label => {
            label.addEventListener('click', async () => {
                if (!(await this.guardUnsaved(tab, 'sort'))) return;
                const col = label.closest('th').dataset.col;
                const s = tab.state;
                if (s.sortBy !== col) { s.sortBy = col; s.sortOrder = 'ASC'; }
                else if (s.sortOrder === 'ASC') { s.sortOrder = 'DESC'; }
                else { s.sortBy = null; s.sortOrder = null; }
                s.page = 1;
                this.loadTableData(tab);
            });
        });

        // Make columns resizable
        const table = gridElement.querySelector('.data-table');
        if (table && window.app.queryEditor) {
            window.app.queryEditor.makeColumnsResizable(table);
        }

        // Attach pagination listeners
        this.attachTablePaginationListeners(tab);

        // Attach cell edit listeners
        this.attachCellEditListeners(tab, gridElement);

        // Foreign-key values become links (see relations.js); column headers get their insights panel
        window.app.relations.decorateGrid(tab, gridElement);
        window.app.insights.attach(tab, gridElement);

        // A read-only connection never edits: no editable cells, and the editing buttons are hidden by CSS
        const container = gridElement.closest('.table-data-container');
        if (container) container.classList.toggle('read-only', !!(conn && conn.read_only));
        if (conn && conn.read_only) {
            gridElement.querySelectorAll('[contenteditable="true"]').forEach(c => c.setAttribute('contenteditable', 'false'));
        }
    }

    attachJsonCellListeners() {
        // Attach listeners to the 🔍 icon specifically, not the whole cell
        document.querySelectorAll('.json-view-icon').forEach(icon => {
            // Prevent mousedown from focusing the parent cell
            icon.addEventListener('mousedown', (e) => {
                e.preventDefault();
                e.stopPropagation();
            });

            icon.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation(); // Prevent cell edit
                const jsonId = icon.getAttribute('data-json-id');
                const jsonData = this.jsonDataStore.get(jsonId);
                const cell = icon.closest('td');
                if (jsonData) {
                    this.showEditableJsonModal(jsonData, jsonId, cell);
                }
            });
        });

        // Also handle old-style json-cell (for backward compatibility with table tabs)
        document.querySelectorAll('.json-cell').forEach(cell => {
            // Only if it doesn't have the new json-view-icon inside
            if (!cell.querySelector('.json-view-icon')) {
                cell.addEventListener('click', (e) => {
                    const jsonId = e.currentTarget.getAttribute('data-json-id');
                    const jsonData = this.jsonDataStore.get(jsonId);
                    if (jsonData) {
                        this.showEditableJsonModal(jsonData, jsonId, cell);
                    }
                });
            }
        });
    }

    showJsonModal(jsonStr) {
        // Reuse QueryEditor's modal
        if (window.app.queryEditor) {
            window.app.queryEditor.showJsonModal(jsonStr);
        }
    }

    /**
     * Show editable JSON modal
     * @param {*} jsonData - JSON data (object or string)
     * @param {string} jsonId - JSON ID in dataStore
     * @param {HTMLElement} cell - The cell element
     */
    showEditableJsonModal(jsonData, jsonId, cell) {
        // Create modal
        const modalId = 'json-editor-modal';
        let modal = document.getElementById(modalId);

        if (!modal) {
            modal = document.createElement('div');
            modal.id = modalId;
            modal.className = 'modal';
            document.body.appendChild(modal);
        }

        // Convert data to formatted JSON string
        const jsonStr = typeof jsonData === 'string' ? jsonData : JSON.stringify(jsonData, null, 2);

        modal.innerHTML = `
            <div class="modal-content modal-large">
                <div class="modal-header">
                    <h3>Edit JSON</h3>
                    <span class="modal-close" data-modal-id="${modalId}">×</span>
                </div>
                <div class="modal-body">
                    <div style="margin-bottom: 12px; display: flex; gap: 8px;">
                        <button class="btn btn-sm" id="json-format-btn">Format</button>
                        <button class="btn btn-sm" id="json-copy-btn">Copy</button>
                        <input type="text" id="json-search-input" placeholder="Search JSON..." class="form-control" style="flex: 1;">
                    </div>
                    <div id="json-editor-container" style="height: 400px; border: 1px solid #3a3a3a;"></div>
                    <div class="form-actions" style="margin-top: 16px;">
                        <button class="btn btn-primary" id="json-save-btn">Save Changes</button>
                        <button class="btn" id="json-cancel-btn">Cancel</button>
                    </div>
                </div>
            </div>
        `;

        modal.classList.add('active');

        // Initialize CodeMirror editor
        const editorContainer = modal.querySelector('#json-editor-container');
        const editor = CodeMirror(editorContainer, {
            value: jsonStr,
            mode: 'application/json',
            theme: 'monokai',
            lineNumbers: true,
            lineWrapping: true,
            matchBrackets: true,
            autoCloseBrackets: true
        });

        // Format button
        modal.querySelector('#json-format-btn').addEventListener('click', () => {
            try {
                const parsed = JSON.parse(editor.getValue());
                editor.setValue(JSON.stringify(parsed, null, 2));
            } catch (e) {
                ui.notify('Invalid JSON: ' + e.message);
            }
        });

        // Copy button
        modal.querySelector('#json-copy-btn').addEventListener('click', () => {
            navigator.clipboard.writeText(editor.getValue());
            ui.notify('JSON copied to clipboard!');
        });

        // Search functionality
        const searchInput = modal.querySelector('#json-search-input');
        searchInput.addEventListener('input', (e) => {
            const searchTerm = e.target.value;
            if (!searchTerm) {
                editor.getDoc().getAllMarks().forEach(mark => mark.clear());
                return;
            }

            editor.getDoc().getAllMarks().forEach(mark => mark.clear());

            const cursor = editor.getSearchCursor(searchTerm);
            while (cursor.findNext()) {
                editor.markText(cursor.from(), cursor.to(), {
                    className: 'highlighted-search-term',
                    css: 'background-color: rgba(255, 193, 7, 0.3);'
                });
            }
        });

        // Save button
        modal.querySelector('#json-save-btn').addEventListener('click', () => {
            try {
                const newJsonStr = editor.getValue().trim();
                const parsed = JSON.parse(newJsonStr);

                // Update the jsonDataStore
                this.jsonDataStore.set(jsonId, parsed);

                // Update the cell preview
                const previewSpan = cell.querySelector('.json-preview');
                if (previewSpan) {
                    const newPreview = newJsonStr.length > 50 ? newJsonStr.substring(0, 50) + '...' : newJsonStr;
                    previewSpan.textContent = newPreview;
                }

                // Mark cell as modified
                cell.classList.add('modified');

                // Find the active tab and enable save buttons
                const activeTabId = this.activeTabId;
                if (activeTabId) {
                    const activeTab = this.tabs.get(activeTabId);
                    if (activeTab && activeTab.type === 'table') {
                        this.toggleSaveButtons(activeTab, true);
                    }
                }

                modal.classList.remove('active');
            } catch (e) {
                ui.notify('Invalid JSON: ' + e.message);
            }
        });

        // Cancel button
        modal.querySelector('#json-cancel-btn').addEventListener('click', () => {
            modal.classList.remove('active');
        });

        // Close button
        modal.querySelector('.modal-close').addEventListener('click', () => {
            modal.classList.remove('active');
        });

        // Close on background click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('active');
            }
        });
    }

    attachTablePaginationListeners(tab) {
        const prevBtn = document.querySelector(`[data-tab-id="${tab.id}"][data-action="prev-page"]`);
        const nextBtn = document.querySelector(`[data-tab-id="${tab.id}"][data-action="next-page"]`);

        if (prevBtn) {
            prevBtn.onclick = async () => {
                if (tab.state.page > 1) {
                    if (!(await this.guardUnsaved(tab, 'change page'))) return;
                    tab.state.page--;
                    // Use search-aware loading if search is active
                    if (tab.state.searchTerm) {
                        this.loadTableDataWithSearch(tab);
                    } else {
                        this.loadTableData(tab);
                    }
                    this.persistToStorage();
                }
            };
        }

        if (nextBtn) {
            nextBtn.onclick = async () => {
                if (!tab.state.hasMore) return;
                if (!(await this.guardUnsaved(tab, 'change page'))) return;
                tab.state.page++;
                // Use search-aware loading if search is active
                if (tab.state.searchTerm) {
                    this.loadTableDataWithSearch(tab);
                } else {
                    this.loadTableData(tab);
                }
                this.persistToStorage();
            };
        }
    }

    /**
     * Attach table editor button listeners
     * @param {object} tab - Tab object
     */
    attachTableEditorListeners(tab) {
        const toolbar = document.querySelector(`#table-info-${tab.id}`).closest('.table-toolbar');

        toolbar.addEventListener('click', async (e) => {
            const button = e.target.closest('button');
            if (!button) return;

            const action = button.getAttribute('data-action');

            // Prevent any default button behavior
            e.preventDefault();
            e.stopPropagation();

            switch (action) {
                case 'add-row':
                    this.addNewRow(tab);
                    break;
                case 'delete-row':
                    await this.deleteSelectedRows(tab);
                    break;
                case 'save-changes':
                    await this.saveTableChanges(tab);
                    break;
                case 'discard-changes':
                    this.discardTableChanges(tab);
                    break;
                case 'search-table':
                    this.searchTable(tab);
                    break;
                case 'clear-search':
                    this.clearTableSearch(tab);
                    break;
                case 'clear-filter':
                    if (!(await this.guardUnsaved(tab, 'remove the filter'))) break;
                    tab.state.filter = null;
                    tab.state.page = 1;
                    tab.title = tab.state.tableName;
                    document.querySelector(`#tabs-header [data-tab-id="${tab.id}"] .tab-label`).textContent = tab.title;
                    this.loadTableData(tab);
                    this.persistToStorage();
                    break;
                case 'export-table-csv':
                    this.exportTableData(tab, 'csv');
                    break;
                case 'export-table-json':
                    this.exportTableData(tab, 'json');
                    break;
            }
        });

        // Add Enter key support for search input
        const searchInput = document.getElementById(`table-search-${tab.id}`);
        if (searchInput) {
            searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.searchTable(tab);
                }
            });
        }
    }

    /**
     * Populate search column dropdown
     * @param {object} tab - Tab object
     * @param {array} columns - Column names
     */
    populateSearchColumns(tab, columns) {
        const select = document.getElementById(`table-search-columns-${tab.id}`);
        if (!select || !columns) return;

        // Clear and add "All Columns" option
        select.innerHTML = '<option value="all">All Columns</option>';

        // Add each column as an option
        columns.forEach(col => {
            const option = document.createElement('option');
            option.value = col;
            option.textContent = col;
            select.appendChild(option);
        });
    }

    /**
     * Search table data
     * @param {object} tab - Tab object
     */
    async searchTable(tab) {
        const searchInput = document.getElementById(`table-search-${tab.id}`);
        const columnSelect = document.getElementById(`table-search-columns-${tab.id}`);
        const clearBtn = document.querySelector(`[data-tab-id="${tab.id}"][data-action="clear-search"]`);

        if (!searchInput || !columnSelect) return;

        const searchTerm = searchInput.value.trim();
        if (!searchTerm) {
            ui.notify('Enter something to search for.');
            return;
        }
        if (!(await this.guardUnsaved(tab, 'search'))) return;

        const selectedColumn = columnSelect.value;

        // Store search params in tab state
        tab.state.searchTerm = searchTerm;
        tab.state.searchColumn = selectedColumn;
        tab.state.page = 1; // Reset to page 1 when searching

        // Show clear button
        if (clearBtn) {
            clearBtn.style.display = 'inline-block';
        }

        // Reload table with search params
        await this.loadTableDataWithSearch(tab);
    }

    /**
     * Clear table search
     * @param {object} tab - Tab object
     */
    async clearTableSearch(tab) {
        if (!(await this.guardUnsaved(tab, 'clear the search'))) return;
        const searchInput = document.getElementById(`table-search-${tab.id}`);
        const clearBtn = document.querySelector(`[data-tab-id="${tab.id}"][data-action="clear-search"]`);

        // Clear search state
        delete tab.state.searchTerm;
        delete tab.state.searchColumn;
        tab.state.page = 1;

        // Clear UI
        if (searchInput) searchInput.value = '';
        if (clearBtn) clearBtn.style.display = 'none';

        // Reload table without search
        await this.loadTableData(tab);
    }

    /**
     * Load table data with search filtering
     * @param {object} tab - Tab object
     */
    async loadTableDataWithSearch(tab) {
        const activeConn = window.app.connectionManager.getActiveConnection();
        if (!activeConn) return;

        const grid = document.getElementById(`table-data-grid-${tab.id}`);
        const info = document.getElementById(`table-info-${tab.id}`);

        grid.innerHTML = '<div class="spinner"></div>';

        try {
            // Build URL with search params
            let url = `/api/data?connection_id=${activeConn.id}` +
                `&database=${encodeURIComponent(tab.state.database)}` +
                `&table=${encodeURIComponent(tab.state.tableName)}` +
                `&limit=${tab.state.pageSize || 100}` +
                `&offset=${((tab.state.page || 1) - 1) * (tab.state.pageSize || 100)}`;

            // Add search params if present
            if (tab.state.searchTerm) {
                url += `&search=${encodeURIComponent(tab.state.searchTerm)}`;
                if (tab.state.searchColumn && tab.state.searchColumn !== 'all') {
                    url += `&search_column=${encodeURIComponent(tab.state.searchColumn)}`;
                }
            }

            if (tab.state.filter) {
                url += `&where_column=${encodeURIComponent(tab.state.filter.column)}&where_value=${encodeURIComponent(tab.state.filter.value)}`;
            }

            if (tab.state.sortBy) {
                url += `&sort_by=${encodeURIComponent(tab.state.sortBy)}&sort_order=${tab.state.sortOrder || 'ASC'}`;
            }

            const response = await fetch(url);
            const data = await response.json();

            if (data.success) {
                this.renderTableData(tab, data.data, grid);

                const searchInfo = tab.state.searchTerm
                    ? ` (filtered by "${tab.state.searchTerm}"${tab.state.searchColumn !== 'all' ? ` in ${tab.state.searchColumn}` : ''})`
                    : '';
                info.textContent = `${tab.state.tableName} - ${data.data.total_count} total rows${searchInfo}`;

                const pageInfo = document.getElementById(`page-info-${tab.id}`);
                if (pageInfo) {
                    pageInfo.textContent = `Page ${tab.state.page || 1}`;
                }

                const chip = document.getElementById(`filter-chip-${tab.id}`);
                if (chip) {
                    chip.style.display = tab.state.filter ? '' : 'none';
                    chip.innerHTML = tab.state.filter
                        ? `${this.escapeHtml(tab.state.filter.column)} = ${this.escapeHtml(tab.state.filter.value)}` +
                          ` <button type="button" data-tab-id="${tab.id}" data-action="clear-filter" title="Show every row again" aria-label="Clear filter">×</button>`
                        : '';
                }
                tab.state.hasMore = !!data.data.has_more;
                const nav = (action) => document.querySelector(`[data-tab-id="${tab.id}"][data-action="${action}"]`);
                if (nav('next-page')) nav('next-page').disabled = !tab.state.hasMore;
                if (nav('prev-page')) nav('prev-page').disabled = (tab.state.page || 1) <= 1;

                // Populate search column dropdown
                this.populateSearchColumns(tab, data.data.columns);
            } else {
                grid.innerHTML = `<div class="error-message">Could not load this table: ${this.escapeHtml(data.error)}</div>`;
            }
        } catch (error) {
            console.error('Error loading table data:', error);
            grid.innerHTML = `<div class="error-message">Could not load this table: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    /**
     * Attach cell edit listeners to track changes
     * @param {object} tab - Tab object
     * @param {HTMLElement} gridElement - Grid element
     */
    attachCellEditListeners(tab, gridElement) {
        const editableCells = gridElement.querySelectorAll('td.editable');

        editableCells.forEach(cell => {
            // Clear "NULL" text when focusing on empty cell
            cell.addEventListener('focus', (e) => {
                if (e.target.textContent === 'NULL') {
                    e.target.textContent = '';
                    e.target.classList.remove('null');
                }
            });

            // Track changes on blur
            cell.addEventListener('blur', (e) => {
                // For cells with json-view-icon, get text from preview span only
                let newValue;
                const previewSpan = e.target.querySelector('.json-preview');
                if (previewSpan) {
                    // JSON or long text cell - only compare preview text
                    newValue = previewSpan.textContent.trim();
                } else {
                    // Regular cell - use full text content
                    newValue = e.target.textContent.trim();
                }

                const originalValue = e.target.getAttribute('data-original-value');

                if (newValue !== originalValue) {
                    // Mark cell as modified
                    e.target.classList.add('modified');

                    // Mark row as modified
                    const rowIndex = e.target.closest('tr').getAttribute('data-row-index');
                    if (rowIndex !== null) {
                        tab.modifiedRows.add(parseInt(rowIndex));
                    }

                    // Show save/discard buttons
                    this.toggleSaveButtons(tab, true);
                } else {
                    e.target.classList.remove('modified');
                }

                // If empty, show NULL (only for non-JSON cells)
                if (newValue === '' && !previewSpan) {
                    e.target.textContent = 'NULL';
                    e.target.classList.add('null');
                }
            });
        });
    }

    /**
     * Toggle save/discard buttons visibility
     * @param {object} tab - Tab object
     * @param {boolean} show - Show or hide
     */
    toggleSaveButtons(tab, show) {
        const saveBtn = document.querySelector(`[data-tab-id="${tab.id}"][data-action="save-changes"]`);
        const discardBtn = document.querySelector(`[data-tab-id="${tab.id}"][data-action="discard-changes"]`);

        if (saveBtn) saveBtn.style.display = show ? 'inline-block' : 'none';
        if (discardBtn) discardBtn.style.display = show ? 'inline-block' : 'none';
    }

    /**
     * Add a new empty row
     * @param {object} tab - Tab object
     */
    addNewRow(tab) {
        const grid = document.getElementById(`table-data-grid-${tab.id}`);
        const table = grid.querySelector('table tbody');
        if (!table) return;

        const gridElement = document.getElementById(`table-data-grid-${tab.id}`);
        const firstRow = gridElement.querySelector('tbody tr');
        if (!firstRow) return;

        const columnCount = firstRow.querySelectorAll('td').length - 1; // Exclude checkbox

        let newRow = '<tr class="new-row" data-row-index="new">';
        newRow += '<td style="width: 40px;"><input type="checkbox" class="row-checkbox"></td>';

        // Get column names from header
        const headers = gridElement.querySelectorAll('thead th');
        for (let i = 1; i < headers.length; i++) {
            const colName = headers[i].querySelector('.th-content').textContent;
            newRow += `<td class="editable new-cell" contenteditable="true" data-column="${colName}" data-original-value=""></td>`;
        }

        newRow += '</tr>';

        table.insertAdjacentHTML('afterbegin', newRow);

        // Attach listeners to new row cells
        const newRowElement = table.querySelector('tr.new-row');
        this.attachCellEditListeners(tab, newRowElement.parentElement.parentElement);

        this.toggleSaveButtons(tab, true);
    }

    /**
     * Delete selected rows
     * @param {object} tab - Tab object
     */
    async deleteSelectedRows(tab) {
        const grid = document.getElementById(`table-data-grid-${tab.id}`);
        const selectedCheckboxes = grid.querySelectorAll('.row-checkbox:checked');

        if (selectedCheckboxes.length === 0) {
            ui.notify('Please select rows to delete');
            return;
        }

        if (!(await ui.confirm(`Delete ${selectedCheckboxes.length} selected row(s)? This cannot be undone.`, { title: window.app.connectionManager.isProduction(tab.connectionId) ? 'Delete rows on PRODUCTION' : 'Delete rows', confirmLabel: 'Delete', danger: true }))) {
            return;
        }

        const activeConn = window.app.connectionManager.getActiveConnection();
        if (!activeConn) return;

        // Get primary key columns from schema
        let primaryKeys = [];
        try {
            const schemaResponse = await fetch(
                `/api/schema?connection_id=${activeConn.id}` +
                `&database=${encodeURIComponent(tab.state.database)}` +
                `&table=${encodeURIComponent(tab.state.tableName)}`
            );
            const schemaData = await schemaResponse.json();
            if (schemaData.success) {
                primaryKeys = schemaData.schema.columns.filter(col => col.primary_key).map(col => col.name);
            }
        } catch (error) {
            console.error('Error fetching schema:', error);
        }

        // Delete each selected row
        for (const checkbox of selectedCheckboxes) {
            const row = checkbox.closest('tr');
            const rowIndex = row.getAttribute('data-row-index');

            // Skip new rows (not yet saved)
            if (rowIndex === 'new') {
                row.remove();
                continue;
            }

            // Build conditions from primary keys or all columns
            const cells = row.querySelectorAll('td.editable, td.null');
            const conditions = {};

            cells.forEach(cell => {
                const colName = cell.getAttribute('data-column');
                const value = cell.getAttribute('data-original-value');

                if (primaryKeys.length > 0) {
                    if (primaryKeys.includes(colName)) {
                        conditions[colName] = value || null;
                    }
                } else {
                    conditions[colName] = value || null;
                }
            });

            try {
                const response = await fetch('/api/data', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        connection_id: activeConn.id,
                        database: tab.state.database,
                        table: tab.state.tableName,
                        conditions: conditions
                    })
                });

                const result = await response.json();

                if (result.success) {
                    row.remove();
                } else {
                    ui.notify(`Failed to delete row: ${result.error}`);
                }
            } catch (error) {
                console.error('Error deleting row:', error);
                ui.notify(`Error deleting row: ${error.message}`);
            }
        }

        this.toggleSaveButtons(tab, false);
    }

    /**
     * Save table changes
     * @param {object} tab - Tab object
     */
    async saveTableChanges(tab) {
        const grid = document.getElementById(`table-data-grid-${tab.id}`);
        const modifiedCells = grid.querySelectorAll('td.modified');
        const newRows = grid.querySelectorAll('tr.new-row');

        if (modifiedCells.length === 0 && newRows.length === 0) {
            ui.notify('No changes to save');
            return;
        }

        const activeConn = window.app.connectionManager.getActiveConnection();
        if (!activeConn) return;

        // Changing production data is never a single stray click
        if (window.app.connectionManager.isProduction(activeConn.id)) {
            const n = modifiedCells.length + newRows.length;
            if (!(await ui.confirm(`Save ${n} change${n === 1 ? '' : 's'} to ${activeConn.name}? This is a production database.`,
                    { title: 'Change production data', confirmLabel: 'Save to production', safeDefault: true }))) return;
        }

        // Get primary key columns from schema
        let primaryKeys = [];
        try {
            const schemaResponse = await fetch(
                `/api/schema?connection_id=${activeConn.id}` +
                `&database=${encodeURIComponent(tab.state.database)}` +
                `&table=${encodeURIComponent(tab.state.tableName)}`
            );
            const schemaData = await schemaResponse.json();
            if (schemaData.success) {
                primaryKeys = schemaData.schema.columns.filter(col => col.primary_key).map(col => col.name);
            }
        } catch (error) {
            console.error('Error fetching schema:', error);
        }

        // Save new rows (INSERT)
        for (const newRow of newRows) {
            const cells = newRow.querySelectorAll('td.editable, td.json-editable, td.long-text-editable');
            const data = {};

            cells.forEach(cell => {
                const colName = cell.getAttribute('data-column');

                // Check if this is a JSON/long-text cell with data stored in jsonDataStore
                const jsonIcon = cell.querySelector('.json-view-icon');
                if (jsonIcon) {
                    const jsonId = jsonIcon.getAttribute('data-json-id');
                    if (jsonId && this.jsonDataStore.has(jsonId)) {
                        const storedValue = this.jsonDataStore.get(jsonId);
                        // For JSON objects, convert back to string
                        if (typeof storedValue === 'object') {
                            data[colName] = JSON.stringify(storedValue);
                        } else {
                            data[colName] = storedValue;
                        }
                        return;
                    }
                }

                const value = cell.textContent.trim();
                data[colName] = value === 'NULL' || value === '' ? null : value;
            });

            try {
                const response = await fetch('/api/data', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        connection_id: activeConn.id,
                        database: tab.state.database,
                        table: tab.state.tableName,
                        data: data
                    })
                });

                const result = await response.json();

                if (result.success) {
                    newRow.classList.remove('new-row');
                    newRow.classList.add('saved-row');
                } else {
                    ui.notify(`Failed to insert row: ${result.error}`);
                    return;
                }
            } catch (error) {
                console.error('Error inserting row:', error);
                ui.notify(`Error inserting row: ${error.message}`);
                return;
            }
        }

        // Save modified rows (UPDATE)
        const modifiedRows = {};
        modifiedCells.forEach(cell => {
            const row = cell.closest('tr');
            const rowIndex = row.getAttribute('data-row-index');

            if (!modifiedRows[rowIndex]) {
                modifiedRows[rowIndex] = { row, cells: [] };
            }

            modifiedRows[rowIndex].cells.push(cell);
        });

        for (const rowIndex in modifiedRows) {
            const { row, cells } = modifiedRows[rowIndex];
            const rowIdx = parseInt(rowIndex);

            // Get original row data
            const originalRow = tab.originalTableData[rowIdx];
            if (!originalRow) {
                console.error('Original row data not found for index:', rowIdx);
                continue;
            }

            // Build update data and conditions
            const updateData = {};
            const conditions = {};

            // Build conditions from primary keys or all original values
            if (primaryKeys.length > 0) {
                // Use primary keys for conditions
                primaryKeys.forEach(pkCol => {
                    let value = originalRow[pkCol];
                    // Convert objects to JSON string
                    if (typeof value === 'object' && value !== null) {
                        value = JSON.stringify(value);
                    }
                    conditions[pkCol] = value;
                });
            } else {
                // Use all original values as conditions (except modified columns)
                const modifiedColumns = new Set();
                cells.forEach(cell => {
                    const colName = cell.getAttribute('data-column');
                    if (colName) modifiedColumns.add(colName);
                });

                tab.tableColumns.forEach(col => {
                    if (!modifiedColumns.has(col)) {
                        let value = originalRow[col];
                        // Convert objects to JSON string
                        if (typeof value === 'object' && value !== null) {
                            value = JSON.stringify(value);
                        }
                        conditions[col] = value;
                    }
                });
            }

            // Build update data from modified cells
            cells.forEach(cell => {
                const colName = cell.getAttribute('data-column');
                if (!colName) return;

                // Check if this is a JSON/long-text cell with data stored in jsonDataStore
                const jsonIcon = cell.querySelector('.json-view-icon');
                if (jsonIcon) {
                    const jsonId = jsonIcon.getAttribute('data-json-id');
                    if (jsonId && this.jsonDataStore.has(jsonId)) {
                        const storedValue = this.jsonDataStore.get(jsonId);
                        // For JSON objects, convert back to string
                        if (typeof storedValue === 'object') {
                            updateData[colName] = JSON.stringify(storedValue);
                        } else {
                            updateData[colName] = storedValue;
                        }
                        return;
                    }
                }

                // Regular editable cell
                let newValue = cell.textContent.trim();
                if (newValue === 'NULL' || newValue === '') {
                    newValue = null;
                }

                updateData[colName] = newValue;
            });

            try {
                const response = await fetch('/api/data', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        connection_id: activeConn.id,
                        database: tab.state.database,
                        table: tab.state.tableName,
                        conditions: conditions,
                        data: updateData
                    })
                });

                const result = await response.json();

                if (result.success) {
                    // Update original values and remove modified class
                    cells.forEach(cell => {
                        cell.setAttribute('data-original-value', cell.textContent.trim());
                        cell.classList.remove('modified');
                    });
                } else {
                    const errorMsg = result.error || result.message || 'Unknown error';
                    console.error('Update failed:', result);
                    ui.notify(`Failed to update row: ${errorMsg}`);
                    return;
                }
            } catch (error) {
                console.error('Error updating row:', error);
                ui.notify(`Error updating row: ${error.message}`);
                return;
            }
        }

        this.toggleSaveButtons(tab, false);

        // Reload table to show fresh data with proper state
        await this.loadTableData(tab);

        ui.notify('Changes saved successfully!');
    }

    /**
     * Discard table changes
     * @param {object} tab - Tab object
     */
    async discardTableChanges(tab) {
        if (!(await ui.confirm('Discard all unsaved changes in this table?', { title: 'Discard changes', confirmLabel: 'Discard', danger: true }))) {
            return;
        }

        // Reload table data
        this.loadTableData(tab);
        this.toggleSaveButtons(tab, false);
    }

    /**
     * Load schema data for a schema tab
     * @param {object} tab - Tab object
     */
    async loadSchemaData(tab) {
        const activeConn = window.app.connectionManager.getActiveConnection();
        if (!activeConn) return;

        const grid = document.getElementById(`schema-grid-${tab.id}`);

        try {
            const response = await fetch(
                `/api/schema?connection_id=${activeConn.id}` +
                `&database=${encodeURIComponent(tab.state.database)}` +
                `&table=${encodeURIComponent(tab.state.tableName)}`
            );

            const data = await response.json();

            if (data.success) {
                this.renderSchemaData(tab, data.schema, grid);
            } else {
                grid.innerHTML = `<div class="error-message">Error: ${data.error}</div>`;
            }
        } catch (error) {
            console.error('Error loading schema:', error);
            grid.innerHTML = `<div class="error-message">Error loading schema: ${error.message}</div>`;
        }
    }

    renderSchemaData(tab, schema, gridElement) {
        let html = '<div style="padding: 20px;">';

        // Columns
        if (schema.columns && schema.columns.length > 0) {
            html += '<h3 style="margin-bottom: 10px; color: var(--text-color);">Columns</h3>';
            html += '<table class="data-table" style="margin-bottom: 20px;">';
            html += '<thead><tr><th>Name</th><th>Type</th><th>Nullable</th><th>Default</th><th>Primary Key</th></tr></thead>';
            html += '<tbody>';

            schema.columns.forEach(col => {
                html += '<tr>';
                html += `<td><strong>${this.escapeHtml(col.name)}</strong></td>`;
                html += `<td>${this.escapeHtml(col.type)}</td>`;
                html += `<td>${col.nullable ? 'Yes' : 'No'}</td>`;
                html += `<td>${col.default ? this.escapeHtml(col.default) : '-'}</td>`;
                html += `<td>${col.primary_key ? 'Yes' : 'No'}</td>`;
                html += '</tr>';
            });

            html += '</tbody></table>';
        }

        // Indexes
        if (schema.indexes && schema.indexes.length > 0) {
            html += '<h3 style="margin-bottom: 10px; color: var(--text-color);">Indexes</h3>';
            html += '<table class="data-table" style="margin-bottom: 20px;">';
            html += '<thead><tr><th>Name</th><th>Columns</th><th>Unique</th></tr></thead>';
            html += '<tbody>';

            schema.indexes.forEach(idx => {
                html += '<tr>';
                html += `<td>${this.escapeHtml(idx.name)}</td>`;
                html += `<td>${idx.columns ? this.escapeHtml(idx.columns.join(', ')) : '-'}</td>`;
                html += `<td>${idx.unique ? 'Yes' : 'No'}</td>`;
                html += '</tr>';
            });

            html += '</tbody></table>';
        }

        // Foreign Keys
        if (schema.foreign_keys && schema.foreign_keys.length > 0) {
            html += '<h3 style="margin-bottom: 10px; color: var(--text-color);">Foreign Keys</h3>';
            html += '<table class="data-table">';
            html += '<thead><tr><th>Column</th><th>Referenced Table</th><th>Referenced Column</th></tr></thead>';
            html += '<tbody>';

            schema.foreign_keys.forEach(fk => {
                html += '<tr>';
                html += `<td>${this.escapeHtml(fk.column)}</td>`;
                html += `<td>${this.escapeHtml(fk.referenced_table)}</td>`;
                html += `<td>${this.escapeHtml(fk.referenced_column)}</td>`;
                html += '</tr>';
            });

            html += '</tbody></table>';
        }

        html += '</div>';

        gridElement.innerHTML = html;
    }

    /**
     * Get all tabs for a connection
     * @param {string} connectionId - Connection ID
     * @returns {Array} Array of tab objects
     */
    getTabsByConnection(connectionId) {
        const tabIds = this.tabsByConnection.get(connectionId) || new Set();
        return Array.from(tabIds).map(id => this.tabs.get(id)).filter(t => t);
    }

    /**
     * Hide all tabs for a connection
     * @param {string} connectionId - Connection ID
     */
    hideTabsForConnection(connectionId) {
        const tabs = this.getTabsByConnection(connectionId);
        tabs.forEach(tab => {
            const tabElement = document.querySelector(`[data-tab-id="${tab.id}"]`);
            if (tabElement) {
                tabElement.style.display = 'none';
            }

            const contentElement = document.querySelector(`[data-content-for="${tab.id}"]`);
            if (contentElement) {
                contentElement.style.display = 'none';
            }
        });
    }

    /**
     * Show/restore tabs for a connection
     * @param {string} connectionId - Connection ID
     */
    restoreTabsForConnection(connectionId) {
        const tabs = this.getTabsByConnection(connectionId);

        tabs.forEach(tab => {
            // Show tab in tab bar
            let tabElement = document.querySelector(`[data-tab-id="${tab.id}"]`);
            if (!tabElement) {
                this.renderTab(tab);
            } else {
                tabElement.style.display = 'flex';
            }
        });

        // Switch to the last active tab for this connection
        if (tabs.length > 0) {
            const lastActiveTab = this.activeTabByConnection.get(connectionId);
            if (lastActiveTab && this.tabs.has(lastActiveTab)) {
                this.switchTab(lastActiveTab);
            } else {
                this.switchTab(tabs[0].id);
            }
        }
    }

    /**
     * Add query to history
     * @param {string} connectionId - Connection ID
     * @param {string} query - SQL query
     */
    addToQueryHistory(connectionId, query) {
        let history = {};
        try {
            const stored = localStorage.getItem(this.HISTORY_KEY);
            if (stored) {
                history = JSON.parse(stored);
            }
        } catch (e) {
            console.error('Error loading query history:', e);
        }

        if (!history[connectionId]) {
            history[connectionId] = [];
        }

        history[connectionId].unshift({
            query: query,
            timestamp: new Date().toISOString()
        });

        // Keep only last 50 queries per connection
        if (history[connectionId].length > 50) {
            history[connectionId] = history[connectionId].slice(0, 50);
        }

        localStorage.setItem(this.HISTORY_KEY, JSON.stringify(history));
    }

    /**
     * Show query history for a tab
     * @param {object} tab - Tab object
     */
    showQueryHistory(tab) {
        let history = {};
        try {
            const stored = localStorage.getItem(this.HISTORY_KEY);
            if (stored) {
                history = JSON.parse(stored);
            }
        } catch (e) {
            console.error('Error loading query history:', e);
        }

        const connectionHistory = history[tab.connectionId] || [];

        if (connectionHistory.length === 0) {
            ui.notify('No query history');
            return;
        }

        const resultsGrid = document.getElementById(`results-grid-${tab.id}`);
        let html = '<div style="padding: 20px;">';
        html += '<h3>Query History</h3>';
        html += '<div style="margin-top: 15px;">';

        connectionHistory.forEach((item, index) => {
            const date = new Date(item.timestamp);
            html += `
                <div style="padding: 10px; margin-bottom: 10px; background: var(--sidebar-bg); border-radius: 4px; cursor: pointer;"
                     onclick="window.app.tabManager.loadHistoryQuery('${tab.id}', ${index})">
                    <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 5px;">
                        ${date.toLocaleString()}
                    </div>
                    <code style="font-size: 12px;">${this.escapeHtml(item.query.substring(0, 100))}${item.query.length > 100 ? '...' : ''}</code>
                </div>
            `;
        });

        html += '</div></div>';
        resultsGrid.innerHTML = html;
    }

    /**
     * Load a query from history into editor
     * @param {string} tabId - Tab ID
     * @param {number} index - History index
     */
    loadHistoryQuery(tabId, index) {
        const tab = this.tabs.get(tabId);
        if (!tab || !tab.editor) return;

        let history = {};
        try {
            const stored = localStorage.getItem(this.HISTORY_KEY);
            if (stored) {
                history = JSON.parse(stored);
            }
        } catch (e) {
            console.error('Error loading query history:', e);
        }

        const connectionHistory = history[tab.connectionId] || [];
        const item = connectionHistory[index];

        if (item) {
            tab.editor.setValue(item.query);
            tab.editor.focus();
        }
    }

    /**
     * Export query results
     * @param {object} tab - Tab object
     * @param {string} format - 'csv' or 'json'
     */
    exportResults(tab, format) {

        // Check if we have query results (from tab.queryResult which has all rows)
        const results = tab.queryResult || tab.state.results;

        if (!results || !results.rows || results.rows.length === 0) {
            ui.notify('No results to export');
            return;
        }

        const rows = results.rows;
        const columns = results.columns;
        const rowCount = rows.length;


        // Generate filename: try to extract table name from query or use "query-results"
        let tableName = this.extractTableNameFromQuery(tab);
        const filename = `${tableName}_${rowCount}`;


        if (format === 'csv') {
            this.exportToCSV(rows, columns, filename);
        } else if (format === 'json') {
            this.exportToJSON(rows, filename);
        }
    }

    /**
     * Export table data
     * @param {object} tab - Tab object (table type)
     * @param {string} format - 'csv' or 'json'
     */
    exportTableData(tab, format) {
        // Get the currently displayed table data
        const tableGrid = document.getElementById(`table-data-grid-${tab.id}`);
        if (!tableGrid) {
            ui.notify('No table data to export');
            return;
        }

        // Extract data from the displayed table
        const table = tableGrid.querySelector('table');
        if (!table) {
            ui.notify('No table data to export');
            return;
        }

        // Get column names from table headers
        const headerRow = table.querySelector('thead tr');
        if (!headerRow) {
            ui.notify('No table headers found');
            return;
        }

        const columns = Array.from(headerRow.querySelectorAll('th'))
            .map(th => th.textContent.trim())
            .filter(col => col && col !== ''); // Remove empty columns (like checkbox column)

        // Get data rows
        const dataRows = table.querySelectorAll('tbody tr');
        if (!dataRows || dataRows.length === 0) {
            ui.notify('No data rows to export');
            return;
        }

        // Convert DOM rows to data objects
        const rows = [];
        dataRows.forEach(tr => {
            const cells = tr.querySelectorAll('td');
            const rowData = {};

            let colIndex = 0;
            cells.forEach((cell, cellIndex) => {
                // Skip checkbox cells
                if (cell.querySelector('input[type="checkbox"]')) {
                    return;
                }

                if (colIndex < columns.length) {
                    const colName = columns[colIndex];

                    // Check if this cell has JSON data in jsonDataStore
                    const jsonIcon = cell.querySelector('.json-view-icon');
                    if (jsonIcon) {
                        const jsonId = jsonIcon.getAttribute('data-json-id');
                        if (jsonId && this.jsonDataStore.has(jsonId)) {
                            const jsonData = this.jsonDataStore.get(jsonId);
                            rowData[colName] = jsonData; // Export as object/string
                        } else {
                            rowData[colName] = cell.textContent.trim();
                        }
                    } else {
                        const cellValue = cell.textContent.trim();
                        rowData[colName] = cellValue === 'NULL' ? null : cellValue;
                    }

                    colIndex++;
                }
            });

            rows.push(rowData);
        });

        const rowCount = rows.length;
        const tableName = tab.state.tableName || 'table-data';
        const filename = `${tableName}_${rowCount}`;

        if (format === 'csv') {
            this.exportToCSV(rows, columns, filename);
        } else if (format === 'json') {
            this.exportToJSON(rows, filename);
        }
    }

    /**
     * Extract table name from SQL query
     * @param {object} tab - Tab object
     * @returns {string} Table name or "query-results"
     */
    extractTableNameFromQuery(tab) {
        try {
            // Get the query from editor
            const query = tab.editor ? tab.editor.getValue().trim() : '';

            if (!query) return 'query-results';

            // Try to extract table name from simple SELECT/UPDATE/DELETE queries
            // Match: SELECT ... FROM table_name, UPDATE table_name, DELETE FROM table_name
            const fromMatch = query.match(/FROM\s+([a-zA-Z0-9_]+)/i);
            const updateMatch = query.match(/UPDATE\s+([a-zA-Z0-9_]+)/i);
            const deleteMatch = query.match(/DELETE\s+FROM\s+([a-zA-Z0-9_]+)/i);

            const tableName = fromMatch?.[1] || updateMatch?.[1] || deleteMatch?.[1];

            return tableName ? tableName.toLowerCase() : 'query-results';
        } catch (e) {
            return 'query-results';
        }
    }

    /**
     * Export rows to CSV file
     * @param {Array} rows - Array of row objects
     * @param {Array} columns - Array of column names
     * @param {string} filename - Base filename without extension
     */
    exportToCSV(rows, columns, filename = 'query-results') {
        // Build CSV header
        const header = columns.map(col => this.escapeCSV(col)).join(',');

        // Build CSV rows
        const csvRows = rows.map(row => {
            return columns.map(col => {
                const value = row[col];
                // Convert objects to JSON strings
                if (typeof value === 'object' && value !== null) {
                    return this.escapeCSV(JSON.stringify(value));
                }
                return this.escapeCSV(value);
            }).join(',');
        });

        // Combine header and rows
        const csv = [header, ...csvRows].join('\n');

        // Download file
        this.downloadFile(csv, `${filename}.csv`, 'text/csv');
    }

    /**
     * Escape CSV values
     * @param {*} value - Value to escape
     * @returns {string} Escaped value
     */
    escapeCSV(value) {
        if (value === null || value === undefined) {
            return '';
        }
        const str = String(value);
        // Escape quotes and wrap in quotes if contains comma, quote, or newline
        if (str.includes(',') || str.includes('"') || str.includes('\n')) {
            return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
    }

    /**
     * Export rows to JSON file
     * @param {Array} rows - Array of row objects
     * @param {string} filename - Base filename without extension
     */
    exportToJSON(rows, filename = 'query-results') {
        const json = JSON.stringify(rows, null, 2);
        this.downloadFile(json, `${filename}.json`, 'application/json');
    }

    /**
     * Download a file
     * @param {string} content - File content
     * @param {string} filename - File name
     * @param {string} mimeType - MIME type
     */
    downloadFile(content, filename, mimeType) {

        try {
            // Create blob with proper MIME type
            const blob = new Blob([content], { type: mimeType });

            // Check if browser supports the download attribute
            const link = document.createElement('a');

            if ('download' in link) {
                // Modern browsers - use blob URL with download attribute
                const url = URL.createObjectURL(blob);
                link.href = url;
                link.download = filename;
                link.style.display = 'none';

                // Append to body, click, and remove
                document.body.appendChild(link);

                // Use setTimeout to ensure the link is in the DOM before clicking
                setTimeout(() => {
                    link.click();

                    // Clean up after a short delay
                    setTimeout(() => {
                        document.body.removeChild(link);
                        URL.revokeObjectURL(url);
                    }, 100);
                }, 0);
            } else {
                // Fallback for older browsers
                const reader = new FileReader();
                reader.onload = function() {
                    const dataUrl = reader.result;
                    link.href = dataUrl;
                    link.download = filename;
                    link.click();
                };
                reader.readAsDataURL(blob);
            }

            // Show success notification
            this.showNotification(`File "${filename}" downloaded successfully`, 'success');
        } catch (error) {
            console.error('Error downloading file:', error);
            this.showNotification(`Failed to download file: ${error.message}`, 'error');
        }
    }

    /**
     * Save all tabs to localStorage (debounced)
     */
    persistToStorage() {
        clearTimeout(this.saveTimeout);
        this.saveTimeout = setTimeout(() => {
            const session = this.buildSessionObject();
            try {
                localStorage.setItem(this.SESSION_KEY, JSON.stringify(session));
            } catch (e) {
                console.error('Error saving session:', e);
                // Handle quota exceeded
                if (e.name === 'QuotaExceededError') {
                    ui.notify('Browser storage quota exceeded. Some session data may not be saved.');
                }
            }
        }, this.SAVE_DELAY);
    }

    /**
     * Build session object for storage
     * @returns {object} Session object
     */
    buildSessionObject() {
        const activeConn = window.app.connectionManager.getActiveConnection();
        const connectedConnections = window.app.connectionManager.connectedConnections;

        // Convert activeTabByConnection Map to plain object for JSON storage
        const activeTabsByConnection = {};
        this.activeTabByConnection.forEach((tabId, connectionId) => {
            activeTabsByConnection[connectionId] = tabId;
        });

        return {
            version: 1,
            lastActiveConnection: activeConn?.id || null,
            connectedConnections: Array.from(connectedConnections || []), // Save all connected DBs
            tabs: Array.from(this.tabs.values()).map(tab => ({
                id: tab.id,
                type: tab.type,
                title: tab.title,
                connectionId: tab.connectionId,
                state: {
                    ...tab.state,
                    results: null  // Don't persist results (too large)
                }
            })),
            activeTabsByConnection: activeTabsByConnection
        };
    }

    /**
     * Load session from localStorage
     * @returns {object|null} Session object or null
     */
    loadFromStorage() {
        try {
            const stored = localStorage.getItem(this.SESSION_KEY);
            if (!stored) return null;

            const session = JSON.parse(stored);

            // Check version
            if (session.version !== 1) {
                console.warn('Session version mismatch, clearing session');
                localStorage.removeItem(this.SESSION_KEY);
                return null;
            }

            // Restore tabs
            session.tabs.forEach(tabData => {
                const tab = {
                    id: tabData.id,
                    type: tabData.type,
                    title: tabData.title,
                    connectionId: tabData.connectionId,
                    state: tabData.state,
                    editor: null  // Will be initialized when tab is shown
                };

                this.tabs.set(tab.id, tab);

                if (!this.tabsByConnection.has(tab.connectionId)) {
                    this.tabsByConnection.set(tab.connectionId, new Set());
                }
                this.tabsByConnection.get(tab.connectionId).add(tab.id);

                // Update counter to avoid ID collisions
                const tabNum = parseInt(tab.id.replace('tab_', ''));
                if (tabNum >= this.tabIdCounter) {
                    this.tabIdCounter = tabNum + 1;
                }
            });

            // Restore active tab per connection mapping
            if (session.activeTabsByConnection) {
                Object.entries(session.activeTabsByConnection).forEach(([connId, tabId]) => {
                    this.activeTabByConnection.set(connId, tabId);
                });
            }

            return session;
        } catch (e) {
            console.error('Error loading session:', e);
            return null;
        }
    }

    /**
     * Save tab state
     * @param {string} tabId - Tab ID
     * @param {object} state - State object to save
     */
    saveTabState(tabId, state) {
        const tab = this.tabs.get(tabId);
        if (tab) {
            tab.state = { ...tab.state, ...state };
            this.persistToStorage();
        }
    }

    /**
     * Setup global keyboard shortcuts
     */
    setupGlobalKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Cmd/Ctrl + S - Save changes in table tabs
            if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                e.preventDefault();

                if (!this.activeTabId) return;

                const activeTab = this.tabs.get(this.activeTabId);
                if (!activeTab) return;

                // Check if it's a table tab with save button visible
                if (activeTab.type === 'table') {
                    const saveBtn = document.querySelector(`[data-tab-id="${activeTab.id}"][data-action="save-changes"]`);
                    if (saveBtn && saveBtn.style.display !== 'none') {
                        saveBtn.click();
                    }
                }
            }

            // Cmd/Ctrl + W - Close current tab
            else if ((e.metaKey || e.ctrlKey) && e.key === 'w') {
                if (this.activeTabId) {
                    e.preventDefault();
                    this.closeTab(this.activeTabId);
                }
            }

            // Cmd/Ctrl + T - New query tab
            else if ((e.metaKey || e.ctrlKey) && e.key === 't') {
                e.preventDefault();
                const activeConn = window.app?.connectionManager?.getActiveConnection();
                if (activeConn) {
                    this.createTab('query', activeConn.id, { query: '' });
                }
            }

            // Cmd/Ctrl + Enter - Execute query
            else if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();

                if (!this.activeTabId) return;

                const activeTab = this.tabs.get(this.activeTabId);
                if (!activeTab) return;

                if (activeTab.type === 'query') {
                    this.executeQuery(activeTab.id);
                }
            }

            // Cmd/Ctrl + R - Refresh/reload table data
            else if ((e.metaKey || e.ctrlKey) && e.key === 'r') {
                e.preventDefault();

                if (!this.activeTabId) return;

                const activeTab = this.tabs.get(this.activeTabId);
                if (!activeTab) return;

                if (activeTab.type === 'table') {
                    this.loadTableData(activeTab);
                }
            }

            // Cmd/Ctrl + Left Arrow - Previous page (query results or table data)
            else if ((e.metaKey || e.ctrlKey) && e.key === 'ArrowLeft') {
                e.preventDefault();

                if (!this.activeTabId) return;

                const activeTab = this.tabs.get(this.activeTabId);
                if (!activeTab) return;

                if (activeTab.type === 'query' && activeTab.queryPagination) {
                    if (activeTab.queryPagination.currentPage > 1) {
                        activeTab.queryPagination.currentPage--;
                        this.renderQueryResultsPage(activeTab);
                    }
                } else if (activeTab.type === 'table' && activeTab.state.page > 1) {
                    activeTab.state.page--;
                    this.loadTableData(activeTab);
                }
            }

            // Cmd/Ctrl + Right Arrow - Next page (query results or table data)
            else if ((e.metaKey || e.ctrlKey) && e.key === 'ArrowRight') {
                e.preventDefault();

                if (!this.activeTabId) return;

                const activeTab = this.tabs.get(this.activeTabId);
                if (!activeTab) return;

                if (activeTab.type === 'query' && activeTab.queryResult && activeTab.queryPagination) {
                    const totalPages = Math.ceil(activeTab.queryResult.rows.length / activeTab.queryPagination.rowsPerPage);
                    if (activeTab.queryPagination.currentPage < totalPages) {
                        activeTab.queryPagination.currentPage++;
                        this.renderQueryResultsPage(activeTab);
                    }
                } else if (activeTab.type === 'table') {
                    // For table tabs, just increment (backend handles max)
                    activeTab.state.page++;
                    this.loadTableData(activeTab);
                }
            }
        });
    }

    /**
     * Show a notification toast message
     * @param {string} message - The message to display
     * @param {string} type - 'success', 'error', 'info', 'warning'
     */
    showNotification(message, type = 'info') {
        // Toasts stack in one container; an identical message already on screen is not repeated
        let stack = document.getElementById('toast-stack');
        if (!stack) {
            stack = document.createElement('div');
            stack.id = 'toast-stack';
            stack.setAttribute('role', 'status');
            stack.setAttribute('aria-live', 'polite');
            document.body.appendChild(stack);
        }
        if ([...stack.children].some(n => n.textContent === message)) return;

        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;
        stack.appendChild(notification);

        // Trigger animation
        setTimeout(() => {
            notification.classList.add('notification-show');
        }, 10);

        // Remove after 3 seconds
        setTimeout(() => {
            notification.classList.remove('notification-show');
            setTimeout(() => notification.remove(), 300);
        }, type === 'error' ? 6000 : 3000);
    }
}

