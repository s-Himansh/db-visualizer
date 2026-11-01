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


@pytest.mark.parametrize('theme', ['light', 'dark', 'system'])
def test_a_choice_is_remembered_and_sent_with_the_page(client, theme):
    assert client.put('/api/theme', json={'theme': theme}).get_json() == {'success': True, 'theme': theme}
    assert client.get('/api/theme').get_json()['theme'] == theme
    assert page_theme(client) == theme


def test_anything_else_is_refused_and_changes_nothing(client):
    client.put('/api/theme', json={'theme': 'light'})
    for bad in ('purple', '', None, 3, ['dark'], '"><script>alert(1)</script>'):
        r = client.put('/api/theme', json={'theme': bad})
        assert r.status_code == 400 and r.get_json()['success'] is False, bad
    assert client.put('/api/theme', data='not json').status_code == 400
    assert client.get('/api/theme').get_json()['theme'] == 'light'


def test_a_hand_edited_settings_file_cannot_put_code_in_the_page(client):
    db.SETTINGS_FILE.write_text(json.dumps({'theme': '";alert(1);//'}))
    assert client.get('/api/theme').get_json()['theme'] == 'system'
    html = client.get('/').get_data(as_text=True)
    assert 'alert(1)' not in html and page_theme(client) == 'system'


def test_the_theme_does_not_disturb_the_assistant_settings(client):
    client.put('/api/ai/settings', json={'api_key': 'sk-ant-test-key-123', 'enabled': True})
    client.put('/api/theme', json={'theme': 'dark'})
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
