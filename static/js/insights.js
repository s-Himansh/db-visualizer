// Column insights: click the ▾ on a column header to see what is in that column.
class ColumnInsights {
    constructor() {
        this.panel = null;
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.panel) { e.stopPropagation(); this.close(); }
        }, true);
        document.addEventListener('mousedown', (e) => {
            if (this.panel && !this.panel.contains(e.target) && !e.target.closest('.th-insight')) this.close();
        });
        window.addEventListener('resize', () => this.close());
    }

    static SQL = ['sqlite', 'postgresql', 'mysql', 'sqlserver', 'oracle'];

    static supported(connectionType) {
        return ColumnInsights.SQL.includes(connectionType);
    }

    attach(tab, grid) {
        if (grid.dataset.insightsBound) return;
        grid.dataset.insightsBound = '1';
        grid.addEventListener('click', (e) => {
            const button = e.target.closest('.th-insight');
            if (!button) return;
            e.stopPropagation();
            this.toggle(tab, button);
        });
        grid.addEventListener('scroll', () => this.close(), { passive: true });
    }

    close() {
        if (!this.panel) return;
        this.panel.remove();
        this.panel = null;
    }

    async toggle(tab, button) {
        const column = button.closest('th').dataset.col;
        if (this.panel && this.panel.dataset.column === column && this.panel.dataset.tab === tab.id) { this.close(); return; }
        this.close();

        const panel = document.createElement('div');
        panel.className = 'insight';
        panel.dataset.column = column;
        panel.dataset.tab = tab.id;
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-label', `About column ${column}`);
        panel.innerHTML = '<div class="insight-head"><span class="insight-name"></span><span class="insight-type"></span>' +
            '<button type="button" class="insight-close" aria-label="Close">×</button></div><div class="insight-body"><div class="spinner"></div></div>';
        panel.querySelector('.insight-name').textContent = column;
        panel.querySelector('.insight-close').addEventListener('click', () => this.close());
        document.body.appendChild(panel);
        this.panel = panel;
        this.place(panel, button);

        try {
            const params = new URLSearchParams({ connection_id: tab.connectionId, database: tab.state.database, table: tab.state.tableName, column });
            const body = await (await fetch(`/api/profile?${params}`)).json();
            if (this.panel !== panel) return;   // closed or replaced while loading
            if (!body.success) throw new Error(body.error || 'Could not read this column');
            this.render(panel, tab, body.profile);
        } catch (err) {
            if (this.panel !== panel) return;
            const msg = document.createElement('div');
            msg.className = 'insight-error';
            msg.textContent = err.message;
            panel.querySelector('.insight-body').replaceChildren(msg);
        }
        this.place(panel, button);
    }

    place(panel, button) {
        const r = button.getBoundingClientRect();
        const w = panel.offsetWidth || 320;
        panel.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
        const below = r.bottom + 6;
        panel.style.top = (below + panel.offsetHeight > window.innerHeight - 8 ? Math.max(8, window.innerHeight - panel.offsetHeight - 8) : below) + 'px';
    }

    render(panel, tab, p) {
        const n = (v) => v == null ? '—' : Number(v).toLocaleString();
        const short = (v) => v == null ? '—' : (String(v).length > 22 ? String(v).slice(0, 21) + '…' : String(v));
        const pct = (part, whole) => whole ? Math.round((part / whole) * 100) : 0;
        const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

        panel.querySelector('.insight-type').textContent = p.type || '';
        const body = panel.querySelector('.insight-body');
        body.replaceChildren();

        const facts = el('dl', 'insight-facts');
        const fact = (label, value, title) => { facts.append(el('dt', null, label)); const d = el('dd', null, value); if (title) d.title = title; facts.append(d); };
        fact('Rows', n(p.total));
        fact('Empty', `${n(p.nulls)} (${pct(p.nulls, p.total)}%)`);
        fact('Distinct', n(p.distinct));
        fact('Lowest', short(p.min), p.min == null ? null : String(p.min));
        fact('Highest', short(p.max), p.max == null ? null : String(p.max));
        if (p.avg != null) fact('Average', Number(p.avg).toLocaleString(undefined, { maximumFractionDigits: 2 }));
        body.append(facts);

        const filled = el('div', 'insight-meter');
        const fill = el('span'); fill.style.width = pct(p.non_null, p.total) + '%';
        filled.title = `${pct(p.non_null, p.total)}% filled`;
        filled.append(fill);
        body.append(filled);

        if (p.histogram) {
            const max = Math.max(...p.histogram.map(h => h.count), 1);
            const chart = el('div', 'insight-hist');
            p.histogram.forEach(h => {
                const bar = el('span');
                bar.style.height = Math.max(h.count ? 3 : 0, Math.round((h.count / max) * 100)) + '%';
                bar.title = `${Number(h.from).toLocaleString(undefined, { maximumFractionDigits: 2 })} to ${Number(h.to).toLocaleString(undefined, { maximumFractionDigits: 2 })}: ${h.count.toLocaleString()} rows`;
                chart.append(bar);
            });
            body.append(el('div', 'insight-sub', 'Spread of values'), chart);
            const axis = el('div', 'insight-axis');
            axis.append(el('span', null, short(p.min)), el('span', null, short(p.max)));
            body.append(axis);
        }

        if (p.top && p.top.length) {
            body.append(el('div', 'insight-sub', 'Most common values'));
            const list = el('div', 'insight-top');
            const biggest = Math.max(...p.top.map(t => t.count), 1);
            p.top.forEach(t => {
                const text = String(t.value);
                const row = el('button', 'insight-row');
                row.type = 'button';
                row.title = `Show only rows where ${p.column} = ${text}`;
                const bar = el('span', 'insight-bar'); bar.style.width = Math.round((t.count / biggest) * 100) + '%';
                row.append(bar, el('span', 'insight-val', text), el('span', 'insight-count', `${t.count.toLocaleString()} · ${pct(t.count, p.non_null)}%`));
                if (text.endsWith('...')) row.disabled = true;   // a shortened value cannot be matched exactly
                row.addEventListener('click', () => {
                    this.close();
                    window.app.openTableData(tab.connectionId, tab.state.database, tab.state.tableName, { column: p.column, value: text });
                });
                list.append(row);
            });
            body.append(list);
        }
        if (p.sampled) body.append(el('div', 'insight-note', `Based on the first ${p.sample_rows.toLocaleString()} rows of a large table.`));
    }
}
