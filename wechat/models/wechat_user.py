# -*- coding: utf-8 -*-
from odoo import fields, models, api


class WechatUser(models.Model):
    _name = 'wechat.user'
    _description = '企微成员（通讯录缓存）'
    _order = 'company_id, name'

    company_id = fields.Many2one('res.company', string="公司", required=True, default=lambda self: self.env.company)
    wechat_id = fields.Char(string='企业微信UserId', required=True, index=True)
    name = fields.Char(required=True)
    department_ids = fields.Many2many('wechat.department', string='所属部门')
    main_department_id = fields.Many2one('wechat.department', string='主部门')
    position = fields.Char(string='职位')
    job_number = fields.Char(string='工号')
    mobile = fields.Char(string='手机')
    email = fields.Char(string='邮箱')
    avatar_url = fields.Char(string='头像链接')
    alias = fields.Char(string='别名')
    gender = fields.Selection([('0', '未定义'), ('1', '男'), ('2', '女')], string='性别')
    status = fields.Selection([
        ('1', '已激活'), ('2', '已禁用'), ('4', '未激活'), ('5', '退出企业'),
    ], string='激活状态')

    _sql_constraints = [
        ('company_wechat_id_uniq', 'unique(company_id, wechat_id)', '同一公司下企业微信成员UserId不能重复。'),
    ]

    @api.model
    def sync_from_app(self, app, department_id=1, fetch_child=True):
        """
        通过指定的企微应用拉取成员数据，更新本地缓存。
        :return: 该公司下最新的全部 wechat.user 记录
        """
        app.ensure_one()
        data = app.get_users(department_id=department_id, fetch_child=fetch_child) or []
        company_id = app.company_id.id
        department_model = self.env['wechat.department']
        department_dict = {d.wechat_id: d.id for d in department_model.search([('company_id', '=', company_id)])}
        existing = {u.wechat_id: u for u in self.search([('company_id', '=', company_id)])}
        new_vals = []
        for item in data:
            job_number = next((attr.get('value') for attr in item.get('extattr', {}).get('attrs', [])
                                if attr.get('name') == '工号'), None)
            department_wechat_ids = item.get('department') or []
            department_ids = [department_dict[d] for d in department_wechat_ids if d in department_dict]
            main_department_wechat_id = item.get('main_department')
            vals = {
                'company_id': company_id,
                'wechat_id': item['userid'],
                'name': item['name'],
                'position': item.get('position', ''),
                'job_number': job_number,
                'department_ids': [(6, 0, department_ids)],
                'main_department_id': department_dict.get(main_department_wechat_id, False),
                'mobile': item.get('mobile'),
                'email': item.get('email'),
                'avatar_url': item.get('avatar'),
                'alias': item.get('alias'),
                'gender': str(item.get('gender')) if item.get('gender') is not None else False,
                'status': str(item.get('status')) if item.get('status') is not None else False,
            }
            if item['userid'] in existing:
                existing[item['userid']].write(vals)
            else:
                new_vals.append(vals)
        if new_vals:
            self.create(new_vals)
        return self.search([('company_id', '=', company_id)])
