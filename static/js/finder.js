// Finding relationships the database never declared (see relationship_inference.py). Suggestions come with their
// evidence; nothing changes until the user accepts one, and accepting only changes this app, never the database.
// Table and column names are untrusted text: only textContent here.
class RelationshipFinder {
    constructor() {
        this.running = new Set();
    }

    el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    panel(tab) {
        return document.querySelector(`#map-${tab.id} .map-suggest`);
    }

    toggle(tab) {
        const panel = this.panel(tab);
        if (!panel) return;
        if (panel.style.display === 'none' || !panel.dataset.open) this.open(tab);
        else this.close(tab);
    }

    close(tab) {
        const panel = this.panel(tab);
        if (!panel) return;
        panel.style.display = 'none';
        delete panel.dataset.open;
    }

    async open(tab) {
        const panel = this.panel(tab);
        if (!panel) return;
        panel.style.display = '';
        panel.dataset.open = '1';
        await this.run(tab);
    }

    async request(url, options) {
        const response = await fetch(url, options && options.body
            ? { ...options, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options.body) } : options);
        return response.json();
    }

    query(tab) {
        return `connection_id=${encodeURIComponent(tab.connectionId)}&database=${encodeURIComponent(tab.state.database || '')}`;
    }

    async run(tab) {
        const panel = this.panel(tab);
        if (!panel || this.running.has(tab.id)) return;
        this.running.add(tab.id);
        panel.replaceChildren(this.header(tab, null), this.el('div', 'spinner'), this.el('p', 'map-suggest-note',
            'Comparing column names with the data. This reads a sample of each column, not the whole table.'));
        try {
            const [found, decisions] = await Promise.all([
                this.request(`/api/relations/inferred?${this.query(tab)}`),
                this.request(`/api/relations/decisions?${this.query(tab)}`)]);
            if (!found.success) throw new Error(found.error || 'Could not look for relationships.');
            this.render(tab, found, decisions.success ? decisions : { accepted: [], ignored: [] });
        } catch (error) {
            panel.replaceChildren(this.header(tab, null), this.el('div', 'map-suggest-error', error.message));
        } finally {
            this.running.delete(tab.id);
        }
    }

    header(tab, summary) {
        const head = this.el('div', 'map-suggest-head');
        head.append(this.el('strong', '', 'Relationships found in the data'));
        if (summary) head.append(this.el('span', 'map-suggest-summary', summary));
        const close = this.el('button', 'btn btn-sm', 'Close');
        close.type = 'button';
        close.addEventListener('click', () => this.close(tab));
        head.append(close);
        return head;
    }

    describe(s) {
        const target = `${s.referenced_table}.${s.referenced_column}`;
        if (!s.orphans) {
            return s.distinct === 1 ? `The only value in ${s.table}.${s.column} exists in ${target}.`
                : `All ${s.distinct.toLocaleString()} distinct values in ${s.table}.${s.column} exist in ${target}.`;
        }
        return `${s.matched.toLocaleString()} of ${s.distinct.toLocaleString()} distinct values exist in ${target}. ` +
            `${s.orphans.toLocaleString()} point${s.orphans === 1 ? 's' : ''} at nothing.`;
    }

    render(tab, found, decisions) {
        const panel = this.panel(tab);
        const parts = [];
        const n = found.suggestions.length;
        parts.push(this.header(tab, `${n} suggestion${n === 1 ? '' : 's'} · checked ${found.examined} column${found.examined === 1 ? '' : 's'} in ${found.seconds}s`));

        if (found.truncated) {
            parts.push(this.el('div', 'map-suggest-warning', 'The search was cut short (time or size limit), so there may be more. What was found is shown.'));
        }
        if (!n) {
            parts.push(this.el('p', 'map-suggest-note', 'Nothing new. Columns named like a reference (such as customer_id) were checked against the data of the table they seem to point at, and none matched.'));
        }
        const list = this.el('div', 'map-suggest-list');
        found.suggestions.forEach(s => list.append(this.row(tab, s)));
        parts.push(list);

        if (n) {
            parts.push(this.el('p', 'map-suggest-note', 'Accepting makes it work like a foreign key in this app: the ↗ and ↘ links in the grid, and the map. Your database is not changed.'));
        }
        if (decisions.accepted.length) parts.push(this.decided(tab, 'Accepted by you', decisions.accepted, 'Forget'));
        if (decisions.ignored.length) parts.push(this.decided(tab, 'Ignored', decisions.ignored, 'Suggest again'));
        panel.replaceChildren(...parts);
    }

    row(tab, s) {
        const row = this.el('div', 'map-suggest-item');
        row.dataset.relation = `${s.table}.${s.column}`;
        const main = this.el('div', 'map-suggest-main');
        const title = this.el('div', 'map-suggest-title');
        title.append(this.el('span', 'map-suggest-name', `${s.table}.${s.column}`), document.createTextNode(' → '),
            this.el('span', 'map-suggest-name', `${s.referenced_table}.${s.referenced_column}`));
        const tag = this.el('span', `map-suggest-confidence ${s.confidence}`, s.confidence);
        tag.title = s.confidence === 'high' ? 'Many different values, and all of them exist in the other table'
            : s.confidence === 'medium' ? 'Some different values, all of them exist in the other table'
            : s.orphans ? 'Some values point at nothing' : 'Only a few different values to go on';
        title.append(tag);
        main.append(title, this.el('div', 'map-suggest-evidence', this.describe(s)));
        if (s.orphans) {
            const show = this.el('button', 'btn btn-sm', 'Show the rows');
            show.type = 'button';
            show.dataset.act = 'orphans';
            show.addEventListener('click', () => window.app.explorer.openOrphans(tab, s));
            main.append(show);
        }
        row.append(main);

        const actions = this.el('div', 'map-suggest-actions');
        const accept = this.el('button', 'btn btn-sm btn-primary', 'Accept');
        const ignore = this.el('button', 'btn btn-sm', 'Ignore');
        accept.type = ignore.type = 'button';
        accept.dataset.act = 'accept';
        ignore.dataset.act = 'ignore';
        accept.addEventListener('click', () => this.decide(tab, s, 'accept', row));
        ignore.addEventListener('click', () => this.decide(tab, s, 'ignore', row));
        actions.append(accept, ignore);
        row.append(actions);
        return row;
    }

    decided(tab, title, items, undoLabel) {
        const box = this.el('details', 'map-suggest-decided');
        box.append(this.el('summary', '', `${title} (${items.length})`));
        items.forEach(r => {
            const line = this.el('div', 'map-suggest-decided-row');
            line.append(this.el('span', 'map-suggest-name', `${r.table}.${r.column} → ${r.referenced_table}.${r.referenced_column}`));
            const undo = this.el('button', 'btn btn-sm', undoLabel);
            undo.type = 'button';
            undo.dataset.act = 'forget';
            undo.addEventListener('click', () => this.decide(tab, r, 'forget'));
            line.append(undo);
            box.append(line);
        });
        return box;
    }

    async decide(tab, relation, action, row) {
        if (row) row.querySelectorAll('button').forEach(b => { b.disabled = true; });
        try {
            const body = await this.request('/api/relations/decision', { method: 'POST', body: {
                connection_id: tab.connectionId, database: tab.state.database || '', action,
                relation: { table: relation.table, column: relation.column, referenced_table: relation.referenced_table, referenced_column: relation.referenced_column },
                evidence: relation } });
            if (!body.success) { ui.notify(body.error || 'Could not save that.', 'error'); this.run(tab); return; }
        } catch (error) {
            ui.notify(`Could not save that: ${error.message}`, 'error');
            return;
        }
        window.app.relations.invalidate(tab.connectionId);
        if (action !== 'ignore') await window.app.relations.renderMap(tab);   // the new link appears on the map
        ui.notify(action === 'accept' ? `Now following ${relation.table}.${relation.column} → ${relation.referenced_table}.`
            : action === 'ignore' ? 'Ignored. It will not be suggested again.' : 'Forgotten.', action === 'ignore' ? 'warning' : 'success');
        await this.run(tab);
    }
}
