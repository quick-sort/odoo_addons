"""PostgreSQL instance fields and read-only capability probing."""

from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.llm.models.llm_service_dispatch import archive_dangling_service


class LLMStore(models.Model):
    _inherit = "llm.store"

    service = fields.Selection(
        selection_add=[("postgresql", "PostgreSQL")],
        ondelete={"postgresql": archive_dangling_service},
    )
    pg_maintenance_database = fields.Char(
        string="Maintenance Database",
        default="postgres",
        help="Database used for server probes and CREATE/DROP DATABASE operations.",
    )
    pg_server_version = fields.Char(readonly=True, copy=False)
    pg_probe_state = fields.Selection(
        [("unknown", "Not Probed"), ("ready", "Reachable"), ("error", "Error")],
        default="unknown",
        readonly=True,
        copy=False,
    )
    pg_can_create_database = fields.Boolean(readonly=True, copy=False)
    pg_can_create_role = fields.Boolean(readonly=True, copy=False)
    pg_last_probe_at = fields.Datetime(readonly=True, copy=False)
    pg_last_probe_error = fields.Text(readonly=True, copy=False)
    pg_extension_status_ids = fields.One2many(
        "llm.pg.extension.status", "store_id", string="PostgreSQL Extensions"
    )

    def action_pg_probe_server(self):
        errors = []
        for store in self:
            if store.service != "postgresql":
                raise UserError(_("Server probing is available only for PostgreSQL stores."))
            result = store._dispatch("probe_server")
            if result.get("error"):
                errors.append(f"{store.name}: {result['error']}")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("PostgreSQL Probe"),
                "message": "\n".join(errors)
                if errors
                else _("Server capabilities and extension availability refreshed."),
                "type": "danger" if errors else "success",
                "sticky": bool(errors),
            },
        }
