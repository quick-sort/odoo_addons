from odoo import fields, models


class HrDepartment(models.Model):
    _inherit = "hr.department"

    wecom_id = fields.Integer(string="企业微信部门ID", index=True)
