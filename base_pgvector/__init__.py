from . import fields
from .init_hook import pre_init_hook

# Export the field type for easier imports:
#   from odoo.addons.base_pgvector import PgVector
from .fields import PgVector
