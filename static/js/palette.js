// Command palette (Cmd/Ctrl+K): type to jump to a table, connection or open tab, or to run an action.
class CommandPalette {
    constructor() {
        this.root = null;
        this.items = [];
        this.shown = [];
        this.index = 0;
        const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
        document.addEventListener('keydown', (e) => {
            if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                e.stopPropagation();
                this.root ? this.close() : this.open();
            }
        }, true);
        const btn = document.getElementById('palette-btn');
        if (btn) {
            btn.querySelector('kbd').textContent = isMac ? '⌘K' : 'Ctrl K';
            btn.addEventListener('click', () => this.open());
        }
    }

    // ---- what can be jumped to -----------------------------------------------------------------------

    collect() {
        const app = window.app;
        const cm = app.connectionManager;
        const items = [];
        const active = cm.getActiveConnection();
        const mapBtn = document.getElementById('open-map-btn');
        const database = mapBtn && mapBtn.dataset.database;

        if (active && database) {
            document.querySelectorAll('#tables-content .tree-item .tree-label').forEach(label => {
                const name = label.textContent;
                items.push({ group: 'Tables', label: name, hint: `open in ${active.name}`, run: () => app.openTableData(active.id, database, name) });
            });
        }
        for (const conn of cm.connections) {
            const connected = cm.connectedConnections.has(conn.id);
            const current = active && active.id === conn.id;
            if (current) continue;
            items.push({
                group: 'Connections', label: conn.name, hint: connected ? 'switch to it' : `connect (${conn.type})`,
                run: () => connected ? cm.switchToConnection(conn.id) : cm.connect(conn.id)
            });
        }
        if (app.tabManager) {
            for (const [id, tab] of app.tabManager.tabs) {
                if (!active || tab.connectionId !== active.id || id === app.tabManager.activeTabId) continue;
                if (tab.type === 'table' && !tab.state.filter) continue;   // the Tables entry already goes to it
                items.push({ group: 'Open tabs', label: tab.title, hint: tab.type, run: () => app.tabManager.switchTab(id) });
            }
        }
        const actions = [
            ['New query', 'write SQL', () => document.getElementById('new-query-tab-btn').click(), !!active],
            ['Show the schema map', 'how tables relate', () => mapBtn.click(), !!active && !!database],
            ['Refresh the table list', 'read the database again', () => document.getElementById('refresh-btn').click(), !!active],
            ['Ask the SQL assistant', 'describe a query in plain English', () => {
                const tm = app.tabManager, current = tm.tabs.get(tm.activeTabId);
                if (current && current.type === 'query') app.assistant.toggle(current);
                else { document.getElementById('new-query-tab-btn').click(); setTimeout(() => { const t = tm.tabs.get(tm.activeTabId); if (t) app.assistant.toggle(t); }, 250); }
            }, !!active],
            ['SQL assistant settings', 'API key and what is sent', () => app.assistant.openSettings(), true],
            ['Open the sample database', 'a small online shop to explore', () => app.openSample(), true],
            ['New connection', 'add a database', () => cm.showConnectionModal(), true],
            ['Manage connections', 'edit, connect or delete', () => cm.showConnectionsManager(), true],
        ];
        for (const [label, hint, run, enabled] of actions) {
            if (enabled) items.push({ group: 'Actions', label, hint, run });
        }
        return items;
    }

    // Subsequence match with a score that prefers early, consecutive and word-start hits; null = no match
    static match(query, text) {
        if (!query) return { score: 0, positions: [] };
        const q = query.toLowerCase(), t = text.toLowerCase();
        const at = t.indexOf(q);
        if (at !== -1) return { score: 100 - at + (at === 0 ? 20 : 0) + (q.length === t.length ? 50 : 0), positions: [...Array(q.length).keys()].map(i => at + i) };
        let ti = 0, score = 0, last = -2;
        const positions = [];
        for (const ch of q) {
            const found = t.indexOf(ch, ti);
            if (found === -1) return null;
            score += (found === last + 1 ? 6 : 1) + (found === 0 || /[\s_\-.]/.test(t[found - 1]) ? 4 : 0);
            positions.push(found);
            last = found;
            ti = found + 1;
        }
        return { score, positions };
    }

    // ---- the dialog ------------------------------------------------------------------------------------

    open() {
        if (this.root || !window.app) return;
        document.querySelectorAll('.table-context-menu').forEach(m => m.remove());
        this.items = this.collect();
        this.previous = document.activeElement;
        const root = document.createElement('div');
        root.className = 'palette-backdrop';
        root.innerHTML = `
            <div class="palette" role="dialog" aria-modal="true" aria-label="Jump to">
                <input class="palette-input" type="text" placeholder="Jump to a table, connection or action" aria-label="Jump to"
                       role="combobox" aria-expanded="true" aria-controls="palette-list" autocomplete="off" spellcheck="false">
                <div class="palette-list" id="palette-list" role="listbox"></div>
                <div class="palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> choose</span><span><kbd>Enter</kbd> go</span><span><kbd>Esc</kbd> close</span></div>
            </div>`;
        this.root = root;
        this.input = root.querySelector('.palette-input');
        this.list = root.querySelector('.palette-list');
        this.input.addEventListener('input', () => { this.index = 0; this.render(); });
        this.input.addEventListener('keydown', (e) => this.onKey(e));
        root.addEventListener('mousedown', (e) => { if (e.target === root) this.close(); });
        this.list.addEventListener('mousemove', (e) => {
            const row = e.target.closest('.palette-item');
            if (row && Number(row.dataset.i) !== this.index) { this.index = Number(row.dataset.i); this.highlight(); }
        });
        this.list.addEventListener('click', (e) => {
            const row = e.target.closest('.palette-item');
            if (row) this.choose(Number(row.dataset.i));
        });
        document.body.appendChild(root);
        this.render();
        this.input.focus();
    }

    close() {
        if (!this.root) return;
        this.root.remove();
        this.root = null;
        if (this.previous && this.previous.focus) this.previous.focus();
    }

    onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.close(); }
        else if (e.key === 'ArrowDown') { e.preventDefault(); this.move(1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); this.move(-1); }
        else if (e.key === 'Enter') { e.preventDefault(); this.choose(this.index); }
    }

    move(step) {
        if (!this.shown.length) return;
        this.index = (this.index + step + this.shown.length) % this.shown.length;
        this.highlight();
    }

    choose(i) {
        const item = this.shown[i];
        if (!item) return;
        this.close();
        item.run();
    }

    render() {
        const query = this.input.value.trim();
        let rows = this.items.map(item => ({ item, m: CommandPalette.match(query, item.label) })).filter(r => r.m);
        // equally good matches: the shorter name is the closer one ("orders" before "order_items" for "ord")
        if (query) rows.sort((a, b) => b.m.score - a.m.score || a.item.label.length - b.item.label.length || a.item.label.localeCompare(b.item.label));
        // with nothing typed, keep each group's own order but cap long table lists
        else {
            const seen = {};
            rows = rows.filter(r => (seen[r.item.group] = (seen[r.item.group] || 0) + 1) <= 8);
        }
        rows = rows.slice(0, 40);
        this.shown = rows.map(r => r.item);
        this.list.innerHTML = '';
        if (!rows.length) {
            const none = document.createElement('div');
            none.className = 'palette-empty';
            none.textContent = query ? `Nothing matches "${query}".` : 'Connect to a database to jump around its tables.';
            this.list.appendChild(none);
            return;
        }
        let group = null;
        rows.forEach((r, i) => {
            if (!query && r.item.group !== group) {
                group = r.item.group;
                const h = document.createElement('div');
                h.className = 'palette-group';
                h.textContent = group;
                this.list.appendChild(h);
            }
            const row = document.createElement('div');
            row.className = 'palette-item';
            row.id = `palette-opt-${i}`;
            row.dataset.i = i;
            row.setAttribute('role', 'option');
            const label = document.createElement('span');
            label.className = 'palette-label';
            const hits = new Set(r.m.positions);
            [...r.item.label].forEach((ch, k) => {
                if (hits.has(k)) { const b = document.createElement('b'); b.textContent = ch; label.appendChild(b); }
                else label.appendChild(document.createTextNode(ch));
            });
            const hint = document.createElement('span');
            hint.className = 'palette-hint';
            hint.textContent = query ? `${r.item.group.toLowerCase()} · ${r.item.hint}` : r.item.hint;
            row.append(label, hint);
            this.list.appendChild(row);
        });
        this.highlight();
    }

    highlight() {
        this.list.querySelectorAll('.palette-item').forEach(r => {
            const on = Number(r.dataset.i) === this.index;
            r.classList.toggle('active', on);
            r.setAttribute('aria-selected', on ? 'true' : 'false');
            if (on) { this.input.setAttribute('aria-activedescendant', r.id); r.scrollIntoView({ block: 'nearest' }); }
        });
    }
}
