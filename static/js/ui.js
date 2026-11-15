// Small line icons for buttons and menus (16x16, drawn in the text colour). Fixed markup, never built from user text.
const Icons = (() => {
    const svg = (d) => `<svg class="ico" viewBox="0 0 16 16" aria-hidden="true" focusable="false">${d}</svg>`;
    return {
        plus: svg('<path d="M8 3v10M3 8h10"/>'),
        trash: svg('<path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.2h5.8l.6-8.2M7 7v3.5M9 7v3.5"/>'),
        check: svg('<path d="M3.5 8.5l3 3 6-7"/>'),
        undo: svg('<path d="M4 6.5h5.5a3 3 0 010 6H6M4 6.5L6.5 4M4 6.5L6.5 9"/>'),
        close: svg('<path d="M4 4l8 8M12 4l-8 8"/>'),
        upload: svg('<path d="M8 11V3M5 6l3-3 3 3M3 12.5h10"/>'),
        download: svg('<path d="M8 3v8M5 8l3 3 3-3M3 12.5h10"/>'),
        refresh: svg('<path d="M13 8a5 5 0 11-1.6-3.7M13 3v2.5h-2.5"/>'),
        search: svg('<circle cx="7" cy="7" r="4.2"/><path d="M10.3 10.3L13.5 13.5"/>'),
        table: svg('<rect x="2.5" y="3.5" width="11" height="9" rx="1.8"/><path d="M2.5 7h11M6.5 7v5.5"/>'),
        tab: svg('<path d="M3 4.5l3 3.5-3 3.5M8 12h5"/>'),
        bookmark: svg('<path d="M4.5 2.5h7v11l-3.5-2.7-3.5 2.7z"/>'),
        bolt: svg('<path d="M9 2L4 9h3.5l-.5 5 5-7H8.5z"/>'),
        theme: svg('<circle cx="8" cy="8" r="5.2"/><path d="M8 2.8v10.4"/><path d="M8 2.8a5.2 5.2 0 010 10.4" fill="currentColor" stroke="none"/>'),
        map: svg('<circle cx="3.5" cy="8" r="1.8"/><circle cx="12.5" cy="3.8" r="1.8"/><circle cx="12.5" cy="12.2" r="1.8"/><path d="M5.2 8h3l2.4-3.2M8.2 8l2.4 3.2"/>')
    };
})();

// A text cell a spreadsheet would run as a formula (=HYPERLINK(...), +cmd, -x, @SUM) gets a leading quote, which
// spreadsheets read as text. Real numbers, negative ones included, are left alone. Used by every CSV export.
function spreadsheetSafe(value) {
    if (typeof value !== 'string' || !/^[=+\-@\t\r]/.test(value)) return value;
    return /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(value) ? value : "'" + value;
}

