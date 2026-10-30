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

    return { notify, confirm: confirmDialog };
})();
