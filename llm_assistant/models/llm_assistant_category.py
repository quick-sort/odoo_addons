from odoo import _, api, fields, models


class LLMAssistantCategory(models.Model):
    _name = "llm.assistant.category"
    _description = "LLM Assistant Category"
    _parent_name = "parent_id"
    _parent_store = True
    _rec_name = "complete_name"
    _order = "complete_name"

    name = fields.Char(
        string="Category Name",
        required=True,
        index=True,
    )
    complete_name = fields.Char(
        string="Complete Name",
        compute="_compute_complete_name",
        store=True,
        recursive=True,
    )
    parent_id = fields.Many2one(
        "llm.assistant.category",
        string="Parent Category",
        index=True,
        ondelete="cascade",
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        "llm.assistant.category",
        "parent_id",
        string="Child Categories",
    )
    assistant_count = fields.Integer(
        string="Assistant Count",
        compute="_compute_assistant_count",
    )
    active = fields.Boolean(default=True)
    code = fields.Char(
        string="Category Code",
        help="Technical code to identify this category",
    )
    description = fields.Text(
        string="Description",
    )
    sequence = fields.Integer(
        string="Sequence",
        default=10,
    )

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = (
                    f"{category.parent_id.complete_name} / {category.name}"
                )
            else:
                category.complete_name = category.name

    @api.depends("child_ids")
    def _compute_assistant_count(self):
        counts = {
            category.id: count
            for category, count in self.env["llm.assistant"]._read_group(
                [("category_id", "child_of", self.ids)],
                groupby=["category_id"],
                aggregates=["__count"],
            )
        }

        for category in self:
            category.assistant_count = counts.get(category.id, 0)

    @api.constrains("parent_id")
    def _check_category_recursion(self):
        if self._has_cycle():
            raise models.ValidationError(
                _("Error! You cannot create recursive categories.")
            )
