// Point the big button at the right build for this computer, and fill in the version and sizes from the latest release.
// Without JavaScript, or if GitHub can't be reached, every link still works: they go to the "latest release" files.
(function () {
  const REPO = 's-Himansh/db-visualizer';
  const BUILDS = {
    'mac-arm': { file: 'DB-Visualizer-macOS-AppleSilicon.zip', label: 'Download for macOS', short: 'macOS (Apple Silicon)' },
    'mac-intel': { file: 'DB-Visualizer-macOS-Intel.zip', label: 'Download for macOS (Intel)', short: 'macOS (Intel)' },
    win: { file: 'DB-Visualizer-Windows.zip', label: 'Download for Windows', short: 'Windows' }
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
        ? 'DB Visualizer is a desktop app. Open this page on your computer to download it.'
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
