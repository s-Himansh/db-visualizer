// The open connections, kept out of the way: a thin handle on the left edge (one dot per open connection) and a panel
// that slides over the sidebar. Both float above the page, so opening or closing them never resizes anything.
// Names are user data: they only ever reach the page through textContent.
class ConnectionSwitcher {
    constructor() {
        this.handle = document.createElement('button');
        this.handle.type = 'button';
        this.handle.id = 'switcher-handle';
        this.handle.hidden = true;
        this.handle.setAttribute('aria-label', 'Open connections');
        this.handle.setAttribute('aria-expanded', 'false');
        this.panel = document.createElement('div');
        this.panel.id = 'switcher-panel';
        this.panel.setAttribute('role', 'dialog');
        this.panel.setAttribute('aria-label', 'Open connections');
        document.body.append(this.handle, this.panel);
        this.open = [];          // the open connections, in the order the panel lists them
        this.byHover = false;    // opened by hovering: it also closes when the pointer leaves
        this.timer = null;

        this.handle.addEventListener('mouseenter', () => this.later(() => this.show(true), 120));
        this.handle.addEventListener('click', () => this.toggle());
        this.panel.addEventListener('mouseenter', () => clearTimeout(this.timer));
        for (const el of [this.handle, this.panel]) {
            el.addEventListener('mouseleave', () => { if (this.byHover) this.later(() => this.hide(), 250); });
        }
        this.panel.addEventListener('keydown', (e) => this.onPanelKey(e));
        document.addEventListener('keydown', (e) => this.onKey(e));
        setTimeout(() => this.render(), 0);   // window.app does not exist yet while the app is still being built
    }

    get isOpen() { return this.panel.classList.contains('open'); }

    later(fn, ms) { clearTimeout(this.timer); this.timer = setTimeout(fn, ms); }

    show(byHover = false) {
        if (!this.open.length) return;
        this.byHover = byHover;
        this.panel.classList.add('open');
        this.handle.setAttribute('aria-expanded', 'true');
    }

    hide() {
        clearTimeout(this.timer);
        this.panel.classList.remove('open');
        this.handle.setAttribute('aria-expanded', 'false');
    }

    toggle() {
        if (this.isOpen && !this.byHover) { this.hide(); return; }
        this.show(false);
        const target = this.panel.querySelector('.switch-row.active .switch-main') || this.panel.querySelector('.switch-main');
        if (target) target.focus();
    }

    // ---- drawing ------------------------------------------------------------------------------------

    render() {
        const cm = window.app && window.app.connectionManager;
        if (!cm) return;
        this.open = [...cm.connectedConnections].map(id => cm.connections.find(c => c.id === id)).filter(Boolean);
        const active = cm.activeConnection && cm.activeConnection.id;
        this.handle.hidden = !this.open.length;
        if (!this.open.length) this.hide();

        this.handle.replaceChildren(...this.open.map(c => {
            const dot = this.el('span', `switch-dot${c.id === active ? ' active' : ''}${c.environment === 'production' ? ' env-production' : ''}`);
            dot.title = c.name;
            return dot;
        }));

        const rows = this.open.map((c, i) => this.row(cm, c, c.id === active, i));
        const add = this.el('button', 'switch-add', '+ New connection');
        add.type = 'button';
        add.addEventListener('click', () => { this.hide(); document.getElementById('manage-connections-btn').click(); });
        this.panel.replaceChildren(this.el('div', 'switch-title', 'Open connections'), ...rows, add);
    }

    row(cm, conn, active, index) {
        const row = this.el('div', `switch-row${active ? ' active' : ''}`);
        row.dataset.connectionId = conn.id;
        const main = this.el('button', 'switch-main');
        main.type = 'button';
        const words = conn.name.trim().split(/\s+|[-_]+/).filter(Boolean);
        const initials = (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || '?').slice(0, 2)).toUpperCase();
        const avatar = this.el('span', 'switch-avatar', initials);
        let hue = 0;
        for (const ch of conn.name) hue = (hue * 31 + ch.charCodeAt(0)) % 360;
        avatar.style.background = `hsl(${hue} 42% 42%)`;
        if (conn.environment === 'production') avatar.classList.add('env-production');
        const name = this.el('span', 'switch-name', conn.name);
        const tags = this.el('span', 'switch-tags');
        tags.innerHTML = cm.envTag(conn) + (conn.read_only ? '<span class="ro-tag" title="Writes are blocked on this connection">read-only</span>' : '');
        const key = this.el('kbd', 'switch-key', index < 9 ? `⌘${index + 1}` : '');
        const text = this.el('span', 'switch-text');
        text.append(name, tags);
        main.append(avatar, text, key);
        main.addEventListener('click', () => { cm.switchToConnection(conn.id); this.hide(); });

        const close = this.el('button', 'switch-close', '×');
        close.type = 'button';
        close.setAttribute('aria-label', `Disconnect ${conn.name}`);
        close.addEventListener('click', () => cm.disconnect(conn.id));
        row.append(main, close);
        row.addEventListener('contextmenu', (e) => { e.preventDefault(); this.menu(e, cm, conn); });
        return row;
    }

    menu(event, cm, conn) {
        document.querySelectorAll('.table-context-menu').forEach(m => m.remove());
        const menu = this.el('div', 'table-context-menu');
        menu.style.left = Math.min(event.clientX, window.innerWidth - 200) + 'px';
        menu.style.top = Math.min(event.clientY, window.innerHeight - 80) + 'px';
        menu.style.zIndex = 1200;
        const item = (label, run) => {
            const el = this.el('div', 'context-menu-item', label);
            el.addEventListener('click', () => { menu.remove(); run(); });
            menu.appendChild(el);
        };
        item('New query', () => { cm.switchToConnection(conn.id); this.hide(); window.app.tabManager.createTab('query', conn.id, { query: '' }); });
        item('Disconnect', () => cm.disconnect(conn.id));
        document.body.appendChild(menu);
        setTimeout(() => document.addEventListener('click', () => menu.remove(), { once: true }), 0);
    }

    el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    // ---- keyboard -----------------------------------------------------------------------------------

    onKey(e) {
        if (e.key === 'Escape' && this.isOpen && !document.querySelector('.app-dialog')) { this.hide(); return; }
        const mod = e.metaKey || e.ctrlKey;
        if (!mod || e.altKey) return;
        if (e.shiftKey && e.key.toLowerCase() === 'd') {       // Cmd/Ctrl+Shift+D: the list of open databases
            e.preventDefault();
            this.toggle();
        } else if (!e.shiftKey && /^[1-9]$/.test(e.key) && this.open[Number(e.key) - 1]) {   // Cmd/Ctrl+1..9: the nth one
            e.preventDefault();
            window.app.connectionManager.switchToConnection(this.open[Number(e.key) - 1].id);
            this.hide();
        }
    }

    onPanelKey(e) {
        if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
        const stops = [...this.panel.querySelectorAll('.switch-main, .switch-add')];
        const at = stops.indexOf(document.activeElement);
        if (at < 0) return;
        e.preventDefault();
        stops[(at + (e.key === 'ArrowDown' ? 1 : stops.length - 1)) % stops.length].focus();
    }
}
