from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..file_service import COMMITTED_ROW_TTL_DAYS


class LLMMCPFileUpload(models.Model):
    _name = "llm.mcp.file.upload"
    _description = "MCP file upload staging"
    _order = "id desc"

    name = fields.Char(required=True)
    attachment_id = fields.Many2one(
        "ir.attachment",
        string="Attachment",
        index=True,
        ondelete="set null",
    )
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("uploaded", "Uploaded"),
            ("committed", "Committed"),
            ("expired", "Expired"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    sha256 = fields.Char()
    size_bytes = fields.Integer()
    expires_at = fields.Datetime(required=True, index=True)
    committed_model = fields.Char()
    committed_res_id = fields.Integer()

    def _check_owner(self):
        self.ensure_one()
        if not self.env.su and self.create_uid.id != self.env.uid:
            raise UserError(self.env._("You can only access your own file uploads."))
        return True

    def _claim_upload(self):
        """Atomically move one staging row from pending to uploaded.

        Returns True only for the request that wins the race; concurrent or
        replayed PUTs get False.
        """
        self.ensure_one()
        self.env.cr.execute(
            "UPDATE llm_mcp_file_upload SET state = 'uploaded' "
            "WHERE id = %s AND state = 'pending' RETURNING id",
            [self.id],
        )
        claimed = bool(self.env.cr.fetchone())
        if claimed:
            self.invalidate_recordset(["state"])
        return claimed

    @api.model
    def _cron_gc(self):
        now = fields.Datetime.now()
        stale = self.search([
            ("expires_at", "<=", now),
            ("state", "in", ("pending", "uploaded")),
        ])
        for upload in stale:
            attachment = upload.attachment_id
            upload.write({"state": "expired"})
            # Only remove the module's own unbound upload target; a file that
            # was manually bound to a record must survive the staging cleanup.
            if attachment and not attachment.res_model and not attachment.res_field:
                attachment.sudo().unlink()
        cutoff = now - timedelta(days=COMMITTED_ROW_TTL_DAYS)
        self.search([
            ("create_date", "<", cutoff),
            ("state", "=", "committed"),
        ]).unlink()
