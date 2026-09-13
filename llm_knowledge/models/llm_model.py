"""Knowledge-specific safeguards for embedding model roles."""

from odoo import _, models
from odoo.exceptions import UserError


class LLMModel(models.Model):
    _inherit = "llm.model"

    def write(self, vals):
        role_fields = {"model_use", "embedding_type"}
        if role_fields.intersection(vals):
            changed = self.filtered(
                lambda model: any(
                    field_name in vals
                    and vals[field_name] != model[field_name]
                    for field_name in role_fields
                )
            )
            if changed:
                databases = self.env["llm.store.database"].search(
                    [
                        "|",
                        ("dense_embedding_model_id", "in", changed.ids),
                        ("sparse_embedding_model_id", "in", changed.ids),
                    ],
                    limit=1,
                )
                if databases:
                    raise UserError(
                        _(
                            "Model '%(model)s' is used by vector database "
                            "'%(database)s'. Remove it from that database before "
                            "changing its usage or embedding type.",
                            model=changed[0].name,
                            database=databases.name,
                        )
                    )
        return super().write(vals)
