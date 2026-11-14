"""The typefaces ship inside the app: served locally with the right type, licensed, and never fetched from elsewhere."""
import re
from pathlib import Path

import pytest

import db

FONTS = Path(db.__file__).parent / 'static' / 'fonts'
FAMILIES = ['instrument-sans', 'bricolage-grotesque', 'geist-mono']


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('part', ['latin', 'latin-ext'])
def test_every_font_file_is_served_as_a_font(client, family, part):
    r = client.get(f'/static/fonts/{family}-{part}.woff2')
    assert r.status_code == 200 and r.mimetype == 'font/woff2'
    assert r.data[:4] == b'wOF2'                      # a real WOFF2 file, not an error page


@pytest.mark.parametrize('family', FAMILIES)
def test_each_font_carries_its_licence(family):
    text = (FONTS / f'OFL-{family}.txt').read_text(encoding='utf-8')
    assert 'SIL Open Font License' in text


def test_the_stylesheet_names_only_files_that_exist():
    css = (Path(db.__file__).parent / 'static' / 'css' / 'fonts.css').read_text()
    names = re.findall(r"url\('/static/fonts/([^']+)'\)", css)
    assert len(names) == 6 and all((FONTS / n).is_file() for n in names)


def test_no_stylesheet_or_page_reaches_out_to_the_internet_for_fonts():
    static = Path(db.__file__).parent / 'static'
    for path in [*static.glob('css/*.css'), static / 'index.html']:
        text = path.read_text(encoding='utf-8')
        assert not re.search(r'url\(\s*[\'"]?https?:', text), path.name
        assert 'fonts.googleapis' not in text and 'fonts.gstatic' not in text, path.name


def test_the_page_loads_the_font_stylesheet(client):
    assert '/static/css/fonts.css' in client.get('/').get_data(as_text=True)
