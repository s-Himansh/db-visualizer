// Names and error text from databases are untrusted: escape before putting them in innerHTML
function escapeHtml(value) {
    const el = document.createElement('div');
    el.textContent = value ?? '';
    return el.innerHTML;
}

// Main Application
class DatabaseVisualizer {
    constructor() {
        this.connectionManager = new ConnectionManager();
        this.tabManager = null;
        this.queryEditor = null;
        this.databaseTree = {};
        this.init();
    }

    async init() {
        // Initialize query editor when ready
        if (typeof QueryEditor !== 'undefined') {
            this.queryEditor = new QueryEditor(this.connectionManager);
        }

        // Initialize tab manager
        if (typeof TabManager !== 'undefined') {
            this.tabManager = new TabManager();
        }
        this.relations = new RelationsManager();
        this.palette = new CommandPalette();
        this.insights = new ColumnInsights();
        this.assistant = new AIAssistant();

        // Event listeners
        document.getElementById('refresh-btn').addEventListener('click', () => this.refreshDatabaseTree());

        // Initialize sidebar resize
        this.initSidebarResize();

        this.initEscapeKey();
        this.initWelcome();

        // Load saved connections
        await this.connectionManager.loadConnections();

        // Restore session from localStorage
        if (this.tabManager) {
            const session = this.tabManager.loadFromStorage();

            if (session) {
                // Auto-reconnect to ALL previously connected connections
                const connectedConns = session.connectedConnections || [];

                for (const connId of connectedConns) {
                    const connExists = this.connectionManager.connections
                        .some(c => c.id === connId);

                    if (connExists) {
                        // Reconnect (don't switch yet)
                        await this.connectionManager.connect(connId);
                    }
                }

                // Switch to last active connection
                if (session.lastActiveConnection &&
                    this.connectionManager.connectedConnections.has(session.lastActiveConnection)) {
                    this.connectionManager.switchToConnection(session.lastActiveConnection);
                }
            }
        }
    }

    async loadDatabaseTree(connectionId) {
        try {
            // Load databases
            const response = await fetch(`/api/databases?connection_id=${connectionId}`);
            const data = await response.json();

            if (data.success) {
                this.renderDatabaseTree(connectionId, data.databases);

                // Database selectors are now per-tab, populated by TabManager
            } else {
                console.error('Error loading databases:', data.error);
                // Show error in sidebar
                const header = document.getElementById('current-database-name');
                header.textContent = 'Error loading database';
                const tablesContent = document.getElementById('tables-content');
                tablesContent.innerHTML = `<div class="tree-message error">
                    ${escapeHtml(data.error)}
                    <button class="btn btn-sm btn-primary" onclick="window.app.connectionManager.connect('${escapeHtml(connectionId)}')">Reconnect</button>
                </div>`;
            }
        } catch (error) {
            console.error('Error loading database tree:', error);
        }
    }

    renderDatabaseTree(connectionId, databases) {
        if (!databases || databases.length === 0) {
            const header = document.getElementById('current-database-name');
            header.textContent = 'No Database';

            const tablesContent = document.getElementById('tables-content');
            tablesContent.innerHTML = '<div class="tree-message">This connection has no database to show.</div>';
            return;
        }

        // Auto-load first database and its tables
        if (databases.length > 0) {
            this.loadTablesInPanel(connectionId, databases[0]);
        }
    }


