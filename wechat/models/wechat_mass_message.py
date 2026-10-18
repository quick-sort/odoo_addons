import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WechatMassMessage(models.Model):
    """Mass message to all (or a tagged subset of) subscribers."""
    _name = 'wechat.mass.message'
    _description = '公众号群发消息'
    _order = 'create_date DESC'

    name = fields.Char(string='消息名称', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='公司', required=True, index=True,
        ondelete='cascade')
    msg_type = fields.Selection([
        ('text', '文本'),
        ('image', '图片'),
        ('voice', '语音'),
        ('video', '视频'),
        ('news', '图文'),
    ], string='消息类型', default='text', required=True)
    content = fields.Text(string='消息内容', help='文本内容或media_id')
    media_id = fields.Char(
        string='媒体ID', size=256, help='图片、语音、视频的media_id')
    title = fields.Char(string='标题', size=256, help='视频/图文消息标题')
    description = fields.Text(string='描述', help='视频/图文消息描述')
    tag_id = fields.Many2one(
        'wechat.user.tag', string='发送到标签',
        help='留空则发送给所有用户')
    scheduled_date = fields.Datetime(
        string='计划发送时间', help='留空则立即发送')
    sent_date = fields.Datetime(string='实际发送时间', readonly=True)
    state = fields.Selection([
        ('draft', '草稿'),
        ('sending', '发送中'),
        ('sent', '已发送'),
        ('failed', '发送失败'),
    ], string='状态', default='draft', index=True)
    error_msg = fields.Text(string='错误信息', readonly=True)
    msg_id = fields.Char(string='微信消息ID', size=64, readonly=True)

    _name_company_uniq = models.Constraint(
        'UNIQUE(name, company_id)', '同一公司内消息名称不能重复',
    )

    def action_send(self):
        for record in self:
            if record.state not in ('draft', 'failed'):
                continue
            record._do_send()
        return True

    def _do_send(self):
        self.ensure_one()
        self.write({'state': 'sending', 'error_msg': False})
        try:
            msg_body = self._prepare_message()
            result = self.env['wechat.request'].wechat_post(
                self.company_id.id, '/message/mass/sendall', json=msg_body)
        except Exception as e:
            self.write({'state': 'failed', 'error_msg': str(e)})
            _logger.error('Mass message error: %s', e)
            return False

        if result and result.get('errcode', 0) == 0:
            self.write({
                'state': 'sent',
                'sent_date': fields.Datetime.now(),
                'msg_id': str(result.get('msg_id', '')),
            })
            return True
        error_msg = (result or {}).get('errmsg', 'Unknown error')
        self.write({'state': 'failed', 'error_msg': error_msg})
        _logger.error('Mass message send failed: %s', error_msg)
        return False

    def _prepare_message(self):
        self.ensure_one()
        msg_body = {'msgtype': self.msg_type}

        if self.msg_type == 'text':
            msg_body['text'] = {'content': self.content or ''}
        elif self.msg_type == 'image':
            msg_body['image'] = {'media_id': self.media_id or ''}
        elif self.msg_type == 'voice':
            msg_body['voice'] = {'media_id': self.media_id or ''}
        elif self.msg_type == 'video':
            msg_body['mpvideo'] = {'media_id': self.media_id or ''}
        elif self.msg_type == 'news':
            msg_body['mpnews'] = {'media_id': self.media_id or ''}

        if self.tag_id and self.tag_id.wechat_tag_id:
            msg_body['filter'] = {
                'is_to_all': False, 'tag_id': self.tag_id.wechat_tag_id}
        else:
            msg_body['filter'] = {'is_to_all': True}
        return msg_body

    def action_retry(self):
        for record in self:
            if record.state == 'failed':
                record.write({'state': 'draft', 'error_msg': False})
        return self.action_send()
