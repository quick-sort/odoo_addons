import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class WechatUser(models.Model):
    """Public account (公众号) follower."""
    _name = 'wechat.user'
    _description = '公众号用户'
    _inherit = 'wechat.user.mixin'
    _rec_name = 'display_name'

    company_id = fields.Many2one(
        'res.company', string='公司', required=True, index=True,
        ondelete='cascade')

    group_id = fields.Char(
        string='用户组ID', size=64, index=True, help='公众号用户分组ID')
    group_name = fields.Char(string='用户组名称', size=128)
    qr_scene = fields.Char(
        string='场景二维码参数', size=64, help='场景二维码参数（数字）')
    qr_scene_str = fields.Char(
        string='场景二维码字符串', size=64, help='场景二维码参数（字符串）')
    remark = fields.Char(string='员工备注', size=128, help='员工对用户的备注')

    tag_ids = fields.Many2many(
        'wechat.user.tag', 'wechat_user_tag_rel', 'user_id', 'tag_id',
        string='用户标签')

    message_count = fields.Integer(
        string='消息数', compute='_compute_message_count',
        help='用户发送的消息总数')
    last_message_time = fields.Datetime(
        string='最后消息时间', compute='_compute_message_count')

    _openid_company_uniq = models.Constraint(
        'UNIQUE(wechat_openid, company_id)',
        '同一公司内OpenID不能重复',
    )

    display_name = fields.Char(compute='_compute_display_name')

    @api.depends('wechat_nickname', 'wechat_openid')
    def _compute_display_name(self):
        for record in self:
            record.display_name = (
                record.wechat_nickname or record.wechat_openid or _('WeChat User'))

    def _compute_message_count(self):
        for record in self:
            domain = [
                ('from_user', '=', record.wechat_openid),
                ('company_id', '=', record.company_id.id),
            ]
            logs = self.env['wechat.message.log'].sudo().search(domain)
            record.message_count = len(logs)
            record.last_message_time = (
                logs[:1].create_date if logs else False)

    @api.model
    def create_from_subscribe(self, company_id, event_data):
        """Create or update a follower from a subscribe event payload."""
        openid = event_data.get('FromUserName', '')
        if not openid:
            return self.env['wechat.user']

        user = self.search([
            ('wechat_openid', '=', openid),
            ('company_id', '=', company_id),
        ], limit=1)

        vals = {
            'company_id': company_id,
            'wechat_openid': openid,
            'wechat_subscribe': 'subscribed',
            'wechat_subscribe_time': fields.Datetime.now(),
        }

        event_key = event_data.get('EventKey', '')
        if event_key:
            # Subscribe-via-QR carries a 'qrscene_' prefix on the key
            if event_key.startswith('qrscene_'):
                event_key = event_key[8:]
            if event_key.isdigit():
                vals['qr_scene'] = event_key
            else:
                vals['qr_scene_str'] = event_key

        if user:
            user.write(vals)
            return user

        user_info = self._fetch_user_info(company_id, openid)
        if user_info:
            vals.update({
                'wechat_nickname': user_info.get('nickname', ''),
                'wechat_headimg': user_info.get('headimgurl', ''),
                'wechat_language': user_info.get('language', 'zh_CN'),
                'group_id': str(user_info.get('groupid', '') or ''),
                'wechat_remark': user_info.get('remark', ''),
            })
        return self.create(vals)

    def update_from_unsubscribe(self):
        self.write({'wechat_subscribe': 'unsubscribed'})

    def _fetch_user_info(self, company_id, openid):
        """Fetch user info via the unified API mixin. Returns dict or None."""
        try:
            result = self.env['wechat.request'].wechat_get(
                company_id, '/user/info',
                params={'openid': openid, 'lang': 'zh_CN'})
            if result and result.get('errcode', 0) == 0:
                return result
        except Exception as e:
            _logger.warning('Fetch user info failed for %s: %s', openid, e)
        return None

    def action_sync_user_info(self):
        self.ensure_one()
        user_info = self._fetch_user_info(
            self.company_id.id, self.wechat_openid)
        if user_info:
            self.sync_wechat_user_info(user_info)
            return True
        return False


class WechatUserTag(models.Model):
    _name = 'wechat.user.tag'
    _description = '公众号用户标签'

    name = fields.Char(string='标签名称', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='公司', required=True, index=True,
        ondelete='cascade')
    wechat_tag_id = fields.Char(
        string='微信标签ID', size=64, help='微信平台返回的标签ID')
    user_count = fields.Integer(
        string='用户数', compute='_compute_user_count')
    active = fields.Boolean(string='启用', default=True)

    _name_company_uniq = models.Constraint(
        'UNIQUE(name, company_id)', '同一公司内标签名称不能重复',
    )

    def _compute_user_count(self):
        for record in self:
            record.user_count = self.env['wechat.user'].search_count(
                [('tag_ids', 'in', record.id)])


class WechatUserGroup(models.Model):
    _name = 'wechat.user.group'
    _description = '公众号用户组'

    name = fields.Char(string='组名称', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='公司', required=True, index=True,
        ondelete='cascade')
    wechat_group_id = fields.Char(
        string='微信组ID', size=64, help='微信平台返回的组ID')
    user_count = fields.Integer(
        string='用户数', compute='_compute_user_count')
    active = fields.Boolean(string='启用', default=True)

    _name_company_uniq = models.Constraint(
        'UNIQUE(name, company_id)', '同一公司内组名称不能重复',
    )

    def _compute_user_count(self):
        for record in self:
            record.user_count = self.env['wechat.user'].search_count(
                [('group_id', '=', record.wechat_group_id or '-')])
