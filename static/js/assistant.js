// The optional SQL assistant: describe what you want, get a statement written into the editor.
// It never runs anything, and sends only names (see ai_assistant.py); the settings dialog says so before it is turned on.
class AIAssistant {
    constructor() {
        this.enabled = false;
        this.modal = document.getElementById('ai-settings-modal');
        document.getElementById('ai-save').addEventListener('click', () => this.save(true));
        document.getElementById('ai-turn-off').addEventListener('click', () => this.save(false));
        document.getElementById('ai-remove-key').addEventListener('click', () => this.removeKey());
        document.getElementById('ai-settings-close').addEventListener('click', () => this.closeSettings());
        document.getElementById('ai-cancel').addEventListener('click', () => this.closeSettings());
        this.refresh();
    }

    async refresh() {
        try {
            this.enabled = (await (await fetch('/api/ai/settings')).json()).enabled;
        } catch (e) { this.enabled = false; }
    }

    // ---- settings dialog -------------------------------------------------------------------------------

    async openSettings() {
        const s = await (await fetch('/api/ai/settings')).json();
        this.enabled = s.enabled;
        document.getElementById('ai-state').textContent = s.enabled ? 'The assistant is on.' : 'The assistant is off.';
        document.getElementById('ai-key').value = '';
        document.getElementById('ai-key').placeholder = s.has_key ? 'A key is saved. Type a new one to replace it.' : 'sk-ant-...';
        document.getElementById('ai-env-note').style.display = (s.env_key && !s.has_key) ? '' : 'none';
        document.getElementById('ai-consent').checked = s.enabled;
        document.getElementById('ai-error').textContent = '';
        document.getElementById('ai-save').textContent = s.enabled ? 'Save changes' : 'Turn on';
        document.getElementById('ai-turn-off').style.display = s.enabled ? '' : 'none';
        document.getElementById('ai-remove-key').style.display = s.has_key ? '' : 'none';
        this.has_key = s.has_key; this.env_key = s.env_key;
        this.modal.classList.add('active');
        document.getElementById('ai-key').focus();
    }

    closeSettings() {
        this.modal.classList.remove('active');
    }

