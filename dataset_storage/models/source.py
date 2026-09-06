from odoo import _, models
from odoo.exceptions import ValidationError


class Source(models.Model):
    _inherit = "dataset.source"

    def write(self, vals):
        if "code" in vals:
            datasets = self.env["dataset"].search([("source_id", "in", self.ids)])
            for dataset in datasets:
                if not dataset._try_acquire_scan_lock():
                    raise ValidationError(
                        _(
                            "Source code cannot change while storage reconciliation "
                            "is active. Retry after the scan finishes."
                        )
                    )
        return super().write(vals)
