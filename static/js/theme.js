// Colour theme: "system" follows the operating system, "light" and "dark" are fixed.
// The server applies the saved choice before the first paint (see index() in db.py); this keeps it current.
const Theme = {
    order: ['system', 'light', 'dark'],
    labels: { system: '◐ System', light: '☀ Light', dark: '☾ Dark' },

    get preference() {
        return document.documentElement.dataset.themePref || 'system';
    },

    resolve(preference) {
        if (preference !== 'system') return preference;
        return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    },

    apply(preference) {
        const root = document.documentElement;
        root.dataset.themePref = preference;
        root.dataset.theme = this.resolve(preference);
        const button = document.getElementById('theme-btn');
        if (button) button.textContent = this.labels[preference];
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

    cycle() {
        this.set(this.order[(this.order.indexOf(this.preference) + 1) % this.order.length]);
    },

    init() {
        this.apply(this.preference);
        document.getElementById('theme-btn').addEventListener('click', () => this.cycle());
        // while following the system, switch when the system does
        window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
            if (this.preference === 'system') this.apply('system');
        });
    }
};
