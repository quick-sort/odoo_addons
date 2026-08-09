# Copyright 2026 ACSONE SA/NV (<http://acsone.eu>)
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


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
        self.line_ids = [(5, 0, 0)] + [
            (0, 0, {"name": name, "relative_path": name}) for name in files
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
