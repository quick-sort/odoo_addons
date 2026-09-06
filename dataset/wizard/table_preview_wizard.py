import base64
import csv
import io

from odoo import api, fields, models
from odoo.tools.misc import html_escape as _esc

try:
    import pyarrow.parquet as pq

    _PYARROW_AVAILABLE = True
except ImportError:
    _PYARROW_AVAILABLE = False

_DEFAULT_PAGE_SIZE = 50
_PAGE_SIZE_SELECTION = [(str(size), str(size)) for size in (10, 25, 50, 100)]


class TablePreviewWizard(models.TransientModel):
    _name = "dataset.table_preview_wizard"
    _description = "Table Preview Wizard"

    chunk_id = fields.Many2one("dataset.data_chunk", required=True)
    chunk_name = fields.Char(
        related="chunk_id.display_name", string="Chunk Name", readonly=True
    )
    raw_data = fields.Binary(readonly=True)
    headers = fields.Text(readonly=True)
    total_rows = fields.Integer(readonly=True)
    total_pages = fields.Integer(readonly=True)
    page = fields.Integer(default=1)
    page_size = fields.Selection(
        _PAGE_SIZE_SELECTION, default=str(_DEFAULT_PAGE_SIZE), required=True
    )
    page_label = fields.Char(compute="_compute_page_label")
    table_html = fields.Html(string="Rows")

    @api.depends("page", "total_pages")
    def _compute_page_label(self):
        for record in self:
            record.page_label = f"{record.page} / {record.total_pages or 1}"

    def _load_table_data(self, chunk=None):
        chunk = chunk or self.chunk_id
        encoded = self.raw_data or (chunk.raw_data if chunk else None)
        if not encoded:
            return [], []
        if isinstance(encoded, str):
            encoded = encoded.encode("utf-8")
        payload = base64.b64decode(encoded)
        chunk_type = chunk.dataset_id.chunk_type if chunk.dataset_id else None
        if chunk_type == "csv":
            reader = csv.DictReader(payload.decode("utf-8", errors="replace").splitlines())
            return reader.fieldnames or [], list(reader)
        if chunk_type == "parquet" and _PYARROW_AVAILABLE:
            frame = pq.read_table(io.BytesIO(payload)).to_pandas()
            return list(frame.columns), frame.to_dict("records")
        return [], []

    @api.model
    def _total_pages(self, total, page_size):
        return max(1, (total + page_size - 1) // page_size) if page_size else 1

    def _int_page_size(self):
        try:
            return int(self.page_size)
        except (TypeError, ValueError):
            return _DEFAULT_PAGE_SIZE

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard in wizards:
            headers, rows = wizard._load_table_data(wizard.chunk_id)
            page_size = wizard._int_page_size()
            wizard.write(
                {
                    "headers": ",".join(str(header) for header in headers),
                    "total_rows": len(rows),
                    "total_pages": wizard._total_pages(len(rows), page_size),
                    "table_html": wizard._build_html_table(headers, rows[:page_size]),
                }
            )
        return wizards

    def _build_html_table(self, headers, rows):
        if not headers:
            return ""
        headings = "".join(f"<th>{_esc(header)}</th>" for header in headers)
        body = ""
        for row in rows:
            values = (row.get(header, "") for header in headers) if isinstance(row, dict) else row
            body += "<tr>" + "".join(f"<td>{_esc(value)}</td>" for value in values) + "</tr>"
        return f'<table class="table table-striped table-sm"><thead><tr>{headings}</tr></thead><tbody>{body}</tbody></table>'

    def _reload_wizard(self):
        return {"type": "ir.actions.act_window", "name": self.chunk_id.display_name, "res_id": self.id, "res_model": self._name, "view_mode": "form", "target": "new"}

    @api.onchange("page_size")
    def _onchange_page_size(self):
        self.page = 1

    def action_prev(self):
        self._write_page(max(1, self.page - 1))
        return self._reload_wizard()

    def action_next(self):
        self._write_page(min(self.total_pages or 1, self.page + 1))
        return self._reload_wizard()

    def _write_page(self, page):
        headers, rows = self._load_table_data(self.chunk_id)
        page_size = self._int_page_size()
        start = (page - 1) * page_size
        self.write({"page": page, "headers": ",".join(str(header) for header in headers), "total_rows": len(rows), "total_pages": self._total_pages(len(rows), page_size), "table_html": self._build_html_table(headers, rows[start : start + page_size])})
