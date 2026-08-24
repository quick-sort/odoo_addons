from odoo import fields, models


class ConferenceIndication(models.Model):
    _name = 'conference.indication'
    _description = 'Indication'
    _order = 'name'

    name = fields.Char(required=True)
    color = fields.Integer()
