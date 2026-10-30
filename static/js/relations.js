// Foreign keys, made useful two ways:
//   1. In a table's grid, a value that points at another table is a link (↗), and a value that other tables point
//      at lists them (↘): click to land on exactly those rows.
//   2. The schema map: every table that takes part in a relationship, drawn so parents sit left of their children.
class RelationsManager {
    constructor() {
        this.cache = new Map();   // "connection|database" -> Promise<{tables, relations, outgoing, incoming}>
    }

    // ---- data ---------------------------------------------------------------------------------------

    load(connectionId, database, { force = false } = {}) {
        const key = `${connectionId}|${database}`;
        if (force || !this.cache.has(key)) {
            this.cache.set(key, (async () => {
                const body = await (await fetch(`/api/relations?connection_id=${connectionId}&database=${encodeURIComponent(database)}`)).json();
                if (!body.success) throw new Error(body.error || 'Could not read the relationships');
                const outgoing = new Map();  // table -> column -> {table, column}   (what this column points at)
                const incoming = new Map();  // table -> column -> [{table, column}]  (who points at this column)
                for (const r of body.relations) {
                    if (!outgoing.has(r.table)) outgoing.set(r.table, new Map());
                    outgoing.get(r.table).set(r.column, { table: r.referenced_table, column: r.referenced_column });
                    if (!incoming.has(r.referenced_table)) incoming.set(r.referenced_table, new Map());
                    const byColumn = incoming.get(r.referenced_table);
                    if (!byColumn.has(r.referenced_column)) byColumn.set(r.referenced_column, []);
                    byColumn.get(r.referenced_column).push({ table: r.table, column: r.column });
                }
                return { tables: body.tables, relations: body.relations, outgoing, incoming };
            })().catch(err => { this.cache.delete(key); throw err; }));
        }
        return this.cache.get(key);
    }

    invalidate(connectionId) {
        for (const key of [...this.cache.keys()]) {
            if (key.startsWith(`${connectionId}|`)) this.cache.delete(key);
        }
    }

    // ---- links in the data grid ---------------------------------------------------------------------

    async decorateGrid(tab, grid) {
        let data;
        try {
            data = await this.load(tab.connectionId, tab.state.database);
        } catch (err) {
            return;  // links are a bonus: a grid without them is still a working grid
        }
        const table = tab.state.tableName;
        const out = data.outgoing.get(table) || new Map();
        const inc = data.incoming.get(table) || new Map();
        if (!out.size && !inc.size) return;

        grid.querySelectorAll('td[data-column]').forEach(td => {
            const column = td.dataset.column;
            const value = td.dataset.originalValue;
            if (value === undefined || value === '' || td.classList.contains('new-cell')) return;
            if (out.has(column)) td.classList.add('fk');
            else if (inc.has(column)) td.classList.add('ref');
        });

        if (grid.dataset.linksBound) return;   // one delegated listener per grid, however often it re-renders
        grid.dataset.linksBound = '1';
        const inArrowZone = (td, e) => e.clientX >= td.getBoundingClientRect().right - 26;

        grid.addEventListener('mousemove', (e) => {
            const td = e.target.closest('td.fk, td.ref');
            if (td) td.style.cursor = (inArrowZone(td, e) || e.metaKey || e.ctrlKey) ? 'pointer' : '';
        });
        grid.addEventListener('click', (e) => {
            const td = e.target.closest('td.fk, td.ref');
            if (!td || !(inArrowZone(td, e) || e.metaKey || e.ctrlKey)) return;
            e.preventDefault();
            e.stopPropagation();
            const column = td.dataset.column;
            const value = td.dataset.originalValue;
            if (td.classList.contains('fk')) {
                const target = out.get(column);
                this.follow(tab, target.table, target.column, value);
            } else {
                this.chooseReferrer(e, tab, inc.get(column), value);
            }
        }, true);
    }

    follow(tab, table, column, value) {
        window.app.openTableData(tab.connectionId, tab.state.database, table, { column, value });
    }

