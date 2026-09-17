"""Automated BioMedTracker login.

The three-step handshake mirrors a browser visiting the login page: GET the
login form (which redirects to Auth0 and returns a ``state`` token), POST the
username, POST the password. A successful password step makes Auth0 redirect
back to ``www.biomedtracker.com`` with session cookies set on that domain.
"""

import re

import requests

from odoo.addons.component.core import Component

_AUTH_BASE = "https://auth.norstella.com"
_BASE_URL = "https://www.biomedtracker.com"
_COOKIE_DOMAIN = "www.biomedtracker.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class InfohubLoginBiomedtracker(Component):
    _name = "infohub.login.biomedtracker"
    _collection = "infohub.channel"
    _usage = "infohub.login.biomedtracker"

    def login(self):
        channel = self.collection

        http = requests.Session()
        http.headers.update(
            {
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        resp = http.get(f"{_BASE_URL}/auth/login.cfm", timeout=30)
        resp.raise_for_status()
        state = self._state(resp.url)

        resp = http.post(
            f"{_AUTH_BASE}/u/login/identifier?state={state}",
            data={
                "state": state,
                "username": channel.biomedtracker_username,
                "js-available": "true",
                "webauthn-available": "false",
                "is-brave": "false",
                "webauthn-platform-available": "false",
            },
            timeout=30,
        )
        resp.raise_for_status()

        resp = http.post(
            f"{_AUTH_BASE}/u/login/password?state={state}",
            data={
                "state": state,
                "username": channel.biomedtracker_username,
                "password": channel.biomedtracker_password,
            },
            timeout=30,
        )
        resp.raise_for_status()

        channel.biomedtracker_session_cookie = self._domain_cookies(http)

    @staticmethod
    def _state(url):
        m = re.search(r"[?&]state=([^&]+)", url)
        if not m:
            raise ValueError(f"state parameter not found in URL: {url}")
        return m.group(1)

    @staticmethod
    def _domain_cookies(http):
        domain_cookies = http.cookies.get_dict(domain=_COOKIE_DOMAIN)
        if not domain_cookies:
            domain_cookies = http.cookies.get_dict(domain=f".{_COOKIE_DOMAIN}")
        return "; ".join(f"{k}={v}" for k, v in domain_cookies.items())
