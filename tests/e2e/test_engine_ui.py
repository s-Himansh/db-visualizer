"""The browser tests drive the engine they were asked to (E2E_BROWSER). Without this a run meant to test WebKit, the engine the Mac app
uses, could silently fall back to Chromium and report a reassuring pass that proved nothing."""
import pytest

from conftest import ENGINE

pytestmark = pytest.mark.e2e


def test_the_browser_is_the_engine_that_was_asked_for(browser, page):
    assert browser.browser_type.name == ENGINE
    agent = page.evaluate('navigator.userAgent')
    if ENGINE == 'webkit':
        assert 'AppleWebKit' in agent and 'Chrome' not in agent and 'Chromium' not in agent, agent
    else:
        assert 'Chrome' in agent, agent
