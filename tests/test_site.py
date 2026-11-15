"""The download page (site/): everything it points at exists, and its links match what the release workflow builds."""
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / 'site'


class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ('src', 'href', 'srcset') and value and not value.startswith(('http', '#', 'data:', 'mailto:')):
                self.refs.append(value.split()[0])


def test_every_file_the_page_uses_is_there():
    refs = Refs()
    refs.feed((SITE / 'index.html').read_text(encoding='utf-8'))
    for css in ('fonts.css', 'style.css'):
        refs.refs += re.findall(r"url\('([^']+)'\)", (SITE / css).read_text(encoding='utf-8'))
    assert len(refs.refs) > 15
    assert [r for r in refs.refs if not (SITE / r).exists()] == []


def test_download_links_name_the_files_the_release_workflow_builds():
    built = set(re.findall(r'file: (DB-Visualizer-[\w-]+)', (ROOT / '.github/workflows/release.yml').read_text()))
    linked = set(re.findall(r'releases/latest/download/(DB-Visualizer-[\w-]+)\.zip', (SITE / 'index.html').read_text()))
    in_script = set(re.findall(r"file: '(DB-Visualizer-[\w-]+)\.zip'", (SITE / 'app.js').read_text()))
    assert built == linked == in_script and len(built) == 3, (built, linked, in_script)


def test_the_page_loads_nothing_from_the_internet():
    html = (SITE / 'index.html').read_text() + (SITE / 'style.css').read_text() + (SITE / 'fonts.css').read_text()
    loaded = re.findall(r'(?:src|srcset)="(https?://[^"]+)"|url\((https?://[^)]+)\)|<link[^>]+rel="stylesheet"[^>]+href="(https?://[^"]+)"', html)
    assert loaded == []        # links to GitHub are for clicking; nothing is fetched by the page itself except the release lookup in app.js
