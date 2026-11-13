// Connection Manager
class ConnectionManager {
    constructor() {
        this.connections = [];
        this.activeConnection = null;
        this.connectedConnections = new Set(); // Track all connected databases
        this.init();
    }

    init() {
        // Connections will be loaded by app.js with proper await

        // Event listeners
        document.getElementById('manage-connections-btn').addEventListener('click', () => this.showConnectionsManager());
        document.addEventListener('keydown', (e) => {
            const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
            if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey && !e.altKey && this.focusConnectionSearch()) e.preventDefault();
        });
        document.getElementById('new-connection-btn-manager').addEventListener('click', () => this.showConnectionModal());
        document.getElementById('connections-manager-close').addEventListener('click', () => this.hideConnectionsManager());
        document.getElementById('connection-modal-close').addEventListener('click', () => this.hideConnectionModal());
        document.getElementById('cancel-connection-btn').addEventListener('click', () => this.hideConnectionModal());
        document.getElementById('connection-form').addEventListener('submit', (e) => this.saveConnection(e));
        document.getElementById('test-connection-btn').addEventListener('click', () => this.testConnection());

        // Type change handler
        document.querySelector('[name="type"]').addEventListener('change', (e) => this.updateFormFields(e.target.value));

        // A production connection starts read-only: the safe default, easy to undo for the rare edit
        document.getElementById('environment-select').addEventListener('change', (e) => {
            const production = e.target.value === 'production';
            document.getElementById('environment-hint').style.display = production ? '' : 'none';
            if (production) document.getElementById('read-only-checkbox').checked = true;
        });

        // SSH tunnel fields
        document.getElementById('ssh-enabled-checkbox').addEventListener('change', () => this.toggleSshFields());
        document.getElementById('ssh-auth-select').addEventListener('change', () => this.toggleSshFields());

        // SSL checkbox handler
        document.getElementById('use-ssl-checkbox').addEventListener('change', (e) => this.toggleSslCertFields(e.target.checked));

