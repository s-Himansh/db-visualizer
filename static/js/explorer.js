// Record explorer: one row and the rows linked to it, in both directions, through declared and accepted relationships.
// Read-only. Row values are user data: they only ever reach the page through textContent.
class RecordExplorer {
    static PER_GROUP = 5;

    constructor() {
        this.modal = document.getElementById('explorer-modal');
        this.title = document.getElementById('explorer-title');
        this.body = document.getElementById('explorer-body');
        this.back = document.getElementById('explorer-back');
        this.trail = [];   // the rows visited, so Back works
        this.ctx = null;   // {tab, relations} of the grid the explorer was opened from

        document.getElementById('explorer-close').addEventListener('click', () => this.close());
        this.modal.addEventListener('mousedown', (e) => { if (e.target === this.modal) this.close(); });
        this.back.addEventListener('click', () => { this.trail.pop(); const { table, row } = this.trail.pop(); this.show(table, row); });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.classList.contains('active') && !document.querySelector('.app-dialog')) this.close();
        });
    }

    async open(tab, table, row) {
        this.ctx = { tab, relations: [] };
        this.trail = [];
        this.modal.classList.add('active');
        try {
            this.ctx.relations = (await window.app.relations.load(tab.connectionId, tab.state.database)).relations;
        } catch (err) {
            this.body.replaceChildren(this.note(err.message));
            return;
        }
        this.show(table, row);
    }

    close() {
        this.modal.classList.remove('active');
        this.trail = [];
    }

    async show(table, row) {
        const here = { table, row };
        this.trail.push(here);
        this.back.hidden = this.trail.length < 2;
        this.title.textContent = `${table}: ${this.summary(row, 3)}`;
        this.body.replaceChildren(this.note('Looking for linked rows…'));

        const { relations } = this.ctx;
        const links = [
            ...relations.filter(r => r.table === table).map(r => ({ kind: 'to', table: r.referenced_table, column: r.referenced_column, via: r.column, value: row[r.column] })),
            ...relations.filter(r => r.referenced_table === table).map(r => ({ kind: 'from', table: r.table, column: r.column, via: r.referenced_column, value: row[r.referenced_column] })),
        ].filter(l => l.value !== undefined && l.value !== null && l.value !== '');
        const groups = await Promise.all(links.map(l => this.fetchGroup(l)));
        if (this.trail[this.trail.length - 1] !== here) return;   // the user moved on while this was loading

        const parts = [];
        for (const [kind, heading] of [['to', 'Points to'], ['from', 'Referenced by']]) {
            const found = groups.filter(g => g.kind === kind && g.total > 0);
            if (found.length) parts.push(this.heading(heading), ...found.map(g => this.groupBox(g)));
        }
        const empty = groups.filter(g => !g.error && g.total === 0).map(g => `${g.table}.${g.column}`);
        if (empty.length) parts.push(this.note(`Nothing found in: ${empty.join(', ')}`));
        for (const g of groups.filter(g => g.error)) parts.push(this.note(`Could not read ${g.table}: ${g.error}`));
        if (!links.length) parts.push(this.note('This row has no linked values.'));
        this.body.replaceChildren(...parts);
    }

    async fetchGroup(link) {
        const { tab } = this.ctx;
        const query = new URLSearchParams({
            connection_id: tab.connectionId, database: tab.state.database ?? '', table: link.table,
            limit: RecordExplorer.PER_GROUP, where_column: link.column, where_value: link.value,
        });
        try {
            const body = await (await fetch(`/api/data?${query}`)).json();
            if (!body.success) throw new Error(body.error || 'Could not read the rows');
            return { ...link, rows: body.data.rows, total: body.data.total_count };
        } catch (err) {
            return { ...link, rows: [], total: 0, error: err.message };
        }
    }

    // ---- drawing ------------------------------------------------------------------------------------

    summary(row, count) {
        const show = (v) => { const s = typeof v === 'object' ? JSON.stringify(v) : String(v); return s.length > 28 ? s.slice(0, 27) + '…' : s; };
        return Object.entries(row).filter(([, v]) => v !== null && v !== '').slice(0, count).map(([k, v]) => `${k} ${show(v)}`).join(' · ') || '(empty row)';
    }

    el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    note(text) { return this.el('p', 'form-hint', text); }

    heading(text) { return this.el('h4', 'explore-heading', text); }

    groupBox(group) {
        const box = this.el('div', 'explore-group');
        const head = this.el('div', 'explore-group-head');
        head.append(this.el('span', 'explore-group-name', group.table),
            this.el('span', 'explore-group-via', group.kind === 'to' ? `${group.via} → ${group.column}` : `${group.column} → ${group.via}`),
            this.el('span', 'explore-group-count', String(group.total)));
        box.appendChild(head);
        for (const row of group.rows) {
            const item = this.el('button', 'explore-row', this.summary(row, 4));
            item.type = 'button';
            item.addEventListener('click', () => this.show(group.table, row));
            box.appendChild(item);
        }
        if (group.total > group.rows.length) {
            const all = this.el('button', 'explore-all', `Show all ${group.total} in the grid`);
            all.type = 'button';
            all.addEventListener('click', () => { this.close(); window.app.relations.follow(this.ctx.tab, group.table, group.column, group.value); });
            box.appendChild(all);
        }
        return box;
    }
}
