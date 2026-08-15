# Copyright 2026 ACSONE SA/NV (<http://acsone.eu>)
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import base64
import os

from odoo import api, fields, models
from odoo.exceptions import UserError


class StorageBackendFileListLine(models.TransientModel):
    _name = "storage.backend.file.list.line"
    _description = "Storage Backend File List Line"
    _order = "name"

    wizard_id = fields.Many2one(
        comodel_name="storage.backend.file.list.wizard",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(required=True)
    relative_path = fields.Char()
    is_directory = fields.Boolean(compute="_compute_is_directory")

    def _compute_is_directory(self):
        for line in self:
            line.is_directory = bool(line.name and line.name.endswith("/"))

    def action_download(self):
        self.ensure_one()
        backend = self.wizard_id.backend_id
        with backend.open(self.relative_path or self.name, "rb") as stream:
            data = stream.read()
        # Serve the bytes through an attachment: the download URL then works
        # through the standard /web/content controller with proper access
        # rules (creator and storage.backend readers can fetch it).
        attachment = self.env["ir.attachment"].create(
            {
                "name": os.path.basename(self.name) or "download",
                "datas": base64.b64encode(data),
                "mimetype": "application/octet-stream",
                "res_model": "storage.backend",
                "res_id": backend.id,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%d?download=true" % attachment.id,
            "target": "self",
        }

    def action_delete(self):
        self.ensure_one()
        self.wizard_id.backend_id.delete(self.relative_path or self.name)
        return self.wizard_id.action_list_files()


class StorageBackendFileListWizard(models.TransientModel):
    _name = "storage.backend.file.list.wizard"
    _description = "Storage Backend File List Wizard"

    backend_id = fields.Many2one(
        comodel_name="storage.backend", required=True, readonly=True
    )
    backend_name = fields.Char(related="backend_id.name")
    backend_type = fields.Selection(related="backend_id.backend_type")
    directory_path = fields.Char(related="backend_id.directory_path")
    subpath = fields.Char(
        string="Subpath",
        help="Optional relative path inside the backend to list. "
        "Leave empty to list the backend root.",
    )
    limit = fields.Integer(
        default=200,
        required=True,
        help="Maximum number of files to load at once. Large backends "
        "(e.g. S3) would otherwise load every key and freeze the client.",
    )
    has_more = fields.Boolean(readonly=True)
    line_ids = fields.One2many(
        comodel_name="storage.backend.file.list.line",
        inverse_name="wizard_id",
        string="Files",
    )
    file_count = fields.Integer(compute="_compute_file_count")
    upload_path = fields.Char(
        string="Upload Path",
        help="Relative path inside the backend for the uploaded file, "
        "e.g. 'reports/export.csv'. Leave empty to use the current "
        "subpath and the filename.",
    )
    file_data = fields.Binary(string="File to Upload")
    filename = fields.Char()

    def _compute_file_count(self):
        for wizard in self:
            wizard.file_count = len(wizard.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        wizards._default_lines()
        return wizards

    def _default_lines(self):
        for wizard in self:
            if wizard.line_ids:
                continue
            wizard._load_files()

    def _load_files(self):
        self.ensure_one()
        # Ask for one more than the limit so we can tell whether the listing
        # was truncated without trusting the adapter to report totals.
        limit = self.limit or 200
        files = self.backend_id.list_files(
            relative_path=self.subpath or "", limit=limit + 1
        )
        has_more = len(files) > limit
        if has_more:
            files = files[:limit]
        self.has_more = has_more
        # Sync the lines in place instead of replacing them wholesale:
        # keeping existing line ids stable means row buttons still resolve
        # when the browser holds the listing from before a (possibly slow,
        # e.g. S3) refresh landed — replaced lines would raise
        # "Record does not exist or has been deleted".
        wanted = set(files)
        seen = set()
        stale = self.env["storage.backend.file.list.line"]
        for line in self.line_ids.sorted("id"):
            if line.name not in wanted or line.name in seen:
                stale |= line
            else:
                seen.add(line.name)
        stale.unlink()
        missing = [name for name in files if name not in seen]
        if missing:
            # Adapters list names relative to the requested path (browsing
            # level by level, "csindex/" shows "index_list.xlsx"), so re-join
            # the subpath to get the full path inside the backend.
            prefix = self.subpath.strip("/") if self.subpath else ""
            self.line_ids = [
                (
                    0,
                    0,
                    {
                        "name": name,
                        "relative_path": "/".join(p for p in (prefix, name) if p),
                    },
                )
                for name in missing
            ]

    def action_list_files(self):
        self.ensure_one()
        self._load_files()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": dict(self.env.context, default_backend_id=self.backend_id.id),
        }

    def action_upload(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(self.env._("Select a file to upload."))
        target = self.upload_path or os.path.join(self.subpath or "", self.filename)
        if not target:
            raise UserError(self.env._("Give the file to upload a name."))
        with self.backend_id.open(target, "wb") as stream:
            stream.write(base64.b64decode(self.file_data))
        self.file_data = False
        self.upload_path = False
        return self.action_list_files()
