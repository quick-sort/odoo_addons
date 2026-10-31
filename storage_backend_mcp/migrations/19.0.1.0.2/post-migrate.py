from odoo import SUPERUSER_ID, api

DEPRECATION_NOTE = (
    "Deprecated for new integrations: prefer the `attachment_*` tools from\n"
    "llm_mcp_server (ir.attachment ids, no backend/path, no list tools).\n"
    "The `storage_*` tools below remain for existing callers.\n\n"
)


def migrate(cr, version):
    """The guide is noupdate; annotate existing installs so agents discover the
    replacement tools instead of starting new integrations on storage paths."""
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    guide = env.ref("storage_backend_mcp.guide_storage", raise_if_not_found=False)
    if guide and "Deprecated for new integrations" not in (guide.body or ""):
        guide.body = DEPRECATION_NOTE + (guide.body or "")
