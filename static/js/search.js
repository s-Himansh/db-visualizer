// Search every table for a value (Cmd/Ctrl+Shift+F, or "Search all tables" in the palette).
// The server asks each table, so this is a button-press search, not search-as-you-type.
class DatabaseSearch {
    constructor() {
        this.root = null;
        document.addEventListener('keydown', (e) => {
            if ((e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey && e.key.toLowerCase() === 'f') {
                e.preventDefault();
                this.root ? this.close() : this.open();
            }
        }, true);
    }

    target() {
        const conn = window.app.connectionManager.getActiveConnection();
        const map = document.getElementById('open-map-btn');
        const database = map && map.dataset.database;
        return conn && database ? { conn, database } : null;
    }

    open() {
        if (this.root) return;
        const target = this.target();
        if (!target) { ui.notify('Open a database first.'); return; }
        this.previous = document.activeElement;
        this.requestId = 0;
        const root = document.createElement('div');
        root.className = 'palette-backdrop';
        root.innerHTML = `
            <div class="palette" role="dialog" aria-modal="true" aria-label="Search every table">
                <input class="palette-input" type="text" placeholder="Find a value in any table of this database, then press Enter" aria-label="Value to find"
                       autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false">
                <div class="palette-list"><div class="palette-empty">Looks in every column of every table.</div></div>
                <div class="palette-foot"><span><kbd>Enter</kbd> search</span><span><kbd>Esc</kbd> close</span></div>
            </div>`;
        this.root = root;
        this.input = root.querySelector('.palette-input');
        this.list = root.querySelector('.palette-list');
        this.input.placeholder = `Find a value in any table of ${target.database}, then press Enter`;
        this.input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.close(); }
            else if (e.key === 'Enter') { e.preventDefault(); this.run(target); }
        });
        root.addEventListener('mousedown', (e) => { if (e.target === root) this.close(); });
        document.body.appendChild(root);
        this.input.focus();
    }

    close() {
        if (!this.root) return;
        this.requestId++;   // an answer still on its way is ignored
        this.root.remove();
        this.root = null;
        if (this.previous && this.previous.focus) this.previous.focus();
    }

    message(text) {
        const d = document.createElement('div');
        d.className = 'palette-empty';
        d.textContent = text;
        this.list.replaceChildren(d);
    }

    async run({ conn, database }) {
        const term = this.input.value.trim();
        if (term.length < 2) { this.message('Type at least two characters to search for.'); return; }
        const id = ++this.requestId;
        this.message(`Looking for "${term}" in every table…`);
        let body;
        try {
            body = await (await fetch(`/api/search?connection_id=${conn.id}&database=${encodeURIComponent(database)}&term=${encodeURIComponent(term)}`)).json();
        } catch (err) {
            if (id === this.requestId) this.message(`Could not search: ${err.message}`);
            return;
        }
        if (id !== this.requestId || !this.root) return;
        if (!body.success) { this.message(body.error); return; }

        const notes = [];
        if (body.scanned < body.tables) notes.push(`Searched ${body.scanned} of ${body.tables} tables (stopped after ${body.seconds}s).`);
        if (body.failed) notes.push(`${body.failed} table${body.failed === 1 ? ' was' : 's were'} skipped because they could not be read.`);
        if (!body.results.length) { this.message([`Nothing found for "${term}".`, ...notes].join(' ')); return; }

        const rows = body.results.map(r => {
            const row = document.createElement('div');
            row.className = 'palette-item';
            row.tabIndex = 0;
            const label = document.createElement('span');
            label.className = 'palette-label';
            label.textContent = r.table;
            const hint = document.createElement('span');
            hint.className = 'palette-hint';
            hint.textContent = `${r.total} row${r.total === 1 ? '' : 's'} · ${this.snippet(r, term)}`;
            row.append(label, hint);
            const go = () => { this.close(); this.openTable(conn.id, database, r.table, term); };
            row.addEventListener('click', go);
            row.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
            return row;
        });
        const head = document.createElement('div');
        head.className = 'palette-group';
        head.textContent = `${body.results.length} table${body.results.length === 1 ? '' : 's'} contain "${term}"`;
        this.list.replaceChildren(head, ...rows, ...notes.map(n => Object.assign(document.createElement('div'), { className: 'palette-group', textContent: n })));
    }

    // the first cell that holds the term, as "column: value"
    snippet(result, term) {
        const lower = term.toLowerCase();
        const row = result.rows[0];
        const cells = Array.isArray(row) ? result.columns.map((c, i) => [c, row[i]]) : result.columns.map(c => [c, row[c]]);
        for (const [column, value] of cells) {
            const text = value !== null && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '');
            if (text.toLowerCase().includes(lower)) return `${column}: ${text.length > 40 ? text.slice(0, 40) + '…' : text}`;
        }
        return 'matches';
    }

    // opens the table with the search already applied, once its grid exists
    openTable(connectionId, database, table, term) {
        window.app.openTableData(connectionId, database, table);
        const tm = window.app.tabManager;
        const started = Date.now();
        const apply = () => {
            const tab = tm.tabs.get(tm.activeTabId);
            const input = tab && document.getElementById(`table-search-${tab.id}`);
            const ready = input && tab.state.tableName === table && document.querySelectorAll(`#table-search-columns-${tab.id} option`).length > 1;
            if (ready) { input.value = term; tm.searchTable(tab); }
            else if (Date.now() - started < 5000) setTimeout(apply, 100);
        };
        apply();
    }
}
