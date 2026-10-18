import json

from odoo import api, fields, models
from odoo.exceptions import UserError

MENU_BUTTON_TYPES = [
    ('view', '跳转网页'),
    ('click', '点击事件'),
    ('miniprogram', '小程序'),
    ('scancode_push', '扫码推送'),
    ('scancode_waitmsg', '扫码提示'),
    ('pic_sysphoto', '系统拍照'),
    ('pic_photo_or_album', '拍照或相册'),
    ('pic_weixin', '微信相册'),
    ('location_select', '位置选择'),
    ('media_id', '下发消息'),
    ('view_limited', '跳转小程序'),
]

KEY_TYPES = ('click', 'scancode_push', 'scancode_waitmsg', 'pic_sysphoto',
             'pic_photo_or_album', 'pic_weixin', 'location_select')


class WechatMenu(models.Model):
    """Custom menu per company, kept as structured buttons + JSON mirror."""
    _name = 'wechat.menu'
    _description = '公众号自定义菜单'
    _order = 'sequence, id'

    name = fields.Char(string='菜单名称', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='公司', required=True, index=True,
        ondelete='cascade')
    menu_json = fields.Text(
        string='菜单JSON', compute='_compute_menu_json',
        help='菜单JSON格式，与微信API格式一致')
    sync_status = fields.Selection([
        ('pending', '待同步'),
        ('syncing', '同步中'),
        ('synced', '已同步'),
        ('failed', '同步失败'),
    ], string='同步状态', default='pending', index=True)
    last_sync_time = fields.Datetime(string='最后同步时间', readonly=True)
    last_error = fields.Text(string='最后错误', readonly=True)
    sequence = fields.Integer(string='优先级', default=0)
    active = fields.Boolean(string='启用', default=True)

    menu_buttons = fields.One2many(
        'wechat.menu.button', 'menu_id', string='菜单按钮')

    _company_uniq = models.Constraint(
        'UNIQUE(company_id)', '每个公司只能有一个自定义菜单',
    )

    @api.depends('menu_buttons.sequence', 'menu_buttons.name',
                 'menu_buttons.button_type', 'menu_buttons.key',
                 'menu_buttons.url', 'menu_buttons.appid',
                 'menu_buttons.pagepath', 'menu_buttons.media_id',
                 'menu_buttons.parent_id')
    def _compute_menu_json(self):
        for record in self:
            record.menu_json = json.dumps(
                {'button': [b._to_wechat_dict() for b in
                            record.menu_buttons.filtered(
                                lambda b: not b.parent_id).sorted('sequence')]},
                ensure_ascii=False, indent=2)

    def action_sync(self):
        """Push the menu JSON to WeChat via the API mixin."""
        for record in self:
            record.sync_status = 'syncing'
            try:
                result = self.env['wechat.request'].wechat_post(
                    record.company_id.id, '/menu/create',
                    json=json.loads(record.menu_json))
            except UserError as e:
                record.write({'sync_status': 'failed', 'last_error': str(e)})
                continue
            if result and result.get('errcode', 0) == 0:
                record.write({
                    'sync_status': 'synced',
                    'last_sync_time': fields.Datetime.now(),
                    'last_error': False,
                })
            else:
                record.write({
                    'sync_status': 'failed',
                    'last_error': (result or {}).get('errmsg', 'unknown error'),
                })
        return True

    def action_delete_remote(self):
        """Delete the menu on the WeChat side."""
        for record in self:
            result = self.env['wechat.request'].wechat_post(
                record.company_id.id, '/menu/delete')
            if result and result.get('errcode', 0) == 0:
                record.write({
                    'sync_status': 'pending',
                    'last_sync_time': fields.Datetime.now(),
                    'last_error': False,
                })
            else:
                record.write({
                    'sync_status': 'failed',
                    'last_error': (result or {}).get('errmsg', 'unknown error'),
                })
        return True


class WechatMenuButton(models.Model):
    _name = 'wechat.menu.button'
    _description = '公众号菜单按钮'
    _order = 'sequence, id'

    menu_id = fields.Many2one(
        'wechat.menu', string='所属菜单', required=True, ondelete='cascade')
    parent_id = fields.Many2one(
        'wechat.menu.button', string='父按钮', ondelete='cascade',
        help='如果设置此项，则为子菜单')
    name = fields.Char(string='按钮名称', required=True)
    button_type = fields.Selection(
        MENU_BUTTON_TYPES, string='按钮类型',
        help='按钮类型，空表示仅为分组父按钮')
    key = fields.Char(string='Key', size=128, help='click类型按钮的key值')
    url = fields.Char(string='跳转URL', size=512, help='view类型按钮的网页链接')
    appid = fields.Char(string='小程序AppID', size=64)
    pagepath = fields.Char(string='小程序页面路径', size=256)
    media_id = fields.Char(
        string='MediaID', size=256, help='media_id类型按钮的素材id')
    sequence = fields.Integer(string='排序', default=0)
    active = fields.Boolean(string='启用', default=True)

    sub_buttons = fields.One2many(
        'wechat.menu.button', 'parent_id', string='子菜单')

    @api.model_create_multi
    def create(self, vals_list):
        # Sub-buttons created via a parent's sub_buttons o2m carry no menu_id;
        # the ORM only links the inverse of the field the command came through
        for vals in vals_list:
            if not vals.get('menu_id') and vals.get('parent_id'):
                vals['menu_id'] = self.browse(vals['parent_id']).menu_id.id
        return super().create(vals_list)

    def _to_wechat_dict(self):
        self.ensure_one()
        button = {'type': self.button_type or 'view', 'name': self.name}
        if self.button_type == 'view':
            button['url'] = self.url or ''
        elif self.button_type == 'click':
            button['key'] = self.key or ''
        elif self.button_type == 'miniprogram':
            button['appid'] = self.appid or ''
            button['pagepath'] = self.pagepath or ''
            button['url'] = self.url or ''
        elif self.button_type in KEY_TYPES:
            button['key'] = self.key or ''
        elif self.button_type in ('media_id', 'view_limited'):
            button['media_id'] = self.media_id or ''
        if self.sub_buttons:
            button.pop('type', None)
            button['sub_button'] = [
                b._to_wechat_dict() for b in self.sub_buttons.sorted('sequence')]
        return button

    @api.onchange('button_type')
    def _onchange_button_type(self):
        """Clear fields irrelevant to the chosen type."""
        keep = {'view': ('url',),
                'click': ('key',),
                'miniprogram': ('appid', 'pagepath', 'url'),
                'media_id': ('media_id',),
                'view_limited': ('media_id',)}
        relevant = keep.get(self.button_type, ('key',) if
                            self.button_type in KEY_TYPES else ())
        for fname in ('key', 'url', 'appid', 'pagepath', 'media_id'):
            if fname not in relevant:
                self[fname] = False
