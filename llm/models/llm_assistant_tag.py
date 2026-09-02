from random import randint

from odoo import fields, models


class LLMAssistantTag(models.Model):
    _name = "llm.assistant.tag"
    _description = "LLM Assistant Tag"

    def _get_default_color(self):
        return randint(1, 11)

    name = fields.Char("Tag Name", required=True, translate=True)
    color = fields.Integer("Color", default=_get_default_color)

    _name_uniq = models.Constraint(
        'unique (name)',
        'Tag name already exists!',
    )
