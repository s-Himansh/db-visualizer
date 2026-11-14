// Colour themes. "System" follows the operating system (Sky when it is light, Obsidian when it is dark); the rest are
// fixed choices. The server applies the saved choice before the first paint (see index() in db.py); this keeps it
// current, draws the picker, and gives every connection its own colour: the active connection sets --hue, and the
// theme's accent, highlights and tags all follow it.
const Theme = {
    // swatch: [panel, raised, accent] as drawn in the picker. hues/prod: the connection colours for themes built from a
    // palette, kept to that palette's own accent family so the theme still looks like itself; Sky and Obsidian spread
    // the hues around the whole wheel instead.
    themes: {
        sky: { label: 'Sky', note: 'airy light blue', mode: 'light', hue: 205, swatch: ['#e9f2fb', '#ffffff', '#2b8fd6'] },
        obsidian: { label: 'Obsidian', note: 'true black', mode: 'dark', hue: 252, swatch: ['#0b0b0d', '#1a1a1e', '#7c6cf0'] },
        inkteal: { label: 'Ink and teal', note: 'midnight ink, teal accents', mode: 'dark', hue: 178, hues: [178, 188, 166, 200, 172, 210], prod: 8, swatch: ['#1a1a24', '#2a293d', '#17b3a6'] },
        coraldeep: { label: 'Deep sea and coral', note: 'dark teal-navy, coral accent', mode: 'dark', hue: 1, hues: [1, 14, 354, 24, 8, 346], prod: 358, swatch: ['#092d3d', '#144759', '#ff6563'] },
        earthygold: { label: 'Earthy gold', note: 'forest green, warm gold', mode: 'dark', hue: 40, hues: [40, 168, 52, 33, 150, 62], prod: 14, swatch: ['#1b3226', '#305240', '#fbd58a'] },
        slatecitrus: { label: 'Slate and citrus', note: 'cool slate, yellow and orange', mode: 'dark', hue: 49, hues: [49, 29, 180, 40, 18, 196], prod: 7, swatch: ['#2f3540', '#444c5a', '#f3c500'] },
        coralcloud: { label: 'Coral cloud', note: 'light, with a coral accent', mode: 'light', hue: 1, hues: [1, 14, 354, 24, 8, 346], prod: 358, swatch: ['#f1f4f6', '#ffffff', '#ff6563'] }
    },
    legacy: { light: 'sky', dark: 'obsidian' },   // what earlier versions saved

    get order() { return ['system', ...Object.keys(this.themes)]; },

    get preference() {
        const saved = document.documentElement.dataset.themePref || 'system';
        return this.legacy[saved] || saved;
    },

    resolve(preference) {
        if (preference !== 'system') return preference;
        return window.matchMedia('(prefers-color-scheme: light)').matches ? 'sky' : 'obsidian';
    },

    // the theme in force right now (never "system")
    get current() { return this.themes[document.documentElement.dataset.theme] || this.themes.obsidian; },

    label(preference) { return preference === 'system' ? '◐ System' : this.themes[preference].label; },

    apply(preference) {
        const root = document.documentElement;
        root.dataset.themePref = preference;
        root.dataset.theme = this.resolve(preference);
        const button = document.getElementById('theme-btn');
        if (button) {
            button.textContent = this.label(preference);
            button.setAttribute('aria-expanded', String(this.menuOpen));
        }
        this.drawMenu();
        this.syncInk();
        document.dispatchEvent(new CustomEvent('theme-changed'));
    },

    async set(preference) {
        this.apply(preference);
        try {
            await fetch('/api/theme', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme: preference })
            });
        } catch (error) {
            console.error('Could not save the theme:', error);   // it still applies for this session
        }
    },

    // ---- each connection's own colour ----------------------------------------------------------------------

    hash(text) {
        let h = 0;
        for (const ch of String(text)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
        return h;
    },

    // A connection's hue: Production always gets the theme's warm warning colour; the others come from the theme's palette
    // (or, for Sky and Obsidian, are spread around the colour wheel), and stay the same from one run to the next.
    hueOf(conn) {
        const theme = this.current;
        if (conn.environment === 'production') return theme.prod ?? 8;
        const h = this.hash(conn.id || conn.name);
        return theme.hues ? theme.hues[h % theme.hues.length] : Math.round((h * 137.508) % 360);
    },

    // Make the whole window take on the active connection's colour; with none, go back to the theme's own.
    useConnection(conn) {
        const root = document.documentElement;
        if (conn) root.style.setProperty('--hue', String(this.hueOf(conn)));
        else root.style.removeProperty('--hue');
        this.syncInk();
    },

    // ---- text that stays readable on any colour ----------------------------------------------------------------

    // white or near-black, whichever reads better on hsl(h s% l%)
    inkOn(h, s, l) {
        s /= 100; l /= 100;
        const k = n => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
        const f = n => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
        const lin = v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
        const lum = 0.2126 * lin(f(0)) + 0.7152 * lin(f(8)) + 0.0722 * lin(f(4));
        // contrast against white, and against the near-black (#10161d, luminance 0.008); take the better
        return 1.05 / (lum + 0.05) >= (lum + 0.05) / 0.058 ? '#ffffff' : '#10161d';
    },

    // the colour of text on the accent (buttons, selected items): chosen from the accent's brightness, so every hue on
    // every theme is readable, not just the ones the theme was drawn with
    syncInk() {
        const root = document.documentElement, css = getComputedStyle(root);
        const hue = parseFloat(root.style.getPropertyValue('--hue')) || this.current.hue;
        const s = parseFloat(css.getPropertyValue('--acc-s')) || 80, l = parseFloat(css.getPropertyValue('--acc-l')) || 62;
        root.style.setProperty('--accent-ink', this.inkOn(hue, s, l));
    },

    // ---- the picker ------------------------------------------------------------------------------------------

    menuOpen: false,

    drawMenu() {
        const menu = document.getElementById('theme-menu');
        if (!menu) return;
        const rows = this.order.map(key => {
            const t = this.themes[key];
            const swatch = key === 'system'
                ? '<span class="theme-swatch theme-swatch-system"><i></i><i></i></span>'
                : `<span class="theme-swatch">${t.swatch.map(c => `<i style="background:${c}"></i>`).join('')}</span>`;
            const label = key === 'system' ? 'Match my system' : t.label;
            const note = key === 'system' ? 'Sky by day, Obsidian at night' : t.note;
            const on = this.preference === key;
            return `<button type="button" role="menuitemradio" aria-checked="${on}" class="theme-row${on ? ' on' : ''}" data-theme-key="${key}">
                ${swatch}<span class="theme-text"><span class="theme-name">${label}</span><span class="theme-note">${note}</span></span><span class="theme-check">${on ? '✓' : ''}</span></button>`;
        });
        menu.innerHTML = rows.join('');
    },

    openMenu() {
        const menu = document.getElementById('theme-menu');
        this.menuOpen = true;
        menu.hidden = false;
        document.getElementById('theme-btn').setAttribute('aria-expanded', 'true');
        (menu.querySelector('.theme-row.on') || menu.querySelector('.theme-row')).focus();
    },

    closeMenu(returnFocus = true) {
        const menu = document.getElementById('theme-menu');
        if (!this.menuOpen) return;
        this.menuOpen = false;
        menu.hidden = true;
        const button = document.getElementById('theme-btn');
        button.setAttribute('aria-expanded', 'false');
        if (returnFocus) button.focus();
    },

    init() {
        this.apply(this.preference);
        const button = document.getElementById('theme-btn');
        const menu = document.getElementById('theme-menu');
        button.addEventListener('click', () => (this.menuOpen ? this.closeMenu() : this.openMenu()));
        menu.addEventListener('click', (e) => {
            const row = e.target.closest('.theme-row');
            if (!row) return;
            this.set(row.dataset.themeKey);
            this.closeMenu();
        });
        menu.addEventListener('keydown', (e) => {
            const rows = [...menu.querySelectorAll('.theme-row')];
            const at = rows.indexOf(document.activeElement);
            if (e.key === 'ArrowDown') { e.preventDefault(); rows[(at + 1) % rows.length].focus(); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); rows[(at - 1 + rows.length) % rows.length].focus(); }
            else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.closeMenu(); }
            else if (e.key === 'Tab') this.closeMenu(false);
        });
        document.addEventListener('mousedown', (e) => {
            if (this.menuOpen && !menu.contains(e.target) && e.target !== button) this.closeMenu(false);
        });
        // while following the system, switch when the system does
        window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
            if (this.preference === 'system') this.apply('system');
        });
    }
};