    // A value can be pointed at from several tables: ask which, unless there is only one
    chooseReferrer(event, tab, referrers, value) {
        if (referrers.length === 1) {
            this.follow(tab, referrers[0].table, referrers[0].column, value);
            return;
        }
        document.querySelectorAll('.table-context-menu').forEach(m => m.remove());
        const menu = document.createElement('div');
        menu.className = 'table-context-menu';
        menu.style.left = Math.min(event.clientX, window.innerWidth - 240) + 'px';
        menu.style.top = Math.min(event.clientY, window.innerHeight - 40 - referrers.length * 30) + 'px';
        const heading = document.createElement('div');
        heading.className = 'context-menu-heading';
        heading.textContent = 'Rows pointing here';
        menu.appendChild(heading);
        referrers.forEach(r => {
            const item = document.createElement('div');
            item.className = 'context-menu-item';
            item.textContent = `${r.table}.${r.column}`;
            item.addEventListener('click', () => { menu.remove(); this.follow(tab, r.table, r.column, value); });
            menu.appendChild(item);
        });
        document.body.appendChild(menu);
        setTimeout(() => document.addEventListener('click', () => menu.remove(), { once: true }), 0);
    }

    // ---- the schema map -----------------------------------------------------------------------------

    static NODE_W = 196;
    static HEAD_H = 32;
    static ROW_H = 22;
    static GAP_X = 96;
    static GAP_Y = 26;

    // Parents (referenced tables) on the left, children on the right; order within a column reduces crossings
    static layout(relations) {
        const nodes = new Map();
        const node = (name) => {
            if (!nodes.has(name)) nodes.set(name, { name, rows: new Map(), parents: new Set(), children: new Set() });
            return nodes.get(name);
        };
        for (const r of relations) {
            const child = node(r.table), parent = node(r.referenced_table);
            child.rows.set(r.column, { ...(child.rows.get(r.column) || {}), fk: true });
            parent.rows.set(r.referenced_column, { ...(parent.rows.get(r.referenced_column) || {}), ref: true });
            if (r.table !== r.referenced_table) { child.parents.add(r.referenced_table); parent.children.add(r.table); }
        }

        // layer = 1 + the deepest parent; a cycle is cut where it closes
        const layerOf = new Map(), visiting = new Set();
        const depth = (name) => {
            if (layerOf.has(name)) return layerOf.get(name);
            if (visiting.has(name)) return 0;
            visiting.add(name);
            let d = 0;
            for (const p of nodes.get(name).parents) d = Math.max(d, depth(p) + 1);
            visiting.delete(name);
            layerOf.set(name, d);
            return d;
        };
        const layers = [];
        for (const n of nodes.values()) {
            n.layer = depth(n.name);
            n.h = RelationsManager.HEAD_H + n.rows.size * RelationsManager.ROW_H + 8;
            (layers[n.layer] = layers[n.layer] || []).push(n);
        }
        layers.forEach(l => l.sort((a, b) => a.name.localeCompare(b.name)));

        const centre = (n) => n.y + n.h / 2;
        for (let pass = 0; pass < 4; pass++) {
            layers.forEach((layer, i) => {
                layer.forEach(n => {
                    const near = [...(pass % 2 === 0 ? n.parents : n.children)].map(x => nodes.get(x)).filter(x => x.y !== undefined);
                    n.score = near.length ? near.reduce((s, x) => s + centre(x), 0) / near.length : (n.y !== undefined ? centre(n) : 0);
                });
                layer.sort((a, b) => a.score - b.score || a.name.localeCompare(b.name));
                let y = 0;
                layer.forEach(n => { n.y = y; y += n.h + RelationsManager.GAP_Y; });
            });
        }
        const heights = layers.map(l => l.reduce((s, n) => s + n.h + RelationsManager.GAP_Y, -RelationsManager.GAP_Y));
        const tallest = Math.max(...heights, 0);
        layers.forEach((layer, i) => {
            const offset = (tallest - heights[i]) / 2;
            layer.forEach(n => {
                n.x = i * (RelationsManager.NODE_W + RelationsManager.GAP_X);
                n.y += offset;
            });
        });
        return { nodes, width: layers.length * (RelationsManager.NODE_W + RelationsManager.GAP_X) - RelationsManager.GAP_X, height: tallest };
    }

