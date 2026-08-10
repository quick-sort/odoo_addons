import logging

from . import controllers
from . import models
from . import wizards

_logger = logging.getLogger(__name__)


def _ensure_root(env):
    """Create the default backend + global root folder if missing."""
    env["one.storage.entry"]._get_or_create_root()


def post_init_hook(env):
    _ensure_root(env)
