from odoo import fields, models


class ConferenceTarget(models.Model):
    _name = 'conference.target'
    _description = 'Target'
    _order = 'name'

    name = fields.Char(required=True)
    color = fields.Integer()
