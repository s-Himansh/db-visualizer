// Saved queries: SQL you want to keep. They live on disk (saved_queries.json in the data folder), so they survive
// restarts. Names and SQL are user data: they are only ever put on the page with textContent.
class SavedQueries {
    constructor() {
        this.items = [];
        this.target = null;      // the query tab the panel was opened from, if any
        this.modal = document.getElementById('saved-queries-modal');
        this.list = document.getElementById('saved-queries-list');
        this.filter = document.getElementById('saved-queries-filter');
        this.empty = document.getElementById('saved-queries-empty');

        document.getElementById('saved-queries-close').addEventListener('click', () => this.close());
        this.modal.addEventListener('mousedown', (e) => { if (e.target === this.modal) this.close(); });
        this.filter.addEventListener('input', () => this.render());
        this.list.addEventListener('click', (e) => this.onClick(e));
        this.list.addEventListener('keydown', (e) => {
            if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('saved-main')) { e.preventDefault(); e.target.click(); }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.classList.contains('active') && !document.querySelector('.app-dialog')) this.close();
        });
        this.load();
    }

    async request(url, options) {
        const response = await fetch(url, options && options.body
            ? { ...options, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options.body) } : options);
        return { status: response.status, body: await response.json() };
    }

    async load() {
        try {
            const { body } = await this.request('/api/saved-queries');
            if (body.success) this.items = body.queries;
        } catch (error) {
            console.error('Could not load saved queries:', error);
        }
        if (this.modal.classList.contains('active')) this.render();
    }

    // ---- saving the query in a tab ----------------------------------------------------------------------

    /** Save what is selected in the tab's editor, or the whole editor if nothing is selected. */
    async saveFrom(tab) {
        if (!tab || !tab.editor) return;
        const sql = (tab.editor.getSelection() || tab.editor.getValue()).trim();
        if (!sql) { ui.notify('Write a query first, then save it.', 'warning'); return; }

        const name = await ui.prompt('Give this query a name so you can find it again.', {
            title: 'Save query', value: tab.savedName || '', confirmLabel: 'Save', emptyMessage: 'Give the query a name.'
        });
        if (!name) return;

        const connection = window.app.connectionManager.connections.find(c => c.id === tab.connectionId);
        const body = { name, sql, connection_name: connection ? connection.name : null };
        try {
            let { status, body: result } = await this.request('/api/saved-queries', { method: 'POST', body });
            if (status === 409 && result.exists) {
                const sameAsBefore = tab.savedName && tab.savedName.toLowerCase() === name.toLowerCase();
                const replace = sameAsBefore || await ui.confirm(
                    `"${name}" is already saved. Replace it with this query?`,
                    { title: 'Replace saved query', confirmLabel: 'Replace', danger: true });
                if (!replace) return;
                ({ status, body: result } = await this.request('/api/saved-queries', { method: 'POST', body: { ...body, replace: true } }));
            }
            if (!result.success) { ui.notify(result.error || 'Could not save the query.', 'error'); return; }
            tab.savedName = result.query.name;
            ui.notify(`Saved the query "${result.query.name}".`, 'success');
            await this.load();
        } catch (error) {
            console.error('Error saving query:', error);
            ui.notify(`Could not save the query: ${error.message}`, 'error');
        }
    }

    // ---- the list ---------------------------------------------------------------------------------------

    open(tab) {
        this.target = tab && tab.type === 'query' && tab.editor ? tab : null;
        this.filter.value = '';
        this.modal.classList.add('active');
        this.render();
        this.load();     // pick up changes made elsewhere
        this.filter.focus();
    }

    close() {
        this.modal.classList.remove('active');
        this.target = null;
    }

    visible() {
        const needle = this.filter.value.trim().toLowerCase();
        return needle ? this.items.filter(q => q.name.toLowerCase().includes(needle) || q.sql.toLowerCase().includes(needle)) : this.items;
    }

    render() {
        const items = this.visible();
        this.list.replaceChildren(...items.map(q => this.row(q)));
        this.empty.style.display = items.length ? 'none' : '';
        this.empty.textContent = this.items.length
            ? 'No saved query matches that.'
            : 'Nothing saved yet. Write a query and press Save in the query tab to keep it here.';
    }

    row(q) {
        const element = (tag, className, text) => {
            const el = document.createElement(tag);
            if (className) el.className = className;
            if (text !== undefined) el.textContent = text;
            return el;
        };
        const row = element('div', 'saved-item');
        row.dataset.id = q.id;

        const main = element('div', 'saved-main');
        main.setAttribute('role', 'button');
        main.tabIndex = 0;
        main.title = this.target ? 'Put this query in the editor' : 'Open this query in a new tab';
        main.append(element('div', 'saved-name', q.name));
        const saved = q.updated ? new Date(q.updated).toLocaleDateString() : '';
        main.append(element('div', 'saved-meta', [q.connection_name && `from ${q.connection_name}`, saved].filter(Boolean).join(' · ')));
        const preview = q.sql.split('\n').slice(0, 3).join('\n');
        main.append(element('code', 'saved-sql', preview.length > 200 ? preview.slice(0, 200) + '…' : preview));
        row.append(main);

        const actions = element('div', 'saved-actions');
        for (const [act, label, cls] of [['tab', 'New tab', 'btn btn-sm'], ['rename', 'Rename', 'btn btn-sm'], ['delete', 'Delete', 'btn btn-sm btn-danger']]) {
            const button = element('button', cls, label);
            button.type = 'button';
            button.dataset.act = act;
            actions.append(button);
        }
        row.append(actions);
        return row;
    }

    async onClick(e) {
        const row = e.target.closest('.saved-item');
        if (!row) return;
        const q = this.items.find(item => item.id === row.dataset.id);
        if (!q) return;
        const act = e.target.dataset.act || (e.target.closest('.saved-main') ? 'use' : null);
        if (act === 'use') this.target ? await this.useInTarget(q) : this.openInNewTab(q);
        else if (act === 'tab') this.openInNewTab(q);
        else if (act === 'rename') await this.rename(q);
        else if (act === 'delete') await this.remove(q);
    }

    async useInTarget(q) {
        const tab = this.target;
        const current = tab.editor.getValue().trim();
        if (current && current !== q.sql.trim()) {
            const replace = await ui.confirm('This replaces what is in the editor now. Use "New tab" to keep it.',
                { title: `Use "${q.name}"?`, confirmLabel: 'Replace', danger: true });
            if (!replace) return;
        }
        tab.editor.setValue(q.sql);
        tab.savedName = q.name;
        this.close();
        tab.editor.focus();
    }

    openInNewTab(q) {
        const active = window.app.connectionManager.getActiveConnection();
        if (!active) { ui.notify('Connect to a database first, then open the query.', 'warning'); return; }
        this.close();
        const tabId = window.app.tabManager.createTab('query', active.id, { query: q.sql });
        const tab = window.app.tabManager.tabs.get(tabId);
        if (tab) tab.savedName = q.name;
    }

    async rename(q) {
        const name = await ui.prompt('New name for this query.', { title: 'Rename query', value: q.name, confirmLabel: 'Rename', emptyMessage: 'Give the query a name.' });
        if (!name || name === q.name) return;
        const { body } = await this.request(`/api/saved-queries/${encodeURIComponent(q.id)}`, { method: 'PUT', body: { name } });
        if (!body.success) ui.notify(body.error || 'Could not rename the query.', 'error');
        await this.load();
        this.render();
    }

    async remove(q) {
        const sure = await ui.confirm(`Delete the saved query "${q.name}"? This cannot be undone.`,
            { title: 'Delete saved query', confirmLabel: 'Delete', danger: true });
        if (!sure) return;
        const { body } = await this.request(`/api/saved-queries/${encodeURIComponent(q.id)}`, { method: 'DELETE' });
        if (!body.success) ui.notify(body.error || 'Could not delete the query.', 'error');
        await this.load();
        this.render();
    }
}
