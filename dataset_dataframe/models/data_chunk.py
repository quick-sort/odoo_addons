from io import BytesIO

import polars as pl

from odoo import fields, models


_READERS = {
    "csv": pl.read_csv,
    "parquet": pl.read_parquet,
}


class DataChunk(models.Model):
    _inherit = "dataset.data_chunk"

    record_count = fields.Integer(
        string="Record Count",
        readonly=True,
        help=(
            "Number of payload rows from the last explicit refresh. "
            "Use Refresh Record Count to update this value."
        ),
    )

    def to_dataframe(self) -> pl.DataFrame | None:
        self.ensure_one()
        chunk_type = self.dataset_id.chunk_type if self.dataset_id else None
        reader = _READERS.get(chunk_type)
        if reader is None:
            return None

        payload = self._read_payload()
        if not payload:
            return None

        dataframe = reader(BytesIO(payload))
        metadata = self.metadata or {}
        metadata_columns = [
            pl.lit(metadata[field_name]).alias(field_name)
            for field_name in (self.dataset_id.key_fields or [])
            if field_name in metadata and field_name not in dataframe.columns
        ]
        if metadata_columns:
            dataframe = dataframe.with_columns(metadata_columns)
        return dataframe

    def action_refresh_record_count(self):
        self.ensure_one()
        self.check_access("write")
        dataframe = self.to_dataframe()
        self.write({"record_count": dataframe.height if dataframe is not None else 0})
        return {"type": "ir.actions.client", "tag": "reload"}
