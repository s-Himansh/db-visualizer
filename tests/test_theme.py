"""The colour theme: remembered on disk, validated, and applied to the page before it paints."""
import json
import re

import pytest

import db


@pytest.fixture(autouse=True)
def fresh_settings():
    db.SETTINGS_FILE.unlink(missing_ok=True)
    yield
    db.SETTINGS_FILE.unlink(missing_ok=True)


def page_theme(client):
    """The theme the served page applies, read from the inline script in its head."""
    found = re.search(r'var p=("[^"]*")', client.get('/').get_data(as_text=True))
    return json.loads(found.group(1)) if found else None


def test_it_follows_the_system_until_told_otherwise(client):
    assert client.get('/api/theme').get_json() == {'success': True, 'theme': 'system'}
    assert page_theme(client) == 'system'


@pytest.mark.parametrize('theme', db.THEMES)
def test_a_choice_is_remembered_and_sent_with_the_page(client, theme):
    assert client.put('/api/theme', json={'theme': theme}).get_json() == {'success': True, 'theme': theme}
    assert client.get('/api/theme').get_json()['theme'] == theme
    assert page_theme(client) == theme


def test_anything_else_is_refused_and_changes_nothing(client):
    client.put('/api/theme', json={'theme': 'sky'})
    for bad in ('purple', '', None, 3, ['dark'], '"><script>alert(1)</script>'):
        r = client.put('/api/theme', json={'theme': bad})
        assert r.status_code == 400 and r.get_json()['success'] is False, bad
    assert client.put('/api/theme', data='not json').status_code == 400
    assert client.get('/api/theme').get_json()['theme'] == 'sky'


def test_a_hand_edited_settings_file_cannot_put_code_in_the_page(client):
    db.SETTINGS_FILE.write_text(json.dumps({'theme': '";alert(1);//'}))
    assert client.get('/api/theme').get_json()['theme'] == 'system'
    html = client.get('/').get_data(as_text=True)
    assert 'alert(1)' not in html and page_theme(client) == 'system'


def test_the_old_light_and_dark_choices_become_sky_and_obsidian(client):
    for old, new in (('light', 'sky'), ('dark', 'obsidian')):
        assert client.put('/api/theme', json={'theme': old}).get_json() == {'success': True, 'theme': new}
        assert page_theme(client) == new
        db.SETTINGS_FILE.write_text(json.dumps({'theme': old}))          # as an earlier version saved it
        assert client.get('/api/theme').get_json()['theme'] == new and page_theme(client) == new


def test_the_page_picks_sky_or_obsidian_when_following_the_system(client):
    html = client.get('/').get_data(as_text=True)
    assert "?'sky':'obsidian'" in html


def test_the_theme_does_not_disturb_the_assistant_settings(client):
    client.put('/api/ai/settings', json={'api_key': 'sk-ant-test-key-123', 'enabled': True})
    client.put('/api/theme', json={'theme': 'obsidian'})
    ai = client.get('/api/ai/settings').get_json()
    assert ai['enabled'] is True and ai['has_key'] is True


def test_the_api_still_needs_the_token(client):
    anonymous = db.app.test_client()
    assert anonymous.get('/api/theme').status_code in (401, 403)
    assert anonymous.put('/api/theme', json={'theme': 'dark'}).status_code in (401, 403)


def test_the_theme_is_set_before_any_stylesheet_loads_so_the_page_never_flashes(client):
    client.put('/api/theme', json={'theme': 'dark'})
    html = client.get('/').get_data(as_text=True)
    assert html.index('themePref') < html.index('rel="stylesheet"')


def test_the_self_check_used_by_the_release_build_passes():
    import subprocess, sys, os
    out = subprocess.run([sys.executable, 'db.py', '--self-check'], capture_output=True, text=True, timeout=60,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         env={**os.environ, 'DBV_DATA_DIR': os.environ.get('TMPDIR', '/tmp') + '/dbv-selfcheck'})
    assert out.returncode == 0 and 'self-check ok' in out.stdout, out.stdout + out.stderr
