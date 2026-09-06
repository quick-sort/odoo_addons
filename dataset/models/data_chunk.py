import base64

from odoo import api, fields, models
from odoo.tools.misc import human_size


class DataChunk(models.Model):
    _name = "dataset.data_chunk"
    _description = "Dataset Data Chunk"
    _order = "id desc"
    _rec_name = "key"

    key = fields.Char(compute="_compute_key", store=True, readonly=True, index=True)
    dataset_id = fields.Many2one(
        "dataset", required=True, index=True, ondelete="restrict"
    )
    description = fields.Text()
    size = fields.Integer(string="Size in bytes")
    display_size = fields.Char(compute="_compute_display_size", string="Size")
    metadata = fields.Json()
    raw_data = fields.Binary(attachment=True)
    raw_data_filename = fields.Char()
    state = fields.Selection(
        [("missing", "Missing"), ("exists", "Exists"), ("checked", "Checked")],
        default="missing",
    )

    _key_dataset_unique = models.Constraint(
        "unique(key, dataset_id)", "Chunk key must be unique within dataset!"
    )

    @staticmethod
    def _raw_data_status(raw_data):
        if raw_data is False or raw_data is None:
            return 0, "missing"
        encoded = raw_data.encode("ascii") if isinstance(raw_data, str) else raw_data
        return len(base64.b64decode(encoded)), "exists"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "raw_data" in vals:
                vals["size"], vals["state"] = self._raw_data_status(vals["raw_data"])
            elif "size" in vals and "state" not in vals:
                vals["state"] = "exists" if vals["size"] else "missing"
        return super().create(vals_list)

    def write(self, vals):
        if "raw_data" in vals:
            size, state = self._raw_data_status(vals["raw_data"])
            vals = {**vals, "size": size, "state": state}
        elif "size" in vals and "state" not in vals:
            vals = {**vals, "state": "exists" if vals["size"] else "missing"}
        return super().write(vals)

    @api.depends("size")
    def _compute_display_size(self):
        for record in self:
            record.display_size = human_size(record.size) or ""

    @api.depends(
        "dataset_id",
        "metadata",
        "dataset_id.code",
        "dataset_id.chunk_type",
        "dataset_id.key_fields",
        "dataset_id.source_id.code",
    )
    def _compute_key(self):
        for record in self:
            record.key = (
                record.dataset_id.build_chunk_key(record.metadata)
                if record.dataset_id
                else False
            )

    def _read_payload(self):
        """Return attachment-backed payload bytes for standalone ``dataset``."""
        self.ensure_one()
        self.check_access("read")
        if not self.raw_data:
            return b""
        encoded = (
            self.raw_data.encode("ascii")
            if isinstance(self.raw_data, str)
            else self.raw_data
        )
        return base64.b64decode(encoded)

    def _get_preview_type(self):
        chunk_type = self.dataset_id.chunk_type if self.dataset_id else None
        return {
            "pdf": "pdf",
            "csv": "table",
            "docx": "binary",
            "xlsx": "binary",
            "pptx": "binary",
            "json": "text",
            "jsonl": "text",
            "parquet": "table",
            "txt": "text",
            "md": "text",
            "image": "binary",
        }.get(chunk_type or "", "binary")

    def action_preview(self):
        self.ensure_one()
        self.check_access("read")
        preview_type = self._get_preview_type()
        if preview_type == "table":
            payload = self._read_payload()
            if payload:
                wizard = self.env["dataset.table_preview_wizard"].create(
                    {
                        "chunk_id": self.id,
                        "raw_data": base64.b64encode(payload),
                    }
                )
                return {
                    "type": "ir.actions.act_window",
                    "name": self.display_name,
                    "res_model": "dataset.table_preview_wizard",
                    "res_id": wizard.id,
                    "target": "new",
                    "view_mode": "form",
                }
            raise ValueError("Cannot load preview data")
        view_xml_id = f"dataset.view_data_chunk_preview_{preview_type}"
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": "dataset.data_chunk",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(view_xml_id).id,
            "target": "new",
        }

    def action_open_file_wizard(self):
        self.ensure_one()
        self.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": "dataset.data_chunk",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("dataset.view_data_chunk_download").id,
            "target": "new",
        }