    async loadTablesInPanel(connectionId, dbName) {
        // Update header with database name
        const header = document.getElementById('current-database-name');
        header.textContent = dbName.split(/[\\/]/).pop() || dbName;
        header.title = dbName;
        const mapBtn = document.getElementById('open-map-btn');
        mapBtn.disabled = false;
        mapBtn.onclick = () => this.openSchemaMap(connectionId, dbName);
        mapBtn.dataset.database = dbName;
        mapBtn.dataset.connection = connectionId;

        const container = document.getElementById('tables-content');
        container.innerHTML = '<div class="spinner"></div>';

        try {
            const response = await fetch(`/api/tables?connection_id=${connectionId}&database=${encodeURIComponent(dbName)}`);
            const data = await response.json();

            if (data.success) {
                container.innerHTML = '';

                if (data.tables.length === 0) {
                    container.innerHTML = '<div class="tree-message">No tables in this database yet.</div>';
                    return;
                }

                data.tables.forEach(table => {
                    const tableItem = document.createElement('div');
                    tableItem.className = 'tree-item';
                    tableItem.tabIndex = 0;
                    tableItem.innerHTML = `
                        <span class="tree-icon ${table.type === 'view' ? 'is-view' : 'is-table'}" title="${table.type === 'view' ? 'View' : 'Table'}"></span>
                        <span class="tree-label">${escapeHtml(table.name)}</span>
                        ${table.rows != null ? `<span class="tree-count" title="${table.rows_estimated ? 'Estimated row count' : 'Row count'}">${table.rows_estimated ? '~' : ''}${this.formatCount(table.rows)}</span>` : ''}
                    `;

                    // Click opens the data; right-click (or the keyboard menu key) offers schema/copy
                    tableItem.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.openTableData(connectionId, dbName, table.name);
                    });
                    tableItem.addEventListener('keydown', (e) => {
                        if (e.key === 'Enter') this.openTableData(connectionId, dbName, table.name);
                    });
                    tableItem.addEventListener('contextmenu', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        this.showTableContextMenu(connectionId, dbName, table.name, e);
                    });

                    container.appendChild(tableItem);
                });
            }
        } catch (error) {
            console.error('Error loading tables:', error);
            container.innerHTML = '<div class="tree-message error">Could not load tables. Check the connection and refresh.</div>';
        }
    }

    showTableContextMenu(connectionId, database, tableName, event) {
        // Remove any existing context menus first
        const existingMenus = document.querySelectorAll('.table-context-menu');
        existingMenus.forEach(m => m.remove());

        // Create new menu
        const menu = document.createElement('div');
        menu.className = 'table-context-menu';
        menu.style.left = Math.min(event.clientX, window.innerWidth - 180) + 'px';
        menu.style.top = Math.min(event.clientY, window.innerHeight - 120) + 'px';

        const options = [
            { label: 'View Data', action: () => this.openTableData(connectionId, database, tableName) },
            { label: 'View Schema', action: () => this.openTableSchema(connectionId, database, tableName) },
            { label: 'Copy Name', action: () => navigator.clipboard.writeText(tableName) }
        ];

        options.forEach(opt => {
            const item = document.createElement('div');
            item.textContent = opt.label;
            item.className = 'context-menu-item';
            item.addEventListener('click', () => {
                opt.action();
                menu.remove();
            });
            menu.appendChild(item);
        });

        document.body.appendChild(menu);

        // Remove menu on click outside
        const closeMenu = (e) => {
            if (!menu.contains(e.target)) {
                menu.remove();
                document.removeEventListener('click', closeMenu);
            }
        };
        setTimeout(() => document.addEventListener('click', closeMenu), 100);
    }

    formatCount(n) {
        return n >= 10000
            ? new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
            : Number(n).toLocaleString();
    }

    initEscapeKey() {
        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') return;
            const menu = document.querySelector('.table-context-menu');
            if (menu) { menu.remove(); return; }
            // Close only the topmost modal, through its own close button so each modal cleans up
            const open = [...document.querySelectorAll('.modal.active')].pop();
            if (!open) return;
            const closer = open.querySelector('.modal-close');
            if (closer) closer.click(); else open.classList.remove('active');
        });
    }

    // Empty-state guidance in the main area; shown whenever no tab is open
    initWelcome() {
        const main = document.getElementById('main-content');
        const welcome = document.createElement('div');
        welcome.id = 'welcome';
        main.prepend(welcome);
        const render = () => this.renderWelcome();
        // disconnecting hides a connection's tabs rather than removing them, so watch visibility as well
        new MutationObserver(render).observe(document.getElementById('tabs-header'), { childList: true, subtree: true, attributes: true, attributeFilter: ['style'] });
        this.renderWelcome = this.renderWelcome.bind(this);
        document.addEventListener('connections-changed', render);
        render();
    }

    // Creates the sample shop database (once) and connects to it
    async openSample() {
        try {
            const result = await (await fetch('/api/sample', { method: 'POST' })).json();
            if (!result.success) throw new Error(result.error);
            await this.connectionManager.loadConnections();
            await this.connectionManager.connect(result.id);
            ui.notify('The sample shop is open. Click Map to see how its tables relate, or follow the arrows in a table.', 'info');
        } catch (err) {
            ui.notify(`Could not open the sample database: ${err.message}`, 'error');
        }
    }

    renderWelcome() {
        const welcome = document.getElementById('welcome');
        if (!welcome) return;
        const hasTabs = [...document.querySelectorAll('#tabs-header .tab')].some(t => t.style.display !== 'none');
        welcome.style.display = hasTabs ? 'none' : '';
        if (hasTabs) return;

        const conns = this.connectionManager.connections || [];
        if (conns.length === 0) {
            welcome.innerHTML = `
                <h2>Connect your first database</h2>
                <p>Browse tables, follow relationships, edit rows and run queries on SQLite, PostgreSQL, MySQL, SQL Server, Oracle, MongoDB, Redis and Cassandra.</p>
                <div class="welcome-actions">
                    <button class="btn btn-primary" id="welcome-new">Add a connection</button>
                    <button class="btn" id="welcome-sample">Try a sample database</button>
                </div>
                <p class="welcome-note">No database handy? The sample is a small online shop with orders, products and customers, stored on this computer.</p>`;
            welcome.querySelector('#welcome-new').addEventListener('click', () => this.connectionManager.showConnectionModal());
            welcome.querySelector('#welcome-sample').addEventListener('click', () => this.openSample());
        } else {
            welcome.innerHTML = `
                <h2>Pick a database to open</h2>
                <p>Your saved connections. Connecting loads its tables in the sidebar.</p>
                <div class="welcome-list">${conns.map(c => `
                    <button class="welcome-conn" data-id="${escapeHtml(c.id)}">
                        <span class="welcome-conn-name">${escapeHtml(c.name)}</span>
                        <span class="connection-type">${escapeHtml(c.type)}</span>
                    </button>`).join('')}</div>
                <div class="welcome-actions">
                    <button class="btn" id="welcome-new">Add a connection</button>
                    ${conns.some(c => c.sample) ? '' : '<button class="btn" id="welcome-sample">Try a sample database</button>'}
                </div>`;
            const sample = welcome.querySelector('#welcome-sample');
            if (sample) sample.addEventListener('click', () => this.openSample());
            welcome.querySelectorAll('.welcome-conn').forEach(b =>
                b.addEventListener('click', () => this.connectionManager.connect(b.dataset.id)));
            welcome.querySelector('#welcome-new').addEventListener('click', () => this.connectionManager.showConnectionModal());
        }
    }

    // Opening the same table twice (a double-click, say) should show the tab you already have
    focusExistingTab(type, connectionId, database, tableName, filter) {
        const same = (a, b) => JSON.stringify(a || null) === JSON.stringify(b || null);
        for (const [id, tab] of this.tabManager.tabs) {
            if (tab.type === type && tab.connectionId === connectionId &&
                tab.state.database === database && tab.state.tableName === tableName &&
                (type !== 'table' || same(tab.state.filter, filter))) {
                this.tabManager.switchTab(id);
                return true;
            }
        }
        return false;
    }

    // `filter` ({column, value}) opens only the rows where that column equals that value: how links are followed
    openTableData(connectionId, database, tableName, filter) {
        if (this.tabManager && this.focusExistingTab('table', connectionId, database, tableName, filter)) return;
        if (this.tabManager) {
            this.tabManager.createTab('table', connectionId, {
                tableName: tableName,
                database: database,
                page: 1,
                pageSize: 100,
                ...(filter ? { filter } : {})
            });
        }
    }

    openSchemaMap(connectionId, database) {
        if (!this.tabManager) return;
        for (const [id, tab] of this.tabManager.tabs) {
            if (tab.type === 'map' && tab.connectionId === connectionId && tab.state.database === database) {
                this.tabManager.switchTab(id);
                return;
            }
        }
        this.tabManager.createTab('map', connectionId, { database });
    }

    async openTableSchema(connectionId, database, tableName) {
        // Create a schema tab instead of trying to display in current tab
        if (this.tabManager && this.focusExistingTab('schema', connectionId, database, tableName)) return;
        if (this.tabManager) {
            this.tabManager.createTab('schema', connectionId, {
                tableName: tableName,
                database: database
            });
        }
    }


    async refreshDatabaseTree() {
        const activeConn = this.connectionManager.getActiveConnection();
        if (activeConn) {
            // Try to reconnect first to ensure connection is alive
            try {
                this.tabManager?.invalidateSchemaCache(activeConn.id);
                this.relations.invalidate(activeConn.id);  // a refresh must pick up new tables and columns
                await this.connectionManager.connect(activeConn.id);
                // Then load the database tree
                this.loadDatabaseTree(activeConn.id);
            } catch (error) {
                console.error('Error refreshing database tree:', error);
                ui.notify('Failed to refresh. Connection may have been lost. Try reconnecting.');
            }
        }
    }

    clearDatabaseTree() {
        const header = document.getElementById('current-database-name');
        const tablesList = document.getElementById('tables-content');

        if (header) header.textContent = 'No database selected';
        if (tablesList) tablesList.innerHTML = '';
        const mapBtn = document.getElementById('open-map-btn');
        if (mapBtn) { mapBtn.disabled = true; delete mapBtn.dataset.database; delete mapBtn.dataset.connection; }

        // Database selectors are now per-tab, managed by TabManager
    }

    initSidebarResize() {
        const sidebar = document.getElementById('sidebar');
        const resizeHandle = document.getElementById('sidebar-resize-handle');

        if (!sidebar || !resizeHandle) return;

        let isResizing = false;
        let startX = 0;
        let startWidth = 0;

        // Load saved width from localStorage
        const savedWidth = localStorage.getItem('sidebar-width');
        if (savedWidth) {
            sidebar.style.width = savedWidth + 'px';
        }

        resizeHandle.addEventListener('mousedown', (e) => {
            isResizing = true;
            startX = e.clientX;
            startWidth = sidebar.offsetWidth;

            resizeHandle.classList.add('resizing');
            document.body.classList.add('sidebar-resizing');

            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!isResizing) return;

            const delta = e.clientX - startX;
            const newWidth = startWidth + delta;

            // Enforce min/max constraints
            if (newWidth >= 200 && newWidth <= 600) {
                sidebar.style.width = newWidth + 'px';
            }
        });

        document.addEventListener('mouseup', () => {
            if (isResizing) {
                isResizing = false;
                resizeHandle.classList.remove('resizing');
                document.body.classList.remove('sidebar-resizing');

                // Save width to localStorage
                localStorage.setItem('sidebar-width', sidebar.offsetWidth);
            }
        });
    }
}

// Initialize app when DOM is ready
let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new DatabaseVisualizer();
    window.app = app; // Make it globally accessible
});
