# -*- coding: utf-8 -*-
from odoo import fields, models, api


class WecomDepartment(models.Model):
    _name = 'wecom.department'
    _description = '企微部门（通讯录缓存）'
    _order = 'company_id, wecom_id'

    company_id = fields.Many2one('res.company', string="公司", required=True, default=lambda self: self.env.company)
    wecom_id = fields.Integer(string='企业微信部门ID', required=True, index=True)
    name = fields.Char(required=True)
    parent_id = fields.Many2one('wecom.department', string='上级部门')
    department_leader = fields.Char(string='负责人UserId')
    wecom_order = fields.Char(string='排序值')

    _company_wecom_id_uniq = models.Constraint(
        'unique(company_id, wecom_id)',
        '同一公司下企业微信部门ID不能重复。')

    @api.model
    def sync_from_app(self, app):
        """
        通过指定的企微应用拉取部门数据，更新本地缓存（新增/更新/维护上级部门关系）。
        :return: 该公司下最新的全部 wecom.department 记录
        """
        app.ensure_one()
        data = app.get_departments() or []
        company_id = app.company_id.id
        existing = {d.wecom_id: d for d in self.search([('company_id', '=', company_id)])}
        new_vals = []
        for item in data:
            leader = item.get('department_leader')
            if isinstance(leader, list):
                leader = '|'.join(leader)
            vals = {
                'company_id': company_id,
                'wecom_id': item['id'],
                'name': item['name'],
                'department_leader': leader or False,
                'wecom_order': item.get('order'),
            }
            if item['id'] in existing:
                existing[item['id']].write(vals)
            else:
                new_vals.append(vals)
        if new_vals:
            created = self.create(new_vals)
            existing.update({d.wecom_id: d for d in created})
        # 第二遍：维护上级部门关系（此时所有部门都已存在于 existing 中）
        for item in data:
            parentid = item.get('parentid')
            wecom_id = item.get('id')
            if parentid and wecom_id in existing:
                parent = existing.get(parentid)
                if parent and existing[wecom_id].parent_id != parent:
                    existing[wecom_id].parent_id = parent.id
        return self.search([('company_id', '=', company_id)])