        // Keyboard shortcuts for connection switching
        document.addEventListener('keydown', (e) => {
            // Cmd/Ctrl + 1-9 to switch to connection 1-9
            if ((e.metaKey || e.ctrlKey) && e.key >= '1' && e.key <= '9' && !e.shiftKey) {
                e.preventDefault();
                const index = parseInt(e.key) - 1;
                if (this.connections[index]) {
                    this.connect(this.connections[index].id);
                }
            }
            // Cmd/Ctrl + Shift + ] for next connection
            else if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === ']') {
                e.preventDefault();
                this.switchToNextConnection();
            }
            // Cmd/Ctrl + Shift + [ for previous connection
            else if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === '[') {
                e.preventDefault();
                this.switchToPreviousConnection();
            }
        });
    }

    async loadConnections() {
        try {
            const response = await fetch('/api/connections');
            const data = await response.json();

            this.connections = data.connections || [];
            this.renderConnections();
        } catch (error) {
            console.error('Error loading connections:', error);
        }
    }

    renderConnections() {
        document.dispatchEvent(new CustomEvent('connections-changed'));
        this.renderGrid(document.getElementById('connections-list'), 'manager');
    }

    // ---- the connection grid: every saved connection visible at once, grouped, searchable ---------------------
    // One renderer for the Connections window and for the "Pick a database" screen.

    static TYPE_COLOR = { mysql: '#d9822b', postgresql: '#336791', sqlite: '#5b6abf', sqlserver: '#a4373a', oracle: '#c0392b',
                          mongodb: '#3f9142', redis: '#c0392b', cassandra: '#1287b1' };
    static TYPE_ABBR = { mysql: 'My', postgresql: 'Pg', sqlite: 'Sq', sqlserver: 'Ms', oracle: 'Or', mongodb: 'Mg', redis: 'Rd', cassandra: 'Ca' };
    static GROUPS = [['production', 'Production'], ['staging', 'Staging'], ['development', 'Development'], ['local', 'Local'], ['', 'Not tagged']];

    // Where a connection points, in a few words: enough to tell two with the same name apart
    connWhere(conn) {
        if (conn.type === 'sqlite') return (conn.database || '').split(/[\\/]/).filter(Boolean).pop() || 'SQLite file';
        const host = conn.host ? conn.host + (conn.port ? ':' + conn.port : '') : '';
        return [host, conn.database].filter(Boolean).join(' / ') || conn.connection_url || '';
    }

    timeAgo(seconds) {
        if (!seconds) return '';
        const d = Math.max(0, Date.now() / 1000 - seconds);
        const units = [[31536000, 'y'], [2592000, 'mo'], [604800, 'w'], [86400, 'd'], [3600, 'h'], [60, 'm']];
        for (const [size, label] of units) if (d >= size) return Math.floor(d / size) + label + ' ago';
        return 'just now';
    }

    connectionTile(conn, mode) {
        const isConnected = this.connectedConnections.has(conn.id);
        const isActive = this.activeConnection?.id === conn.id;
        const item = document.createElement('div');
        // The Connections window keeps its original class names; the picker screen's tiles are separate so the two
        // never answer to the same selector while both are in the page.
        item.className = (mode === 'manager' ? 'connection-item conn-tile' : 'conn-tile') + (isActive ? ' active' : isConnected ? ' connected' : '');
        item.tabIndex = 0;
        item.dataset.id = conn.id;
        const color = ConnectionManager.TYPE_COLOR[conn.type] || '#6b7683';
        const where = this.connWhere(conn);
        const used = this.timeAgo(conn.last_used);
        item.innerHTML = `
            <div class="connection-info">
                <span class="conn-avatar" style="background:${color}">${this.esc(ConnectionManager.TYPE_ABBR[conn.type] || (conn.type || '?').slice(0, 2))}</span>
                <div class="conn-text">
                    <div class="connection-name">${isConnected ? '<span class="conn-dot" title="Connected"></span>' : ''}${this.esc(conn.name)}</div>
                    <div class="conn-where">${this.esc(where) || '&nbsp;'}</div>
                    <div class="conn-tags">
                        <span class="connection-type">${this.esc(conn.type)}</span>
                        ${this.envTag(conn)}
                        ${conn.read_only ? '<span class="connection-type ro" title="Writes are blocked on this connection">read-only</span>' : ''}
                        ${used ? `<span class="conn-used" title="Last opened">${this.esc(used)}</span>` : ''}
                    </div>
                </div>
            </div>
            ${mode === 'manager' ? `<div class="connection-actions">
                <button class="connect-btn" title="${isConnected ? 'Disconnect' : 'Connect'}">${isConnected ? 'Disconnect' : 'Connect'}</button>
                <button class="edit-btn" title="Edit connection" aria-label="Edit connection">Edit</button>
                <button class="delete-btn" title="Delete connection" aria-label="Delete connection">Delete</button>
            </div>` : ''}`;

        // user text goes in as properties, never into attribute markup
        item.querySelector('.conn-where').title = where;
        const connectBtn = item.querySelector('.connect-btn');
        if (connectBtn) { connectBtn.dataset.id = conn.id; item.querySelector('.delete-btn').dataset.id = conn.id; }
        const open = () => {
            if (isConnected) this.switchToConnection(conn.id); else this.connect(conn.id);
            if (mode === 'manager') this.hideConnectionsManager();
        };
        item.querySelector('.connection-info').addEventListener('click', (e) => { e.stopPropagation(); open(); });
        if (connectBtn) {
            item.querySelector('.edit-btn').addEventListener('click', (e) => { e.stopPropagation(); this.editConnection(conn); });
            connectBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (this.connectedConnections.has(conn.id)) this.disconnect(conn.id); else this.connect(conn.id);
            });
            item.querySelector('.delete-btn').addEventListener('click', (e) => { e.stopPropagation(); this.deleteConnection(conn.id); });
        }
        item.addEventListener('keydown', (e) => {
            if (e.target !== item) return;
            if (e.key === 'Enter') { e.preventDefault(); open(); }
        });
        return item;
    }

    renderGrid(container, mode = 'manager') {
        if (!container) return;
        container.innerHTML = '';
        if (this.connections.length === 0) {
            container.innerHTML = `
                <div class="tree-message">
                    <strong>No connections yet</strong><br>
                    Choose New connection to add your first database.
                </div>
            `;
            return;
        }
        this.collapsed = this.collapsed || new Set();
        const search = document.createElement('input');
        search.type = 'search';
        search.className = 'conn-search';
        search.placeholder = `Search ${this.connections.length} connection${this.connections.length === 1 ? '' : 's'}…`;
        search.setAttribute('aria-label', 'Search connections');
        search.autocomplete = 'off';
        search.setAttribute('autocapitalize', 'off');
        search.setAttribute('autocorrect', 'off');
        search.spellcheck = false;
        const groupsEl = document.createElement('div');
        groupsEl.className = 'conn-groups';
        container.append(search, groupsEl);

        const draw = () => {
            const q = search.value.trim().toLowerCase();
            const match = (c) => !q || [c.name, c.type, c.environment, c.host, c.database].some(v => String(v ?? '').toLowerCase().includes(q));
            const shown = this.connections.filter(match);
            const recent = (a, b) => (b.last_used || 0) - (a.last_used || 0) || String(a.name).localeCompare(String(b.name));
            const open = shown.filter(c => this.connectedConnections.has(c.id)).sort(recent);
            const rest = shown.filter(c => !this.connectedConnections.has(c.id));
            const groups = [['open', 'Open now', open]];
            const known = new Set(ConnectionManager.GROUPS.map(g => g[0]));
            for (const [env, label] of ConnectionManager.GROUPS) {
                groups.push([env || 'none', label, rest.filter(c => (known.has(c.environment || '') ? (c.environment || '') : '') === env).sort(recent)]);
            }
            groupsEl.innerHTML = '';
            if (!shown.length) {
                groupsEl.innerHTML = `<div class="tree-message">Nothing matches "${this.esc(search.value.trim())}".</div>`;
                return;
            }
            for (const [key, label, list] of groups) {
                if (!list.length) continue;
                const closed = !q && this.collapsed.has(key);
                const section = document.createElement('section');
                section.className = 'conn-group';
                const head = document.createElement('button');
                head.type = 'button';
                head.className = 'conn-group-head';
                head.setAttribute('aria-expanded', String(!closed));
                head.innerHTML = `<span class="conn-caret">${closed ? '▸' : '▾'}</span><span>${this.esc(label)}</span><span class="conn-count">${list.length}</span>`;
                head.addEventListener('click', () => {
                    if (this.collapsed.has(key)) this.collapsed.delete(key); else this.collapsed.add(key);
                    draw();
                });
                section.appendChild(head);
                if (!closed) {
                    const grid = document.createElement('div');
                    grid.className = 'conn-grid';
                    list.forEach(c => grid.appendChild(this.connectionTile(c, mode)));
                    section.appendChild(grid);
                }
                groupsEl.appendChild(section);
            }
        };
        search.addEventListener('input', draw);

        // Arrow keys walk the tiles, Enter opens one, Escape returns to the search box
        container.addEventListener('keydown', (e) => {
            const tiles = [...container.querySelectorAll('.conn-tile')];
            const at = tiles.indexOf(document.activeElement);
            const step = { ArrowDown: 'down', ArrowUp: 'up', ArrowRight: 1, ArrowLeft: -1 }[e.key];
            if (step === undefined) {
                if (e.key === 'Escape' && at >= 0) { e.preventDefault(); e.stopPropagation(); search.focus(); }
                return;
            }
            if (document.activeElement === search && (step === 'down' || step === 1)) {
                if (tiles[0]) { e.preventDefault(); tiles[0].focus(); }
                return;
            }
            if (at < 0) return;
            e.preventDefault();
            let to = at;
            if (step === 1 || step === -1) to = at + step;
            else {                       // up/down: the nearest tile in the row above or below, in the same column
                const here = tiles[at].getBoundingClientRect();
                const rows = tiles.filter(t => (step === 'down' ? t.getBoundingClientRect().top > here.top + 4 : t.getBoundingClientRect().top < here.top - 4));
                if (rows.length) {
                    const target = step === 'down' ? Math.min(...rows.map(t => t.getBoundingClientRect().top)) : Math.max(...rows.map(t => t.getBoundingClientRect().top));
                    const inRow = rows.filter(t => Math.abs(t.getBoundingClientRect().top - target) < 4);
                    to = tiles.indexOf(inRow.reduce((best, t) => Math.abs(t.getBoundingClientRect().left - here.left) < Math.abs(best.getBoundingClientRect().left - here.left) ? t : best));
                } else if (step === 'up') { search.focus(); return; }
            }
            if (tiles[to]) tiles[to].focus();
        });
        draw();
    }

    // "/" jumps to the search box of whichever connection grid is on screen
    focusConnectionSearch() {
        const boxes = [...document.querySelectorAll('.conn-search')].filter(b => b.offsetParent !== null);
        if (boxes.length) { boxes[0].focus(); boxes[0].select(); return true; }
        return false;
    }

    showConnectionsManager() {
        const modal = document.getElementById('connections-manager-modal');
        modal.classList.add('active');
        this.renderConnections(); // Refresh connections list

        // Close on background click
        const closeOnBgClick = (e) => {
            if (e.target === modal) {
                this.hideConnectionsManager();
                modal.removeEventListener('click', closeOnBgClick);
            }
        };
        modal.addEventListener('click', closeOnBgClick);
    }

    hideConnectionsManager() {
        const modal = document.getElementById('connections-manager-modal');
        modal.classList.remove('active');
    }

    showConnectionModal(connectionData = null) {
        // Hide the Connections Manager modal first
        this.hideConnectionsManager();

        const modal = document.getElementById('connection-modal');
        const form = document.getElementById('connection-form');

        // Reset form
        form.reset();
        this.editingId = connectionData ? connectionData.id : null;
        document.getElementById('connection-modal-title').textContent = connectionData ? 'Edit connection' : 'New connection';

        if (connectionData) {
            // Editing existing connection
            form.elements['name'].value = connectionData.name || '';
            form.elements['type'].value = connectionData.type || '';
            form.elements['host'].value = connectionData.host || '';
            form.elements['port'].value = connectionData.port || '';
            form.elements['database'].value = connectionData.database || '';
            form.elements['username'].value = connectionData.username || '';
            form.elements['connection_url'].value = connectionData.connection_url || '';
            form.elements['use_ssl'].checked = connectionData.use_ssl || false;
            form.elements['read_only'].checked = !!connectionData.read_only;
            form.elements['environment'].value = connectionData.environment || '';
            form.elements['ssh_enabled'].checked = !!connectionData.ssh_enabled;
            form.elements['ssh_host'].value = connectionData.ssh_host || '';
            form.elements['ssh_port'].value = connectionData.ssh_port || '';
            form.elements['ssh_user'].value = connectionData.ssh_user || '';
            form.elements['ssh_auth'].value = connectionData.ssh_auth || 'password';
            form.elements['ssh_key_path'].value = connectionData.ssh_key_path || '';
            // secrets are never sent back to the page; leaving them blank keeps the saved ones
            // Don't populate password for security
        }

        // Update form fields based on type
        if (form.elements['type'].value) {
            this.updateFormFields(form.elements['type'].value);
        }

        // Show/hide SSL certificate fields based on checkbox
        this.toggleSslCertFields(form.elements['use_ssl'].checked);
        this.toggleSshFields();

        modal.classList.add('active');
    }

    hideConnectionModal() {
        const modal = document.getElementById('connection-modal');
        modal.classList.remove('active');

        // Re-show the Connections Manager if it was previously open
        // (This happens when user cancels the connection form)
        const connectionsManager = document.getElementById('connections-manager-modal');
        if (!connectionsManager.classList.contains('active')) {
            this.showConnectionsManager();
        }
    }

    editConnection(connectionData) {
        this.showConnectionModal(connectionData);
    }

    sshFormData(formData) {
        const on = formData.get('ssh_enabled') === 'on';
        return {
            ssh_enabled: on,
            ssh_host: formData.get('ssh_host'),
            ssh_port: parseInt(formData.get('ssh_port')) || null,
            ssh_user: formData.get('ssh_user'),
            ssh_auth: formData.get('ssh_auth'),
            ssh_password: formData.get('ssh_password'),
            ssh_key_path: formData.get('ssh_key_path'),
            ssh_passphrase: formData.get('ssh_passphrase')
        };
    }

    // Show the SSH fields only when they apply: not for SQLite (a file), and only when the box is ticked
    toggleSshFields() {
        const form = document.getElementById('connection-form');
        const isFile = form.elements['type'].value === 'sqlite';
        document.getElementById('ssh-toggle-group').style.display = isFile ? 'none' : '';
        const on = !isFile && form.elements['ssh_enabled'].checked;
        document.getElementById('ssh-fields').style.display = on ? '' : 'none';
        const key = form.elements['ssh_auth'].value === 'key';
        document.getElementById('ssh-password-group').style.display = key ? 'none' : '';
        document.getElementById('ssh-key-group').style.display = key ? '' : 'none';
        document.getElementById('ssh-passphrase-group').style.display = key ? '' : 'none';
    }

    // First contact with an SSH server: show its fingerprint and let the user decide. Cancel is the default.
    confirmHostKey(info) {
        return ui.confirm(
            `You are connecting to the SSH server ${info.host}:${info.port} for the first time.\n\n` +
            `Its fingerprint is:\n${info.fingerprint}\n\n` +
            'Only continue if this matches the fingerprint your server administrator gave you.',
            { title: 'Trust this SSH server?', confirmLabel: 'Trust and connect', safeDefault: true });
    }

    // Connection names are user input rendered through innerHTML
    esc(value) {
        const el = document.createElement('div');
        el.textContent = value ?? '';
        return el.innerHTML;
    }

    updateFormFields(type) {
        queueMicrotask(() => this.toggleSshFields());
        const hostGroup = document.getElementById('host-group');
        const portGroup = document.getElementById('port-group');
        const databaseGroup = document.getElementById('database-group');
        const usernameGroup = document.getElementById('username-group');
        const passwordGroup = document.getElementById('password-group');
        const connectionUrlGroup = document.getElementById('connection-url-group');
        const sslGroup = document.getElementById('ssl-group');

        // Show/hide fields based on database type
        if (type === 'sqlite') {
            hostGroup.style.display = 'none';
            portGroup.style.display = 'none';
            usernameGroup.style.display = 'none';
            passwordGroup.style.display = 'none';
            databaseGroup.style.display = 'block';
            connectionUrlGroup.style.display = 'none';
            sslGroup.style.display = 'none';
            databaseGroup.querySelector('label').textContent = 'Database file path';
        } else if (type === 'mongodb' || type === 'redis') {
            // MongoDB and Redis support connection URL
            connectionUrlGroup.style.display = 'block';
            hostGroup.style.display = 'none';
            portGroup.style.display = 'none';
            usernameGroup.style.display = 'none';
            passwordGroup.style.display = 'none';
            databaseGroup.style.display = 'none';
            sslGroup.style.display = 'block';

            // Set placeholder based on type
            const urlInput = connectionUrlGroup.querySelector('input');
            if (type === 'mongodb') {
                urlInput.placeholder = 'mongodb://username:password@host:port/database?authSource=admin';
            } else if (type === 'redis') {
                urlInput.placeholder = 'redis://username:password@host:port/database';
            }
        } else if (type === 'cassandra') {
            hostGroup.style.display = 'block';
            portGroup.style.display = 'block';
            usernameGroup.style.display = 'block';
            passwordGroup.style.display = 'block';
            databaseGroup.style.display = 'block';
            connectionUrlGroup.style.display = 'none';
            sslGroup.style.display = 'block';
            databaseGroup.querySelector('label').textContent = 'Keyspace (optional)';
            hostGroup.querySelector('label').textContent = 'Contact Points';
            hostGroup.querySelector('input').placeholder = 'localhost or host1,host2,host3';

            // Set default port for Cassandra
            const portInput = portGroup.querySelector('input');
            if (!portInput.value) {
                portInput.value = 9042;
            }
        } else {
            hostGroup.style.display = 'block';
            portGroup.style.display = 'block';
            usernameGroup.style.display = 'block';
            passwordGroup.style.display = 'block';
            databaseGroup.style.display = 'block';
            connectionUrlGroup.style.display = 'none';
            sslGroup.style.display = 'block';
            databaseGroup.querySelector('label').textContent = 'Database';
            hostGroup.querySelector('label').textContent = 'Host';
            hostGroup.querySelector('input').placeholder = 'localhost';

            // Set default ports
            const portInput = portGroup.querySelector('input');
            const portDefaults = {
                'postgresql': 5432,
                'mysql': 3306,
                'sqlserver': 1433,
                'oracle': 1521,
                'mongodb': 27017,
                'redis': 6379
            };
            if (portDefaults[type] && !portInput.value) {
                portInput.value = portDefaults[type];
            }
        }
    }

    toggleSslCertFields(showFields) {
        const sslCertsGroup = document.getElementById('ssl-certs-group');
        const sslClientCertGroup = document.getElementById('ssl-client-cert-group');
        const sslClientKeyGroup = document.getElementById('ssl-client-key-group');

        if (showFields) {
            sslCertsGroup.style.display = 'block';
            sslClientCertGroup.style.display = 'block';
            sslClientKeyGroup.style.display = 'block';
        } else {
            sslCertsGroup.style.display = 'none';
            sslClientCertGroup.style.display = 'none';
            sslClientKeyGroup.style.display = 'none';
        }
    }

    async saveConnection(event) {
        event.preventDefault();

        const formData = new FormData(event.target);
        const connectionData = {
            name: formData.get('name'),
            type: formData.get('type'),
            host: formData.get('host'),
            port: parseInt(formData.get('port')) || null,
            database: formData.get('database'),
            username: formData.get('username'),
            password: formData.get('password'),
            connection_url: formData.get('connection_url'),
            use_ssl: formData.get('use_ssl') === 'on',
            read_only: formData.get('read_only') === 'on',
            environment: formData.get('environment') || '',
            ...this.sshFormData(formData)
        };

        // Handle certificate files if SSL is enabled and files are selected
        if (connectionData.use_ssl) {
            const caCertFile = formData.get('ca_cert');
            const clientCertFile = formData.get('client_cert');
            const clientKeyFile = formData.get('client_key');

            if (caCertFile && caCertFile.size > 0) {
                connectionData.ca_cert = await this.readFileAsBase64(caCertFile);
                connectionData.ca_cert_filename = caCertFile.name;
            }

            if (clientCertFile && clientCertFile.size > 0) {
                connectionData.client_cert = await this.readFileAsBase64(clientCertFile);
                connectionData.client_cert_filename = clientCertFile.name;
            }

            if (clientKeyFile && clientKeyFile.size > 0) {
                connectionData.client_key = await this.readFileAsBase64(clientKeyFile);
                connectionData.client_key_filename = clientKeyFile.name;
            }
        }

        try {
            // A blank password on edit means "keep the stored one" (handled server-side)
            const response = await fetch(this.editingId ? `/api/connections/${this.editingId}` : '/api/connections', {
                method: this.editingId ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(connectionData)
            });

            const result = await response.json();

            if (result.success) {
                this.hideConnectionModal();
                this.loadConnections();
                this.showConnectionsManager(); // Show the manager again after saving
                this.showStatus('Connection saved successfully', 'success');
            } else {
                this.showStatus('Failed to save connection: ' + result.error, 'error');
            }
        } catch (error) {
            console.error('Error saving connection:', error);
            this.showStatus('Error saving connection', 'error');
        }
    }

    readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result.split(',')[1]); // Remove data:... prefix
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    async deleteConnection(id) {
        if (!(await ui.confirm('Delete this connection? Its saved password is removed too. The database itself is not touched.', { title: 'Delete connection', confirmLabel: 'Delete', danger: true }))) {
            return;
        }

        try {
            const response = await fetch(`/api/connections/${id}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                this.loadConnections();
                this.showStatus('Connection deleted', 'success');

                // Clear active connection if deleted
                if (this.activeConnection?.id === id) {
                    this.activeConnection = null;
                    this.updateConnectionStatus('Not Connected');
                    // Clear database tree
                    if (window.app) {
                        window.app.clearDatabaseTree();
                    }
                }
            } else {
                this.showStatus('Failed to delete connection: ' + result.error, 'error');
            }
        } catch (error) {
            console.error('Error deleting connection:', error);
            this.showStatus('Error deleting connection', 'error');
        }
    }

    async testConnection() {
        const form = document.getElementById('connection-form');
        const formData = new FormData(form);
        const connectionData = {
            id: this.editingId || undefined,
            type: formData.get('type'),
            host: formData.get('host'),
            port: parseInt(formData.get('port')) || null,
            database: formData.get('database'),
            username: formData.get('username'),
            password: formData.get('password'),
            connection_url: formData.get('connection_url'),
            use_ssl: formData.get('use_ssl') === 'on',
            read_only: formData.get('read_only') === 'on',
            environment: formData.get('environment') || '',
            ...this.sshFormData(formData)
        };

        // Handle certificate files if SSL is enabled and files are selected
        if (connectionData.use_ssl) {
            const caCertFile = formData.get('ca_cert');
            const clientCertFile = formData.get('client_cert');
            const clientKeyFile = formData.get('client_key');

            if (caCertFile && caCertFile.size > 0) {
                connectionData.ca_cert = await this.readFileAsBase64(caCertFile);
                connectionData.ca_cert_filename = caCertFile.name;
            }

            if (clientCertFile && clientCertFile.size > 0) {
                connectionData.client_cert = await this.readFileAsBase64(clientCertFile);
                connectionData.client_cert_filename = clientCertFile.name;
            }

            if (clientKeyFile && clientKeyFile.size > 0) {
                connectionData.client_key = await this.readFileAsBase64(clientKeyFile);
                connectionData.client_key_filename = clientKeyFile.name;
            }
        }

        if (!connectionData.type) {
            this.showStatus('Please select a database type', 'error');
            return;
        }

        this.showStatus('Testing connection...', 'info');

        try {
            const send = async (trust) => (await fetch('/api/test-connection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...connectionData, ssh_trust_host_key: trust })
            })).json();

            let result = await send();
            if (result.needs_host_key_confirmation) {
                if (!(await this.confirmHostKey(result))) {
                    this.showStatus('Test cancelled. The SSH server was not trusted.', 'info');
                    return;
                }
                result = await send(result.fingerprint);
            }

            if (result.success) {
                this.showStatus('✓ ' + result.message, 'success');
            } else {
                this.showStatus('✗ ' + (result.message || result.error), 'error');
            }
        } catch (error) {
            console.error('Error testing connection:', error);
            this.showStatus('Error testing connection', 'error');
        }
    }

    async connect(id) {
        try {
            // Check if already connected
            if (this.connectedConnections.has(id)) {
                // Just switch to it, don't reconnect
                this.switchToConnection(id);
                return;
            }

            this.showStatus('Connecting...', 'info');

            const send = async (trust) => (await fetch('/api/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id, ssh_trust_host_key: trust })
            })).json();

            let result = await send();
            if (result.needs_host_key_confirmation) {
                if (!(await this.confirmHostKey(result))) {
                    this.showStatus('Not connected. The SSH server was not trusted.', 'info');
                    return;
                }
                result = await send(result.fingerprint);
            }

            if (result.success) {
                const conn = this.connections.find(c => c.id === id);

                // Mark as connected (don't disconnect others!)
                this.connectedConnections.add(id);

                // Switch to this connection
                this.switchToConnection(id);

                this.renderConnections();
                this.hideConnectionsManager();
                this.showStatus(`Connected to ${conn.name}`, 'success');
            } else {
                this.showStatus('Failed to connect: ' + result.error, 'error');
            }
        } catch (error) {
            console.error('Error connecting:', error);
            this.showStatus('Error connecting to database', 'error');
        }
    }

    async rename(id) {
        const conn = this.connections.find(c => c.id === id);
        if (!conn) return;
        const oldName = conn.name;
        const name = await ui.prompt('New name for this connection.', { title: 'Rename connection', value: oldName, confirmLabel: 'Rename', emptyMessage: 'Give the connection a name.' });
        if (!name || name === oldName) return;
        try {
            // the update merges what it is given into the saved connection, so nothing else (host, password, tunnel) is touched
            const response = await fetch(`/api/connections/${encodeURIComponent(id)}`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, environment: conn.environment || '' }) });
            const result = await response.json();
            if (!result.success) { ui.notify(result.error || 'Could not rename the connection.', 'error'); return; }
        } catch (error) {
            ui.notify(`Could not rename the connection: ${error.message}`, 'error');
            return;
        }
        await this.loadConnections();
        if (this.activeConnection?.id === id) {
            this.activeConnection = this.connections.find(c => c.id === id);
            this.updateConnectionStatus(`Connected to ${name}`);
        }
        this.updateConnectionBadges();
        ui.notify(`Renamed "${oldName}" to "${name}".`, 'success');
    }

    switchToConnection(id) {

        // 1. Hide tabs for old connection before switching
        if (this.activeConnection && window.app?.tabManager) {
            window.app.tabManager.hideTabsForConnection(this.activeConnection.id);
        }

        const conn = this.connections.find(c => c.id === id);
        this.activeConnection = conn;
        this.updateConnectionStatus(`Connected to ${conn.name}`);
        this.updateConnectionBadges();

        // 2. Restore or create tabs for new connection
        if (window.app?.tabManager) {
            const tabs = window.app.tabManager.getTabsByConnection(id);
            if (tabs.length === 0) {
                // No tabs exist, create default query tab
                window.app.tabManager.createTab('query', id, { query: '' });
            } else {
                // Restore existing tabs
                window.app.tabManager.restoreTabsForConnection(id);
            }

            // 3. Persist session state
            window.app.tabManager.persistToStorage();
        }

        // 4. Load database tree in background
        if (window.app) {
            window.app.loadDatabaseTree(id);
        }
    }

    async disconnect(id) {
        try {
            const response = await fetch('/api/disconnect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id })
            });

            const result = await response.json();

            if (result.success) {
                // Remove from connected set
                this.connectedConnections.delete(id);

                // Hide tabs for disconnected connection
                if (window.app?.tabManager) {
                    window.app.tabManager.hideTabsForConnection(id);
                }

                // If this was the active connection, switch to another or clear
                if (this.activeConnection?.id === id) {
                    // Switch to another connected database if available
                    const otherConnected = Array.from(this.connectedConnections)[0];
                    if (otherConnected) {
                        this.switchToConnection(otherConnected);
                    } else {
                        this.activeConnection = null;
                        this.updateConnectionStatus('Not Connected');
                        if (window.app) {
                            window.app.clearDatabaseTree();
                        }
                    }
                }

                this.updateConnectionBadges();
                this.renderConnections();
                this.showStatus('Disconnected', 'success');
            } else {
                this.showStatus('Failed to disconnect: ' + result.error, 'error');
            }
        } catch (error) {
            console.error('Error disconnecting:', error);
            this.showStatus('Error disconnecting', 'error');
        }
    }

    updateConnectionStatus(status) {
        const statusElement = document.getElementById('connection-status');
        statusElement.textContent = status;

        if (this.activeConnection) {
            statusElement.classList.add('connected');
        } else {
            statusElement.classList.remove('connected');
        }
    }

    envTag(conn) {
        return conn.environment ? `<span class="env-tag env-${this.esc(conn.environment)}">${this.esc(conn.environment)}</span>` : '';
    }

    // SQL databases can export INSERT statements and be searched table by table; the others cannot
    isSql(connectionId) {
        const conn = this.connections.find(c => c.id === connectionId);
        return !!conn && ['sqlite', 'mysql', 'postgresql', 'sqlserver', 'oracle'].includes(conn.type);
    }

    isProduction(connectionId) {
        const conn = this.connections.find(c => c.id === connectionId);
        return !!conn && conn.environment === 'production';
    }

    // The whole window takes on the colour of the active connection's environment
    applyEnvironment() {
        const env = this.activeConnection && this.activeConnection.environment;
        if (env) document.body.dataset.env = env; else delete document.body.dataset.env;
    }

    updateConnectionBadges() {
        this.applyEnvironment();
        // Get or create badges container
        let badgesContainer = document.getElementById('connection-badges-container');
        if (!badgesContainer) {
            // Create container after refresh button
            const toolbarLeft = document.querySelector('.toolbar-left');
            badgesContainer = document.createElement('div');
            badgesContainer.id = 'connection-badges-container';
            badgesContainer.className = 'connection-badges-container';
            toolbarLeft.appendChild(badgesContainer);
        }

        // Clear and rebuild badges
        badgesContainer.innerHTML = '';

        // The top bar names the active connection; the others live in the switcher (switcher.js)
        this.connectedConnections.forEach(connId => {
            if (this.activeConnection?.id !== connId) return;
            const conn = this.connections.find(c => c.id === connId);
            if (!conn) return;

            const badge = document.createElement('div');
            badge.className = 'connection-badge';
            if (this.activeConnection?.id === connId) {
                badge.classList.add('active');
            }
            badge.setAttribute('data-connection-id', connId);

            badge.innerHTML = `
                <span class="connection-dot"></span>
                <span class="connection-name">${this.esc(conn.name)}</span>
                ${this.envTag(conn)}
                ${conn.read_only ? '<span class="ro-tag" title="Writes are blocked on this connection">read-only</span>' : ''}
                <span class="connection-close" data-connection-id="${connId}">×</span>
            `;

            // Click to see all the open connections
            badge.addEventListener('click', (e) => {
                if (!e.target.classList.contains('connection-close')) {
                    window.app.switcher.toggle();
                }
            });

            // Click × to disconnect
            const closeBtn = badge.querySelector('.connection-close');
            closeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.disconnect(connId);
            });

            badgesContainer.appendChild(badge);
        });

        // Hide old single badge
        const oldBadge = document.getElementById('active-conn-badge');
        if (oldBadge) {
            oldBadge.style.display = 'none';
        }

        if (window.app && window.app.switcher) window.app.switcher.render();
    }

    switchToNextConnection() {
        if (this.connections.length === 0) return;

        const currentIndex = this.connections.findIndex(c => c.id === this.activeConnection?.id);
        const nextIndex = (currentIndex + 1) % this.connections.length;
        this.connect(this.connections[nextIndex].id);
    }

    switchToPreviousConnection() {
        if (this.connections.length === 0) return;

        const currentIndex = this.connections.findIndex(c => c.id === this.activeConnection?.id);
        const prevIndex = (currentIndex - 1 + this.connections.length) % this.connections.length;
        this.connect(this.connections[prevIndex].id);
    }

    showStatus(message, type = 'info') {
        const statusElement = document.getElementById('status-message');
        statusElement.textContent = message;
        // Errors and confirmations deserve more than a status-bar line
        if (type === 'error' || type === 'success') {
            window.app?.tabManager?.showNotification(message, type);
        }

        // You could add different styling based on type
        if (type === 'error') {
            statusElement.style.color = 'var(--danger-color)';
        } else if (type === 'success') {
            statusElement.style.color = 'var(--success-color)';
        } else {
            statusElement.style.color = 'var(--text-muted)';
        }

        // Clear after 5 seconds
        setTimeout(() => {
            if (statusElement.textContent === message) {
                statusElement.textContent = 'Ready';
                statusElement.style.color = 'var(--text-muted)';
            }
        }, 5000);
    }

    getActiveConnection() {
        return this.activeConnection;
    }
}
