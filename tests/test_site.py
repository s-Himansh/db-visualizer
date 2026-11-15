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
    built = {f'{name}.{ext}' for name, ext in re.findall(r'file: (Cairn-[\w-]+), ext: (\w+)', (ROOT / '.github/workflows/release.yml').read_text())}
    linked = set(re.findall(r'releases/latest/download/(Cairn-[\w-]+\.(?:zip|dmg))', (SITE / 'index.html').read_text()))
    in_script = set(re.findall(r"file: '(Cairn-[\w.-]+)'", (SITE / 'app.js').read_text()))
    assert built == linked == in_script and len(built) == 3, (built, linked, in_script)


def test_the_page_loads_nothing_from_the_internet():
    html = (SITE / 'index.html').read_text() + (SITE / 'style.css').read_text() + (SITE / 'fonts.css').read_text()
    loaded = re.findall(r'(?:src|srcset)="(https?://[^"]+)"|url\((https?://[^)]+)\)|<link[^>]+rel="stylesheet"[^>]+href="(https?://[^"]+)"', html)
    assert loaded == []        # links to GitHub are for clicking; nothing is fetched by the page itself except the release lookup in app.js


def test_every_link_within_the_page_lands_on_something():
    html = (SITE / 'index.html').read_text(encoding='utf-8')
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    jumps = set(re.findall(r'href="#([^"]+)"', html))
    assert {'first-launch', 'source', 'download'} <= jumps
    assert jumps - ids == set(), jumps - ids


def test_the_python_route_uses_the_commands_the_readme_documents():
    html = (SITE / 'index.html').read_text(encoding='utf-8')
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert './run.sh' in html and './run.sh' in readme
    assert 'python -m venv .venv' in html and r'.venv\Scripts\python db.py' in html
    assert 'requirements.txt' in html and (ROOT / 'requirements.txt').exists() and (ROOT / 'run.sh').exists()


def test_the_mac_steps_cover_the_newer_macos_where_right_click_open_no_longer_works():
    html = (SITE / 'index.html').read_text(encoding='utf-8')
    assert 'Open Anyway' in html and 'Privacy &amp; Security' in html and 'Move to Trash' in html
    assert 'xattr -dr com.apple.quarantine' in html
    notes = (ROOT / '.github/workflows/release.yml').read_text()
    assert 'Open Anyway' in notes


def test_the_mac_disk_image_layout_has_the_app_an_applications_shortcut_and_its_artwork():
    settings = {'defines': {'app': 'dist/Cairn.app'}}
    exec((ROOT / 'packaging' / 'dmg_settings.py').read_text(), settings)           # the way dmgbuild reads it
    assert settings['files'] == ['dist/Cairn.app'] and settings['symlinks'] == {'Applications': '/Applications'}
    assert set(settings['icon_locations']) == {'Cairn.app', 'Applications'}
    assert settings['icon_locations']['Cairn.app'][0] < settings['icon_locations']['Applications'][0]      # the app on the left, the drop target on the right
    assert (ROOT / settings['background']).stat().st_size > 1000                    # run from the repo root, as the workflow does
    assert 'dmgbuild -s packaging/dmg_settings.py' in (ROOT / '.github/workflows/release.yml').read_text()