    async put(body) {
        const response = await fetch('/api/ai/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error);
        this.enabled = result.enabled;
        return result;
    }

    async save(enable) {
        const error = document.getElementById('ai-error');
        error.textContent = '';
        const key = document.getElementById('ai-key').value.trim();
        try {
            if (enable && !document.getElementById('ai-consent').checked) {
                throw new Error('Tick the box to confirm you are happy with what is sent.');
            }
            if (enable && !key && !this.has_key && !this.env_key) throw new Error('Enter an Anthropic API key.');
            await this.put({ enabled: enable, ...(key ? { api_key: key } : {}) });
            this.closeSettings();
            ui.notify(enable ? 'The assistant is on. Open a query tab and choose Ask.' : 'The assistant is off.', 'info');
        } catch (err) {
            error.textContent = err.message;
        }
    }

    async removeKey() {
        try {
            await this.put({ remove_key: true, enabled: false });
            this.closeSettings();
            ui.notify('The saved API key was removed and the assistant is off.', 'info');
        } catch (err) {
            document.getElementById('ai-error').textContent = err.message;
        }
    }

    // ---- the Ask panel in a query tab -------------------------------------------------------------------

    panel(tab) { return document.getElementById(`ai-panel-${tab.id}`); }

    toggle(tab) {
        if (!this.enabled) { this.openSettings(); return; }
        const panel = this.panel(tab);
        const show = panel.style.display === 'none';
        panel.style.display = show ? '' : 'none';
        if (show) document.getElementById(`ai-input-${tab.id}`).focus();
        else tab.editor && tab.editor.focus();
    }

    bind(tab) {
        const panel = this.panel(tab);
        if (!panel || panel.dataset.bound) return;
        panel.dataset.bound = '1';
        const input = document.getElementById(`ai-input-${tab.id}`);
        panel.addEventListener('click', (e) => {
            const action = e.target.closest('button')?.dataset.action;
            if (action === 'ai-generate') this.generate(tab);
            else if (action === 'ai-preview') this.preview(tab);
            else if (action === 'ai-close') this.toggle(tab);
            else if (action === 'ai-settings') this.openSettings();
        });
        input.addEventListener('keydown', (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); this.generate(tab); }
            if (e.key === 'Escape') { e.stopPropagation(); this.toggle(tab); }
        });
    }

    request(tab, extra = {}) {
        const conn = window.app.connectionManager.getActiveConnection();
        return fetch('/api/ai/sql', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ connection_id: conn.id, database: tab.state.database, request: document.getElementById(`ai-input-${tab.id}`).value, ...extra })
        }).then(async r => ({ ok: r.ok, status: r.status, body: await r.json() }));
    }

    show(tab, node) {
        document.getElementById(`ai-result-${tab.id}`).replaceChildren(node);
    }

    message(text, cls) {
        const d = document.createElement('div');
        d.className = cls;
        d.textContent = text;
        return d;
    }

    // Exactly the text that would go to the API, without sending it
    async preview(tab) {
        if (!document.getElementById(`ai-input-${tab.id}`).value.trim()) { this.show(tab, this.message('Describe what you want first.', 'ai-error')); return; }
        const { ok, body } = await this.request(tab, { preview: true });
        if (!ok) { this.show(tab, this.message(body.error, 'ai-error')); return; }
        const wrap = document.createElement('div');
        wrap.className = 'ai-preview';
        const head = this.message('This is everything that would be sent. Nothing has been sent yet.', 'ai-note');
        const pre = document.createElement('pre');
        pre.textContent = body.preview.system + '\n\n' + body.preview.user;
        wrap.append(head, pre);
        this.show(tab, wrap);
    }

    async generate(tab) {
        if (tab.asking) return;
        if (!document.getElementById(`ai-input-${tab.id}`).value.trim()) { this.show(tab, this.message('Describe what you want first.', 'ai-error')); return; }
        tab.asking = true;
        const button = this.panel(tab).querySelector('[data-action=ai-generate]');
        button.disabled = true;
        button.textContent = 'Writing…';
        this.show(tab, this.message('Asking Claude. This usually takes a few seconds.', 'ai-note'));
        try {
            const { ok, body } = await this.request(tab);
            if (!ok) {
                if (body.needs_setup) { this.enabled = false; this.openSettings(); }
                this.show(tab, this.message(body.error, 'ai-error'));
                return;
            }
            this.render(tab, body);
        } catch (err) {
            this.show(tab, this.message('Could not reach the app. Try again.', 'ai-error'));
        } finally {
            tab.asking = false;
            button.disabled = false;
            button.textContent = 'Write SQL';
        }
    }

    render(tab, r) {
        const card = document.createElement('div');
        card.className = 'ai-card';
        if (r.explanation) card.append(this.message(r.explanation, 'ai-explanation'));
        if (r.sql) {
            this.insert(tab, r.sql);
            const badge = document.createElement('span');
            const danger = r.destructive;
            badge.className = 'ai-badge ' + (danger ? 'is-danger' : r.read_only ? 'is-safe' : 'is-write');
            badge.textContent = danger ? `Removes or changes many rows: ${danger}` : r.read_only ? 'Reads data only' : 'Changes data';
            const hint = this.message('Added to the editor. Read it, then press Run. Nothing has run yet.' +
                (r.truncated ? ' The answer was cut short, so check the end of the statement.' : ''), 'ai-note');
            card.append(badge, hint);
        }
        const u = r.usage;
        if (u) card.append(this.message(`${u.input_tokens.toLocaleString()} tokens in, ${u.output_tokens.toLocaleString()} out`, 'ai-usage'));
        this.show(tab, card);
    }

    // Replace a selection, fill an empty editor, or add below what is already there; the new text stays selected
    insert(tab, sql) {
        const ed = tab.editor;
        if (!ed) return;
        if (ed.somethingSelected()) {
            ed.replaceSelection(sql, 'around');
        } else if (!ed.getValue().trim() || ed.getValue() === tab.templateText) {   // empty, or still the starter text
            ed.setValue(sql);
            ed.setSelection({ line: 0, ch: 0 }, { line: ed.lastLine(), ch: ed.getLine(ed.lastLine()).length });
        } else {
            const from = { line: ed.lastLine(), ch: ed.getLine(ed.lastLine()).length };
            ed.replaceRange('\n\n' + sql, from);
            ed.setSelection({ line: ed.lastLine() - sql.split('\n').length + 1, ch: 0 }, { line: ed.lastLine(), ch: ed.getLine(ed.lastLine()).length });
        }
        ed.focus();
    }
}
