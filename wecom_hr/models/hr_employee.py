from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    wecom_userid = fields.Char(string="企业微信UserId", index=True)
