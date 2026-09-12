import logging
import shutil
from pathlib import Path

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Load packaged demo files into the demo filesystem backend."""
    backend = env.ref('posters.storage_demo_backend', raise_if_not_found=False)
    if not backend:
        return

    source_directory = Path(__file__).parent / 'demo' / 'files'
    backend = backend.sudo().with_context(storage_backend_force_relative_path=True)
    for source_path in source_directory.iterdir():
        if not source_path.is_file():
            continue
        with (
            source_path.open('rb') as source,
            backend.open(source_path.name, 'wb') as target,
        ):
            shutil.copyfileobj(source, target)
        _logger.info(
            'Loaded poster demo file %s into storage backend',
            source_path.name,
        )
