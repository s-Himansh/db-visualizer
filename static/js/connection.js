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
        const container = document.getElementById('connections-list');
        container.innerHTML = '';
        document.dispatchEvent(new CustomEvent('connections-changed'));


        if (this.connections.length === 0) {
            container.innerHTML = `
                <div class="tree-message">
                    <strong>No connections yet</strong><br>
                    Choose New connection to add your first database.
                </div>
            `;
            return;
        }

        this.connections.forEach(conn => {
            const item = document.createElement('div');
            item.className = 'connection-item';

            const isConnected = this.connectedConnections.has(conn.id);
            const isActive = this.activeConnection?.id === conn.id;

            if (isActive) {
                item.classList.add('active');
            } else if (isConnected) {
                item.classList.add('connected');
            }

            item.innerHTML = `
                <div class="connection-info">
                    <div class="connection-name">${this.esc(conn.name)}</div>
                    <span class="connection-type">${this.esc(conn.type)}</span>
                    ${this.envTag(conn)}
                    ${conn.read_only ? '<span class="connection-type ro" title="Writes are blocked on this connection">read-only</span>' : ''}
                </div>
                <div class="connection-actions">
                    <button class="connect-btn" data-id="${conn.id}" title="${isConnected ? 'Disconnect' : 'Connect'}">
                        ${isConnected ? 'Disconnect' : 'Connect'}
                    </button>
                    <button class="edit-btn" title="Edit connection" aria-label="Edit connection">Edit</button>
                    <button class="delete-btn" data-id="${conn.id}" title="Delete connection" aria-label="Delete connection">Delete</button>
                </div>
            `;

            item.querySelector('.edit-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                this.editConnection(conn);
            });

            // Click on connection name to switch (if already connected)
            item.querySelector('.connection-info').addEventListener('click', (e) => {
                e.stopPropagation();
                if (isConnected) {
                    this.switchToConnection(conn.id);
                    this.hideConnectionsManager();
                } else {
                    this.connect(conn.id);
                    this.hideConnectionsManager();
                }
            });

            // Connect/disconnect button
            item.querySelector('.connect-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                const id = e.target.getAttribute('data-id');
                if (this.connectedConnections.has(id)) {
                    this.disconnect(id);
                } else {
                    this.connect(id);
                }
            });

            // Delete button
            item.querySelector('.delete-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                const id = e.target.getAttribute('data-id');
                this.deleteConnection(id);
            });

            container.appendChild(item);
        });
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

        // Create badge for each connected database
        this.connectedConnections.forEach(connId => {
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

            // Click to switch
            badge.addEventListener('click', (e) => {
                if (!e.target.classList.contains('connection-close')) {
                    this.switchToConnection(connId);
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
