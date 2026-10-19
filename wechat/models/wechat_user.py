from datetime import datetime

from odoo import api, fields, models


class WechatUserMixin(models.AbstractModel):
    """Shared WeChat identity fields for concrete user models."""
    _name = 'wechat.user.mixin'
    _description = 'WeChat User Mixin'

    wechat_openid = fields.Char(
        string='OpenID', size=64, index=True, copy=False,
        help='WeChat OpenID - unique identifier for the user in this official account')
    wechat_unionid = fields.Char(
        string='UnionID', size=64, index=True, copy=False,
        help='WeChat UnionID - unique identifier for the user across WeChat platforms')
    wechat_subscribe = fields.Selection([
        ('subscribed', '已关注'),
        ('unsubscribed', '未关注'),
        ('never', '从未关注'),
    ], string='关注状态', default='never', index=True)
    wechat_subscribe_time = fields.Datetime(string='关注时间')
    wechat_subscribe_scene = fields.Char(
        string='关注场景', size=64,
        help='关注场景值，如公众号二维码、搜索、名片等')
    wechat_language = fields.Selection([
        ('zh_CN', '简体中文'),
        ('zh_TW', '繁体中文'),
        ('en', '英文'),
    ], string='语言')
    wechat_nickname = fields.Char(
        string='昵称', size=128,
        help='用户的昵称（注意：此字段单独存储，不与其他字段同步）')
    wechat_headimg = fields.Char(string='头像URL', size=512)
    wechat_remark = fields.Char(string='备注', size=128)

    def sync_wechat_user_info(self, user_info):
        """Sync WeChat user info from an API response dict."""
        self.ensure_one()
        vals = {}
        if 'openid' in user_info:
            vals['wechat_openid'] = user_info['openid']
        if 'unionid' in user_info:
            vals['wechat_unionid'] = user_info['unionid']
        if 'subscribe' in user_info:
            vals['wechat_subscribe'] = (
                'subscribed' if user_info['subscribe'] else 'unsubscribed')
        if 'subscribe_time' in user_info:
            try:
                vals['wechat_subscribe_time'] = datetime.fromtimestamp(
                    int(user_info['subscribe_time']))
            except (ValueError, TypeError):
                pass
        if 'subscribe_scene' in user_info:
            vals['wechat_subscribe_scene'] = user_info['subscribe_scene']
        if 'language' in user_info:
            vals['wechat_language'] = user_info['language']
        if 'nickname' in user_info:
            vals['wechat_nickname'] = user_info['nickname']
        if 'headimgurl' in user_info:
            vals['wechat_headimg'] = user_info['headimgurl']
        if 'remark' in user_info:
            vals['wechat_remark'] = user_info['remark']
        if vals:
            self.write(vals)
        return True

    @api.model
    def get_by_openid(self, openid):
        return self.search([('wechat_openid', '=', openid)], limit=1)
