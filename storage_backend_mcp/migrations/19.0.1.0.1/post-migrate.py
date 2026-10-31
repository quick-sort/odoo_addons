from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Existing installs already have the guide record, and it is noupdate;
    pin it to administrators so the upgrade does not leave it visible to every
    internal user."""
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    guide = env.ref("storage_backend_mcp.guide_storage", raise_if_not_found=False)
    if not guide:
        return

    guide.allowed_group_ids = [(6, 0, env.ref("base.group_system").ids)]