    // A path through `points`, with each corner rounded
    static rounded(points, radius = 10) {
        let d = `M${points[0][0]},${points[0][1]}`;
        for (let i = 1; i < points.length - 1; i++) {
            const [px, py] = points[i - 1], [x, y] = points[i], [nx, ny] = points[i + 1];
            const r = Math.min(radius, Math.hypot(x - px, y - py) / 2, Math.hypot(nx - x, ny - y) / 2);
            const ux = Math.sign(x - px), uy = Math.sign(y - py), vx = Math.sign(nx - x), vy = Math.sign(ny - y);
            d += ` L${x - ux * r},${y - uy * r} Q${x},${y} ${x + vx * r},${y + vy * r}`;
        }
        const [lx, ly] = points[points.length - 1];
        return d + ` L${lx},${ly}`;
    }

    // Route one relationship. Between neighbouring columns a gentle curve is free of tables. Anything longer runs
    // through the empty gutters between columns and along a lane above or below every table, so it can never pass
    // behind an unrelated one. `lanes` hands out a fresh lane each time so parallel edges do not overlap.
    static route(child, parent, y1, y2, frame) {
        const R = RelationsManager, W = R.NODE_W;
        const gutter = (layer) => layer * (W + R.GAP_X) - R.GAP_X / 2;       // the empty strip left of a column
        if (child === parent) {                                                // a table that points at itself
            const x = child.x;
            return `M${x},${y1} C${x - 70},${y1} ${x - 70},${y2} ${x},${y2}`;
        }
        if (parent.layer === child.layer - 1) {                                // neighbouring columns
            const x1 = child.x, x2 = parent.x + W, dx = Math.max(40, (x1 - x2) / 2);
            return `M${x1},${y1} C${x1 - dx},${y1} ${x2 + dx},${y2} ${x2},${y2}`;
        }
        const above = (y1 + y2) / 2 < frame.mid;
        const lane = above ? frame.top - 18 - 11 * frame.above++ : frame.bottom + 18 + 11 * frame.below++;
        const jitter = ((frame.lanes++ % 5) - 2) * 7;                          // keep vertical runs in a gutter apart
        const toChild = gutter(child.layer) + jitter;
        if (parent.layer < child.layer) {                                      // a skipped column: enter the parent from the right
            const toParent = gutter(parent.layer + 1) + jitter;
            return R.rounded([[child.x, y1], [toChild, y1], [toChild, lane], [toParent, lane], [toParent, y2], [parent.x + W, y2]]);
        }
        const toParentLeft = gutter(parent.layer) + jitter;                    // same column or a cycle: enter from the left
        return R.rounded([[child.x, y1], [toChild, y1], [toChild, lane], [toParentLeft, lane], [toParentLeft, y2], [parent.x, y2]]);
    }