// Small UI helpers shared by every script: a styled confirm dialog and non-blocking messages.
// They replace the browser's alert()/confirm(), which look foreign in a desktop app and freeze the page.
window.ui = (() => {
    // Informational messages become toasts. The kind is read from the wording so call sites stay one-liners.
    function notify(message, type) {
        const text = String(message);
        type = type || (/\b(fail|failed|error|invalid|could not|cannot|unable)/i.test(text) ? 'error'
            : /\b(success|saved|copied|inserted|deleted|updated|exported)/i.test(text) ? 'success'
            : 'warning');
        const tabs = window.app && window.app.tabManager;
        if (tabs) tabs.showNotification(text, type);
        else console.warn(text);
    }

    // Resolves true on the confirm button, false on Cancel, Escape, the close button or a click outside.
    function confirmDialog(message, { title = 'Are you sure?', confirmLabel = 'Continue', cancelLabel = 'Cancel', danger = false, safeDefault = false } = {}) {
        return new Promise(resolve => {
            const root = document.createElement('div');
            root.className = 'modal active app-dialog';
            root.setAttribute('role', 'alertdialog');
            root.setAttribute('aria-modal', 'true');
            root.innerHTML = `
                <div class="modal-content app-dialog-box">
                    <div class="modal-header">
                        <h3 class="app-dialog-title"></h3>
                        <span class="modal-close" role="button" aria-label="Cancel" tabindex="0">×</span>
                    </div>
                    <div class="modal-body">
                        <p class="app-dialog-message"></p>
                        <div class="form-actions">
                            <button type="button" class="btn" data-answer="cancel"></button>
                            <button type="button" class="btn ${danger ? 'btn-danger-solid' : 'btn-primary'}" data-answer="ok"></button>
                        </div>
                    </div>
                </div>`;
            // textContent, never innerHTML: messages can contain table names and database error text
            root.querySelector('.app-dialog-title').textContent = title;
            root.querySelector('.app-dialog-message').textContent = message;
            const ok = root.querySelector('[data-answer=ok]');
            const cancel = root.querySelector('[data-answer=cancel]');
            ok.textContent = confirmLabel;
            cancel.textContent = cancelLabel;

            const previous = document.activeElement;
            const done = (answer) => {
                document.removeEventListener('keydown', onKey, true);
                root.remove();
                if (previous && previous.focus) previous.focus();
                resolve(answer);
            };
            const onKey = (e) => {
                if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); }
                else if (e.key === 'Tab') {  // keep focus inside the dialog
                    e.preventDefault();
                    (document.activeElement === ok ? cancel : ok).focus();
                }
            };
            ok.addEventListener('click', () => done(true));
            cancel.addEventListener('click', () => done(false));
            root.querySelector('.modal-close').addEventListener('click', () => done(false));
            root.addEventListener('mousedown', (e) => { if (e.target === root) done(false); });
            document.addEventListener('keydown', onKey, true);
            document.body.appendChild(root);
            // The safe choice has the focus: Enter on a destructive dialog cancels
            ((danger || safeDefault) ? cancel : ok).focus();
        });
    }

    // Asks for one line of text. Resolves with the trimmed text, or null on Cancel, Escape, the close button or a click outside.
    function promptDialog(message, { title = 'Enter a value', value = '', confirmLabel = 'OK', cancelLabel = 'Cancel', maxLength = 100, emptyMessage = 'Enter a value first.' } = {}) {
        return new Promise(resolve => {
            const root = document.createElement('div');
            root.className = 'modal active app-dialog';
            root.setAttribute('role', 'dialog');
            root.setAttribute('aria-modal', 'true');
            root.innerHTML = `
                <div class="modal-content app-dialog-box">
                    <div class="modal-header">
                        <h3 class="app-dialog-title"></h3>
                        <span class="modal-close" role="button" aria-label="Cancel" tabindex="0">×</span>
                    </div>
                    <div class="modal-body">
                        <p class="app-dialog-message"></p>
                        <input type="text" class="form-control app-dialog-input" autocomplete="off" spellcheck="false">
                        <p class="app-dialog-error form-hint" role="alert" style="display: none;"></p>
                        <div class="form-actions">
                            <button type="button" class="btn" data-answer="cancel"></button>
                            <button type="button" class="btn btn-primary" data-answer="ok"></button>
                        </div>
                    </div>
                </div>`;
            // textContent / value, never innerHTML
            root.querySelector('.app-dialog-title').textContent = title;
            root.querySelector('.app-dialog-message').textContent = message;
            const input = root.querySelector('.app-dialog-input');
            const error = root.querySelector('.app-dialog-error');
            input.maxLength = maxLength;
            input.value = value;
            const ok = root.querySelector('[data-answer=ok]');
            const cancel = root.querySelector('[data-answer=cancel]');
            ok.textContent = confirmLabel;
            cancel.textContent = cancelLabel;

            const previous = document.activeElement;
            const done = (answer) => {
                document.removeEventListener('keydown', onKey, true);
                root.remove();
                if (previous && previous.focus) previous.focus();
                resolve(answer);
            };
            const submit = () => {
                const text = input.value.trim();
                if (!text) {
                    error.textContent = emptyMessage;
                    error.style.display = '';
                    input.focus();
                    return;
                }
                done(text);
            };
            const onKey = (e) => {
                if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(null); }
                else if (e.key === 'Enter' && document.activeElement === input) { e.preventDefault(); e.stopPropagation(); submit(); }
                else if (e.key === 'Tab') {   // keep focus inside the dialog
                    const order = [input, cancel, ok];
                    const next = order[(order.indexOf(document.activeElement) + (e.shiftKey ? order.length - 1 : 1)) % order.length];
                    e.preventDefault();
                    next.focus();
                }
            };
            input.addEventListener('input', () => { error.style.display = 'none'; });
            ok.addEventListener('click', submit);
            cancel.addEventListener('click', () => done(null));
            root.querySelector('.modal-close').addEventListener('click', () => done(null));
            root.addEventListener('mousedown', (e) => { if (e.target === root) done(null); });
            document.addEventListener('keydown', onKey, true);
            document.body.appendChild(root);
            input.focus();
            input.select();
        });
    }

    return { notify, confirm: confirmDialog, prompt: promptDialog };
})();
