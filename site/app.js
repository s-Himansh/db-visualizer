// Point the big button at the right build for this computer, and fill in the version and sizes from the latest release.
// Without JavaScript, or if GitHub can't be reached, every link still works: they go to the "latest release" files.
(function () {
  const REPO = 's-Himansh/db-visualizer';
  const BUILDS = {
    'mac-arm': { file: 'Cairn-macOS-AppleSilicon.dmg', label: 'Download for macOS', short: 'macOS (Apple Silicon)' },
    'mac-intel': { file: 'Cairn-macOS-Intel.dmg', label: 'Download for macOS (Intel)', short: 'macOS (Intel)' },
    win: { file: 'Cairn-Windows.zip', label: 'Download for Windows', short: 'Windows' }
  };
  const $ = (sel) => document.querySelector(sel);
  const button = $('#get-btn'), label = $('#get-label'), note = $('#get-note'), other = $('#other');

  async function whichBuild() {
    const ua = navigator.userAgent;
    if (/iPhone|iPad|iPod|Android/i.test(ua)) return 'phone';
    if (/Windows/i.test(ua)) return 'win';
    if (/Mac/i.test(ua)) {
      try {                                                    // Chrome and Edge can say which chip; Safari can't, so assume a recent Mac
        const hint = await navigator.userAgentData.getHighEntropyValues(['architecture']);
        if (hint.architecture === 'x86') return 'mac-intel';
      } catch (e) { /* not available */ }
      return 'mac-arm';
    }
    return 'other';
  }

  function show(key) {
    if (BUILDS[key]) {
      button.dataset.dl = key;
      button.href = `https://github.com/${REPO}/releases/latest/download/${BUILDS[key].file}`;
      label.textContent = BUILDS[key].label;
      // the other builds, as small links under the button
      other.innerHTML = Object.keys(BUILDS).filter((k) => k !== key)
        .map((k) => `<a href="#download">${BUILDS[k].short}</a>`).join('') +
        '<a href="#download">All downloads</a>';
    } else {
      button.href = '#download';
      button.removeAttribute('data-dl');
      label.textContent = 'See the downloads';
      note.textContent = key === 'phone'
        ? 'Cairn is a desktop app. Open this page on your computer to download it.'
        : 'There is no Linux build yet. You can run it from source, or download for a Mac or Windows.';
    }
  }

  async function latest() {
    try {
      const res = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, { headers: { Accept: 'application/vnd.github+json' } });
      if (!res.ok) return;
      const release = await res.json();
      $('#version').textContent = release.tag_name;
      for (const a of release.assets || []) {
        const key = Object.keys(BUILDS).find((k) => BUILDS[k].file === a.name);
        if (!key) continue;
        document.querySelectorAll(`[data-dl="${key}"]`).forEach((el) => { el.href = a.browser_download_url; });
        document.querySelectorAll(`[data-size="${key}"]`).forEach((el) => { el.textContent = `(${Math.round(a.size / 1048576)} MB)`; });
      }
    } catch (e) { /* offline or rate limited: the fallback links already work */ }
  }

  whichBuild().then(show).then(latest);
})();

// The live demo: a toy shop. Arrows jump to the row they point at, totals can be edited, and edits wait in a bar.
(function () {
  const customers = [[1, 'Ines Rao', 'Portugal'], [2, 'Tomás Weber', 'Germany'], [3, 'Aiko Mori', 'Japan'], [4, 'Lena Okafor', 'Nigeria'], [5, 'Sam Duarte', 'Brazil']];
  const orders = [[101, 3, 48.0, 'paid'], [102, 1, 120.5, 'pending'], [103, 5, 19.99, 'paid'], [104, 3, 75.0, 'paid'], [105, 2, 310.0, 'pending']];
  const orderBody = document.getElementById('demo-orders'), customerBody = document.getElementById('demo-customers');
  const live = document.getElementById('demo-live'), bar = document.getElementById('demo-bar'), count = document.getElementById('demo-count');
  if (!orderBody || !customerBody) return;
  const fmt = (n) => Number(n).toFixed(2);
  const original = new Map();                      // order id -> the total it started with
  const changed = new Set();

  orderBody.innerHTML = orders.map(([id, cust, total, status]) => {
    const who = customers.find((c) => c[0] === cust)[1];
    original.set(id, fmt(total));
    return `<tr data-order="${id}"><td class="idc">${id}</td>
      <td><button type="button" class="link" data-customer="${cust}" aria-label="Go to customer ${cust}, ${who}">${cust} <span aria-hidden="true">↗</span></button></td>
      <td class="num edit" contenteditable="plaintext-only" tabindex="0" role="textbox" aria-label="Total for order ${id}" data-total="${id}">${fmt(total)}</td>
      <td><span class="pill ${status}">${status}</span></td></tr>`;
  }).join('');
  customerBody.innerHTML = customers.map(([id, name, country]) => `<tr data-customer-row="${id}"><td class="idc">${id}</td><td>${name}</td><td>${country}</td></tr>`).join('');

  const clearTarget = () => customerBody.querySelectorAll('.target').forEach((r) => r.classList.remove('target'));
  orderBody.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-customer]');
    if (!btn) return;
    const id = Number(btn.dataset.customer), [, name, country] = customers.find((c) => c[0] === id);
    clearTarget();
    customerBody.querySelector(`[data-customer-row="${id}"]`).classList.add('target');
    const back = orders.filter((o) => o[1] === id).length;
    live.textContent = `Customer ${id}: ${name}, ${country}. ${back} ${back === 1 ? 'order points' : 'orders point'} at this customer.`;
  });

  function refresh() {
    bar.hidden = changed.size === 0;
    count.textContent = `${changed.size} unsaved ${changed.size === 1 ? 'change' : 'changes'}`;
  }
  orderBody.addEventListener('focusout', (e) => {
    const cell = e.target.closest('[data-total]');
    if (!cell) return;
    const id = Number(cell.dataset.total), typed = cell.textContent.trim();
    if (typed === '' || isNaN(Number(typed))) { cell.textContent = original.get(id); changed.delete(id); cell.classList.remove('changed'); refresh(); return; }
    cell.textContent = fmt(typed);
    const edited = cell.textContent !== original.get(id);
    cell.classList.toggle('changed', edited);
    edited ? changed.add(id) : changed.delete(id);
    refresh();
  });
  orderBody.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.matches('[data-total]')) { e.preventDefault(); e.target.blur(); } });

  document.getElementById('demo-undo').addEventListener('click', () => {
    changed.forEach((id) => { const cell = orderBody.querySelector(`[data-total="${id}"]`); cell.textContent = original.get(id); cell.classList.remove('changed'); });
    changed.clear(); refresh(); live.textContent = 'Undone. Nothing was saved.';
  });
  document.getElementById('demo-save').addEventListener('click', () => {
    const n = changed.size;
    changed.forEach((id) => { const cell = orderBody.querySelector(`[data-total="${id}"]`); original.set(id, cell.textContent); cell.classList.remove('changed'); });
    changed.clear(); refresh();
    live.textContent = `Saved ${n} ${n === 1 ? 'change' : 'changes'} together. In Cairn, they're saved as one: all or nothing.`;
  });
})();