    async renderMap(tab) {
        const root = document.getElementById(`map-${tab.id}`);
        if (!root) return;
        // window-level listeners belong to one render: drop the previous render's before adding new ones
        if (tab.mapListeners) tab.mapListeners.abort();
        tab.mapListeners = new AbortController();
        const { signal } = tab.mapListeners;
        const canvas = root.querySelector('.map-canvas');
        const info = root.querySelector('.map-info');
        const loose = root.querySelector('.map-loose');
        canvas.innerHTML = '<div class="spinner"></div>';
        let data;
        try {
            data = await this.load(tab.connectionId, tab.state.database, { force: true });
        } catch (err) {
            canvas.innerHTML = `<div class="error-message">Could not draw the map: ${escapeHtml(err.message)}</div>`;
            return;
        }

        const { nodes, width, height } = RelationsManager.layout(data.relations);
        const NS = 'http://www.w3.org/2000/svg';
        const el = (name, attrs = {}, parent) => {
            const e = document.createElementNS(NS, name);
            for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
            if (parent) parent.appendChild(e);
            return e;
        };

        const linked = new Set(nodes.keys());
        const unlinked = data.tables.filter(t => !linked.has(t.name));
        info.textContent = `${data.tables.length} tables, ${data.relations.length} relationship${data.relations.length === 1 ? '' : 's'}`;
        loose.innerHTML = '';
        if (unlinked.length) {
            const label = document.createElement('span');
            label.className = 'map-loose-label';
            label.textContent = linked.size ? 'No relationships:' : 'Tables:';
            loose.appendChild(label);
            unlinked.forEach(t => {
                const chip = document.createElement('button');
                chip.className = 'map-chip';
                chip.textContent = t.name;
                chip.addEventListener('click', () => window.app.openTableData(tab.connectionId, tab.state.database, t.name));
                loose.appendChild(chip);
            });
        }
        loose.style.display = unlinked.length ? '' : 'none';

        canvas.innerHTML = '';
        if (!linked.size) {
            canvas.innerHTML = '<div class="map-empty"><strong>No foreign keys found.</strong><br>' +
                'This database does not declare relationships between its tables, so there is nothing to draw. ' +
                'Its tables are listed below.</div>';
            return;
        }

        const svg = el('svg', { class: 'map-svg', width: '100%', height: '100%' }, canvas);
        const defs = el('defs', {}, svg);
        const marker = el('marker', { id: `arrow-${tab.id}`, viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse' }, defs);
        el('path', { d: 'M0,1 L9,5 L0,9 z', class: 'map-arrow' }, marker);
        const viewport = el('g', { class: 'map-viewport' }, svg);
        const edgeLayer = el('g', { class: 'map-edges' }, viewport);
        const nodeLayer = el('g', { class: 'map-nodes' }, viewport);

        const R = RelationsManager;
        const rowY = (n, col) => n.y + R.HEAD_H + [...n.rows.keys()].indexOf(col) * R.ROW_H + R.ROW_H / 2;
        const edges = [];
        const all = [...nodes.values()];
        const frame = { top: Math.min(...all.map(n => n.y)), bottom: Math.max(...all.map(n => n.y + n.h)), above: 0, below: 0, lanes: 0 };
        frame.mid = (frame.top + frame.bottom) / 2;
        // longest first, so the edges that travel furthest get the lanes closest to the tables
        const ordered = [...data.relations].sort((a, b) =>
            Math.abs(nodes.get(b.table).layer - nodes.get(b.referenced_table).layer) - Math.abs(nodes.get(a.table).layer - nodes.get(a.referenced_table).layer));
        for (const r of ordered) {
            const child = nodes.get(r.table), parent = nodes.get(r.referenced_table);
            const d = RelationsManager.route(child, parent, rowY(child, r.column), rowY(parent, r.referenced_column), frame);
            const path = el('path', { d, class: 'map-edge', 'marker-end': `url(#arrow-${tab.id})` }, edgeLayer);
            el('title', {}, path).textContent = `${r.table}.${r.column} → ${r.referenced_table}.${r.referenced_column}`;
            edges.push({ path, from: r.table, to: r.referenced_table });
        }

        const nodeEls = new Map();
        for (const n of nodes.values()) {
            const g = el('g', { class: 'map-node', transform: `translate(${n.x},${n.y})`, 'data-table': n.name, tabindex: '0', role: 'button', 'aria-label': `Open table ${n.name}` }, nodeLayer);
            el('rect', { class: 'map-node-box', width: R.NODE_W, height: n.h, rx: 7 }, g);
            el('rect', { class: 'map-node-head', width: R.NODE_W, height: R.HEAD_H, rx: 7 }, g);
            const title = el('text', { class: 'map-node-title', x: 12, y: R.HEAD_H / 2 + 4.5 }, g);
            title.textContent = n.name.length > 22 ? n.name.slice(0, 21) + '…' : n.name;
            el('title', {}, g).textContent = n.name;
            [...n.rows.entries()].forEach(([col, role], i) => {
                const y = R.HEAD_H + i * R.ROW_H + R.ROW_H / 2 + 4;
                const t = el('text', { class: `map-col ${role.fk ? 'is-fk' : 'is-ref'}`, x: 12, y }, g);
                t.textContent = col.length > 20 ? col.slice(0, 19) + '…' : col;
                const tag = el('text', { class: 'map-col-tag', x: R.NODE_W - 12, y, 'text-anchor': 'end' }, g);
                tag.textContent = role.fk ? 'FK' : 'ref';
            });
            const open = () => window.app.openTableData(tab.connectionId, tab.state.database, n.name);
            g.addEventListener('click', (e) => { if (!svg.dataset.dragged) open(); });
            g.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
            g.addEventListener('mouseenter', () => focusOn(n.name));
            g.addEventListener('mouseleave', () => focusOn(null));
            nodeEls.set(n.name, g);
        }

        // hovering a table lights up what it touches and quiets everything else
        function focusOn(name) {
            svg.classList.toggle('has-focus', !!name);
            const touching = new Set(name ? [name] : []);
            edges.forEach(e => {
                const on = name && (e.from === name || e.to === name);
                e.path.classList.toggle('on', !!on);
                if (on) { touching.add(e.from); touching.add(e.to); }
            });
            nodeEls.forEach((g, n) => g.classList.toggle('on', touching.has(n)));
        }

        // pan and zoom
        const view = { x: 0, y: 0, k: 1 };
        const apply = () => viewport.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
        const zoomAt = (factor, cx, cy) => {
            const k = Math.min(2.5, Math.max(0.15, view.k * factor));
            view.x = cx - (cx - view.x) * (k / view.k);
            view.y = cy - (cy - view.y) * (k / view.k);
            view.k = k;
            apply();
        };
        const fit = () => {
            const box = canvas.getBoundingClientRect();
            viewport.removeAttribute('transform');
            const bb = viewport.getBBox();                       // everything drawn, edges and lanes included
            const k = Math.min(1.1, (box.width - 80) / Math.max(bb.width, 1), (box.height - 80) / Math.max(bb.height, 1));
            view.k = Math.max(0.15, k);
            view.x = (box.width - bb.width * view.k) / 2 - bb.x * view.k;
            view.y = (box.height - bb.height * view.k) / 2 - bb.y * view.k;
            apply();
        };
        const centreOn = (name) => {
            const n = nodes.get(name), box = canvas.getBoundingClientRect();
            view.k = Math.max(view.k, 0.9);
            view.x = box.width / 2 - (n.x + R.NODE_W / 2) * view.k;
            view.y = box.height / 2 - (n.y + n.h / 2) * view.k;
            apply();
        };
        svg.addEventListener('wheel', (e) => {
            e.preventDefault();
            const box = svg.getBoundingClientRect();
            zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - box.left, e.clientY - box.top);
        }, { passive: false });
        let drag = null;
        svg.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
            delete svg.dataset.dragged;
        });
        window.addEventListener('mousemove', (e) => {
            if (!drag) return;
            const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
            if (Math.abs(dx) + Math.abs(dy) > 4) { drag.moved = true; svg.dataset.dragged = '1'; }
            if (drag.moved) { view.x = drag.vx + dx; view.y = drag.vy + dy; apply(); }
        }, { signal });
        window.addEventListener('mouseup', () => { drag = null; setTimeout(() => delete svg.dataset.dragged, 0); }, { signal });

        const box = canvas.getBoundingClientRect();
        root.querySelector('[data-map=fit]').onclick = fit;
        root.querySelector('[data-map=zoom-in]').onclick = () => zoomAt(1.25, box.width / 2, box.height / 2);
        root.querySelector('[data-map=zoom-out]').onclick = () => zoomAt(0.8, box.width / 2, box.height / 2);
        root.querySelector('[data-map=refresh]').onclick = () => this.renderMap(tab);

        const search = root.querySelector('.map-search');
        const doSearch = () => {
            const term = search.value.trim().toLowerCase();
            nodeEls.forEach((g, name) => {
                g.classList.toggle('match', !!term && name.toLowerCase().includes(term));
                g.classList.toggle('faded', !!term && !name.toLowerCase().includes(term));
            });
            return term ? [...nodes.keys()].find(n => n.toLowerCase().includes(term)) : null;
        };
        search.oninput = doSearch;
        search.onkeydown = (e) => { if (e.key === 'Enter') { const first = doSearch(); if (first) centreOn(first); } };
        search.value = '';

        requestAnimationFrame(() => { fit(); svg.dataset.ready = '1'; });
    }
}
