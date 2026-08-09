import logging

from . import controllers
from . import models

_logger = logging.getLogger(__name__)


def _ensure_company_roots(env):
    """Create a default backend + root folder for every existing company."""
    Entry = env["one.storage.entry"]
    for company in env["res.company"].search([]):
        Entry._get_or_create_root(company)


def post_init_hook(env):
    _ensure_company_roots(env)
