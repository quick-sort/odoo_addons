import polars as pl

from odoo import models


class Dataset(models.Model):
    _inherit = "dataset"

    def to_dataframe(self) -> pl.DataFrame | None:
        self.ensure_one()
        frames = []
        for chunk in self.chunk_ids.sorted("id"):
            dataframe = chunk.to_dataframe()
            if dataframe is not None:
                frames.append(dataframe)
        if not frames:
            return None
        return pl.concat(frames, how="vertical_relaxed")
