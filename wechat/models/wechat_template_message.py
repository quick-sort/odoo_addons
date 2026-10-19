import json
import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class WechatTemplateMessage(models.Model):
    """Template message registry: WeChat template IDs + data schemas."""
    _name = 'wechat.template.message'
    _description = '公众号模板消息'
    _order = 'name'

    name = fields.Char(string='模板名称', required=True, index=True)
    code = fields.Char(
        string='模板代码', size=64, index=True,
        help='程序化使用的代码，如 order_confirm')
    template_id = fields.Char(
        string='微信模板ID', required=True, index=True,
        help='从微信公众平台获取的模板ID')
    company_id = fields.Many2one(
        'res.company', string='公司', required=True, index=True,
        ondelete='cascade')
    data_schema = fields.Text(
        string='数据格式', default='{}',
        help='模板消息数据格式，JSON格式')
    description = fields.Text(string='描述', help='模板消息的用途说明')
    primary_color = fields.Char(
        string='主题色', size=16, default='#173177')
    active = fields.Boolean(string='启用', default=True)
    send_count = fields.Integer(string='发送次数', default=0)
    last_send_time = fields.Datetime(string='最后发送时间')

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)', '同一公司内模板代码不能重复',
    )
    _template_id_company_uniq = models.Constraint(
        'UNIQUE(template_id, company_id)', '同一公司内模板ID不能重复',
    )

    def get_data_schema_dict(self):
        self.ensure_one()
        try:
            return json.loads(self.data_schema)
        except (json.JSONDecodeError, TypeError):
            return {}

    def send_template_message(self, openid, data, url=''):
        """Send a template message via the unified API mixin."""
        self.ensure_one()
        msg_data = {
            'touser': openid,
            'template_id': self.template_id,
            'data': data,
        }
        if url:
            msg_data['url'] = url

        try:
            result = self.env['wechat.request'].wechat_post(
                self.company_id.id, '/message/template/send', json=msg_data)
        except Exception as e:
            _logger.error('Error sending template message: %s', e)
            return False

        if result and result.get('errcode', 0) == 0:
            self.write({
                'send_count': self.send_count + 1,
                'last_send_time': fields.Datetime.now(),
            })
            return True
        _logger.error('Template message send failed: %s', result)
        return False
