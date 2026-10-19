from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = 'res.company'

    wechat_app_id = fields.Char(string='AppID', size=64, index=True)
    wechat_app_secret = fields.Char(string='AppSecret', size=128)
    wechat_token = fields.Char(
        string='Token', size=128, help='微信公众平台配置的消息校验Token')
    wechat_aes_key = fields.Char(
        string='EncodingAESKey', size=128,
        help='公众号消息加解密密钥(43位字符)')

    wechat_access_token = fields.Char(
        string='Access Token', size=512, copy=False, readonly=True)
    wechat_token_expire = fields.Datetime(
        string='Token过期时间', copy=False, readonly=True)

    def action_test_wechat_connection(self):
        self.ensure_one()
        try:
            token = self.env['wechat.request'].sudo()._get_access_token(self.id)
        except UserError as e:
            raise UserError(_('连接失败: %s') % e) from e
        if token:
            company = self.sudo()
            company.wechat_access_token = token
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('微信连接测试'),
                    'message': _('连接成功，Access Token 已刷新'),
                    'type': 'success',
                },
            }
        raise UserError(_('连接失败: 未获取到 Access Token'))
