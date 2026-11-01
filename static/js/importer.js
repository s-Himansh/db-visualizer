// CSV import: pick a file, say which file column goes into which table column, check it, import it.
// Everything is all-or-nothing on the server. File names, headers and values are untrusted text: only textContent here.
class CsvImporter {
    constructor() {
        this.modal = document.getElementById('import-modal');
        this.fileInput = document.getElementById('import-file');
        this.body = document.getElementById('import-body');
        this.status = document.getElementById('import-status');
        this.checkButton = document.getElementById('import-check');
        this.runButton = document.getElementById('import-run');
        this.busy = false;
        this.tab = null;
        this.file = null;
        this.preview = null;
        this.options = { delimiter: '', hasHeader: true, emptyAsNull: true };
        this.mapping = {};

        this.fileInput.addEventListener('change', () => this.onFile());
        document.getElementById('import-close').addEventListener('click', () => this.close());
        document.getElementById('import-cancel').addEventListener('click', () => this.close());
        this.modal.addEventListener('mousedown', (e) => { if (e.target === this.modal) this.close(); });
        this.checkButton.addEventListener('click', () => this.check());
        this.runButton.addEventListener('click', () => this.run());
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.classList.contains('active') && !document.querySelector('.app-dialog')) this.close();
        });
    }

    // ---- starting -------------------------------------------------------------------------------------------

    async start(tab) {
        const conn = window.app.connectionManager.connections.find(c => c.id === tab.connectionId);
        if (conn && conn.read_only) { ui.notify('This connection is read-only, so it cannot import.', 'warning'); return; }
        if (!['sqlite', 'mysql', 'postgresql', 'sqlserver', 'oracle'].includes(conn && conn.type)) {
            ui.notify('CSV import works with SQLite, PostgreSQL, MySQL, SQL Server and Oracle.', 'warning');
            return;
        }
        if (window.app.tabManager.hasUnsavedChanges(tab) && !(await ui.confirm(
            'This table has unsaved changes. Importing reloads the table, so they would be lost.',
            { title: 'Unsaved changes', confirmLabel: 'Import anyway', danger: true }))) return;
        this.tab = tab;
        this.fileInput.value = '';
        this.fileInput.click();
    }

    async onFile() {
        const file = this.fileInput.files[0];
        if (!file) return;
        this.file = file;
        this.options = { delimiter: '', hasHeader: true, emptyAsNull: true };
        this.mapping = {};
        if (await this.loadPreview(true)) {
            this.modal.classList.add('active');
            this.runButton.focus();
        }
    }

    form(extra = {}) {
        const data = new FormData();
        data.append('file', this.file, this.file.name);
        data.append('connection_id', this.tab.connectionId);
        data.append('database', this.tab.state.database || '');
        data.append('table', this.tab.state.tableName);
        data.append('delimiter', this.options.delimiter);
        data.append('has_header', String(this.options.hasHeader));
        for (const [key, value] of Object.entries(extra)) data.append(key, value);
        return data;
    }

    async post(url, data) {
        const response = await fetch(url, { method: 'POST', body: data });
        let body;
        try { body = await response.json(); } catch (e) { body = { success: false, error: `The server answered ${response.status}.` }; }
        return { status: response.status, body };
    }

    async loadPreview(first) {
        try {
            const { body } = await this.post('/api/import/preview', this.form());
            if (!body.success) {
                if (first) ui.notify(body.error || 'Could not read that file.', 'error');
                else this.say(body.error || 'Could not read that file.', 'error');
                return false;
            }
            this.preview = body;
            this.options.delimiter = body.delimiter;
            // a new reading of the file (another separator, header or not) changes what each file column is, so start again
            this.mapping = { ...body.suggested_mapping };
            this.render();
            return true;
        } catch (error) {
            console.error('Import preview failed:', error);
            ui.notify(`Could not read that file: ${error.message}`, 'error');
            return false;
        }
    }

    close() {
        if (this.busy) return;
        this.modal.classList.remove('active');
        this.file = null;
        this.preview = null;
    }

    // ---- the dialog -----------------------------------------------------------------------------------------

    el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    say(message, kind = '') {
        this.status.className = `import-status ${kind}`;
        this.status.textContent = message;
        this.status.style.display = message ? '' : 'none';
    }

    mappedCount() {
        return Object.values(this.mapping).filter(v => v !== null && v !== undefined).length;
    }

    render() {
        const p = this.preview;
        document.getElementById('import-title').textContent = `Import CSV into ${this.tab.state.tableName}`;
        const parts = [];

        const summary = this.el('div', 'import-summary');
        summary.append(this.el('strong', '', this.file.name));
        summary.append(this.el('span', 'import-muted', ` · ${p.total_rows.toLocaleString()} row${p.total_rows === 1 ? '' : 's'} · ${p.encoding === 'cp1252' || p.encoding === 'latin-1' ? 'Windows text encoding' : 'UTF-8'}`));
        parts.push(summary);

        if (p.problems.length) {
            const box = this.el('div', 'import-problems');
            box.setAttribute('role', 'alert');
            box.append(this.el('strong', '', 'This file cannot be imported as it is:'));
            const list = this.el('ul');
            p.problems.forEach(text => list.append(this.el('li', '', text)));
            box.append(list);
            box.append(this.el('div', 'import-muted', 'If the columns look wrong, try another delimiter below.'));
            parts.push(box);
        }

        parts.push(this.optionsRow());
        parts.push(this.mappingTable());

        const missing = p.table_columns.filter(c => c.required && (this.mapping[c.name] === null || this.mapping[c.name] === undefined));
        if (missing.length) {
            const warn = this.el('div', 'import-warning', `Not filled in: ${missing.map(c => c.name).join(', ')}. ${missing.length === 1 ? 'It is required and has' : 'They are required and have'} no default, so the database will probably refuse the rows.`);
            warn.setAttribute('role', 'status');
            parts.push(warn);
        }
        parts.push(this.previewTable());

        this.body.replaceChildren(...parts);
        this.checkButton.disabled = this.runButton.disabled = !!p.problems.length || this.mappedCount() === 0;
        this.runButton.textContent = `Import ${p.total_rows.toLocaleString()} row${p.total_rows === 1 ? '' : 's'}`;
        this.say('');
    }

    optionsRow() {
        const row = this.el('div', 'import-options');

        const delimiterLabel = this.el('label', '', 'Separator ');
        const select = this.el('select', 'form-control');
        select.id = 'import-delimiter';
        for (const [value, label] of [['comma', 'Comma ,'], ['semicolon', 'Semicolon ;'], ['tab', 'Tab'], ['pipe', 'Pipe |']]) {
            const option = this.el('option', '', label);
            option.value = value;
            select.append(option);
        }
        select.value = this.options.delimiter;
        select.addEventListener('change', () => { this.options.delimiter = select.value; this.loadPreview(false); });
        delimiterLabel.append(select);
        row.append(delimiterLabel);

        const checkbox = (id, text, key, reload) => {
            const label = this.el('label', 'import-check');
            const input = this.el('input');
            input.type = 'checkbox';
            input.id = id;
            input.checked = this.options[key];
            input.addEventListener('change', () => { this.options[key] = input.checked; if (reload) this.loadPreview(false); else this.render(); });
            label.append(input, document.createTextNode(' ' + text));
            return label;
        };
        row.append(checkbox('import-header', 'First row has column names', 'hasHeader', true));
        row.append(checkbox('import-null', 'Empty values become NULL', 'emptyAsNull', false));
        return row;
    }

    mappingTable() {
        const p = this.preview;
        const table = this.el('table', 'import-mapping');
        const head = this.el('tr');
        ['Table column', 'Comes from', 'First row'].forEach(text => head.append(this.el('th', '', text)));
        const thead = this.el('thead');
        thead.append(head);
        table.append(thead);
        const tbody = this.el('tbody');
        for (const column of p.table_columns) {
            const row = this.el('tr');
            const name = this.el('td', 'import-column');
            name.append(this.el('span', 'import-column-name', column.name));
            name.append(this.el('span', 'import-muted', ` ${column.type || ''}`));
            if (column.primary_key) name.append(this.el('span', 'import-tag', 'key'));
            if (column.required) name.append(this.el('span', 'import-tag import-tag-required', 'required'));
            row.append(name);

            const choose = this.el('td');
            const select = this.el('select', 'form-control');
            select.setAttribute('aria-label', `File column for ${column.name}`);
            select.dataset.column = column.name;
            const skip = this.el('option', '', "— don't import —");
            skip.value = '';
            select.append(skip);
            p.headers.forEach((header, index) => {
                const option = this.el('option', '', header || `(column ${index + 1})`);
                option.value = String(index);
                select.append(option);
            });
            const chosen = this.mapping[column.name];
            select.value = chosen === null || chosen === undefined ? '' : String(chosen);
            select.addEventListener('change', () => { this.mapping[column.name] = select.value === '' ? null : Number(select.value); this.render(); });
            choose.append(select);
            row.append(choose);

            const sample = p.sample_rows[0] && chosen !== null && chosen !== undefined ? p.sample_rows[0][chosen] : '';
            row.append(this.el('td', 'import-sample', sample === '' || sample === undefined ? '' : sample));
            tbody.append(row);
        }
        table.append(tbody);
        const wrap = this.el('div', 'import-mapping-wrap');
        wrap.append(table);
        return wrap;
    }

    previewTable() {
        const p = this.preview;
        const columns = p.table_columns.filter(c => this.mapping[c.name] !== null && this.mapping[c.name] !== undefined);
        const wrap = this.el('div', 'import-preview');
        wrap.append(this.el('div', 'import-muted', `What will be inserted (first ${p.sample_rows.length} of ${p.total_rows.toLocaleString()})`));
        if (!columns.length) { wrap.append(this.el('div', 'import-warning', 'Choose at least one column to import.')); return wrap; }
        const table = this.el('table', 'import-sample-table');
        const head = this.el('tr');
        columns.forEach(c => head.append(this.el('th', '', c.name)));
        const thead = this.el('thead');
        thead.append(head);
        table.append(thead);
        const body = this.el('tbody');
        p.sample_rows.forEach(r => {
            const tr = this.el('tr');
            columns.forEach(c => {
                const value = r[this.mapping[c.name]];
                const empty = value === '' && this.options.emptyAsNull;
                tr.append(this.el('td', empty ? 'import-null' : '', empty ? 'NULL' : value));
            });
            body.append(tr);
        });
        table.append(body);
        const scroll = this.el('div', 'import-preview-scroll');
        scroll.append(table);
        wrap.append(scroll);
        return wrap;
    }

    // ---- checking and importing -----------------------------------------------------------------------------

    setBusy(busy, label) {
        this.busy = busy;
        this.checkButton.disabled = this.runButton.disabled = busy || !!this.preview.problems.length || this.mappedCount() === 0;
        document.getElementById('import-cancel').disabled = busy;
        if (busy) this.say(label, 'busy');
    }

    async send(dryRun) {
        const mapping = {};
        for (const [column, index] of Object.entries(this.mapping)) if (index !== null && index !== undefined) mapping[column] = index;
        this.setBusy(true, dryRun ? 'Checking every row…' : 'Importing…');
        try {
            const { body } = await this.post('/api/import', this.form({
                mapping: JSON.stringify(mapping), empty_as_null: String(this.options.emptyAsNull), dry_run: String(dryRun) }));
            return body;
        } catch (error) {
            console.error('Import failed:', error);
            return { success: false, error: `Could not reach the app: ${error.message}` };
        } finally {
            this.setBusy(false);
        }
    }

    async run() {
        const conn = window.app.connectionManager.connections.find(c => c.id === this.tab.connectionId);
        if (window.app.connectionManager.isProduction(this.tab.connectionId)) {
            const n = this.preview.total_rows.toLocaleString();
            if (!(await ui.confirm(`Import ${n} row${this.preview.total_rows === 1 ? '' : 's'} into ${this.tab.state.tableName} on ${conn ? conn.name : 'this connection'}? This is a production database.`,
                { title: 'Change production data', confirmLabel: 'Import into production', safeDefault: true }))) return;
        }
        const result = await this.send(false);
        if (!result.success) {
            this.say(`Nothing was imported. ${result.error}`, 'error');
            return;
        }
        const table = this.tab.state.tableName;
        const tab = this.tab;
        this.close();
        ui.notify(`Imported ${result.imported.toLocaleString()} row${result.imported === 1 ? '' : 's'} into ${table}.`, 'success');
        await window.app.tabManager.loadTableData(tab);
    }

    async check() {
        const result = await this.send(true);
        if (result.success) this.say(`Looks good: all ${result.imported.toLocaleString()} rows can be imported. Nothing was changed.`, 'ok');
        else this.say(`${result.error}${result.rolled_back === false ? '' : ' Nothing was changed.'}`, 'error');
    }
}
