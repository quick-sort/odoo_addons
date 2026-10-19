import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WechatMessage(models.Model):
    """Base storage for all WeChat messages (inbound and outbound)."""
    _name = 'wechat.message'
    _description = 'WeChat Message'
    _order = 'create_date DESC'

    name = fields.Char(string='Message Name', compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        ondelete='cascade')
    msgid = fields.Char(
        string='Message ID', size=64, index=True,
        help='WeChat message ID from the platform')
    from_user = fields.Char(
        string='From User', size=64, help='OpenID of the sender')
    to_user = fields.Char(
        string='To User', size=64,
        help='OpenID of the recipient (usually the official account)')
    msg_type = fields.Selection([
        ('text', '文本消息'),
        ('image', '图片消息'),
        ('voice', '语音消息'),
        ('video', '视频消息'),
        ('shortvideo', '小视频消息'),
        ('location', '位置消息'),
        ('link', '链接消息'),
        ('event', '事件消息'),
    ], string='Message Type', index=True)
    content = fields.Text(string='Message Content')
    direction = fields.Selection([
        ('inbound', '接收'),
        ('outbound', '发送'),
    ], string='Direction', default='inbound', index=True)
    event_type = fields.Char(
        string='Event Type', size=64,
        help='Event type for event messages (e.g., subscribe, unsubscribe, click)')
    event_key = fields.Char(
        string='Event Key', size=256,
        help='Event key for menu clicks or QR code scans')
    media_id = fields.Char(string='Media ID', size=256)
    pic_url = fields.Char(string='Picture URL', size=512)
    format = fields.Char(string='Voice Format', size=32)
    recognition = fields.Text(string='Speech Recognition')
    location_x = fields.Float(string='Latitude')
    location_y = fields.Float(string='Longitude')
    scale = fields.Integer(string='Map Scale')
    label = fields.Char(string='Location Label', size=256)
    title = fields.Char(string='Link Title', size=256)
    description = fields.Text(string='Link Description')
    url = fields.Char(string='Link URL', size=512)
    state = fields.Selection([
        ('pending', '待处理'),
        ('processing', '处理中'),
        ('done', '已完成'),
        ('failed', '处理失败'),
    ], string='State', default='pending', index=True)
    fail_reason = fields.Text(string='Failure Reason')
    reply_msgid = fields.Char(string='Reply Message ID', size=64)

    _msgid_company_uniq = models.Constraint(
        'UNIQUE(msgid, company_id)', 'Message ID must be unique per company',
    )

    @api.depends('msgid', 'msg_type', 'create_date')
    def _compute_name(self):
        for record in self:
            if record.msgid:
                date_str = record.create_date.strftime(
                    '%Y%m%d %H:%M') if record.create_date else ''
                msg_type_display = dict(
                    self._fields['msg_type'].selection).get(record.msg_type, '')
                record.name = f'{msg_type_display} - {record.msgid[:16]} - {date_str}'
            elif record.create_date:
                record.name = f'New Message - {record.create_date}'
            else:
                record.name = 'New Message'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'company_id' not in vals and self.env.context.get('default_company_id'):
                vals['company_id'] = self.env.context['default_company_id']
        return super().create(vals_list)

    @api.model
    def _cleanup_old_messages(self):
        """Cron: delete messages older than the configured retention period."""
        keep_days = int(self.env['ir.config_parameter'].sudo().get_param(
            'wechat.message.keep_days', '90'))
        cutoff_date = datetime.now() - timedelta(days=keep_days)
        old_messages = self.search([('create_date', '<', cutoff_date)])
        if old_messages:
            _logger.info(
                'Deleting %d WeChat messages older than %s',
                len(old_messages), cutoff_date)
            old_messages.unlink()
        return len(old_messages)

    def action_mark_processing(self):
        self.write({'state': 'processing'})
        return True

    def action_mark_done(self):
        self.write({'state': 'done'})
        return True

    def action_mark_failed(self, reason=''):
        self.write({'state': 'failed', 'fail_reason': reason})
        return True


class WechatMessageLog(models.Model):
    """MP-specific message log, extends the base message with reply tracking."""
    _name = 'wechat.message.log'
    _description = '公众号消息日志'
    _inherit = 'wechat.message'
    _table = 'wechat_message_log'

    user_id = fields.Many2one(
        'wechat.user', string='发送用户', ondelete='set null')
    thumb_media_id = fields.Char(string='缩略图MediaID', size=256)
    precision = fields.Float(string='精度', digits=(10, 5))
    reply_type = fields.Selection([
        ('text', '文本'),
        ('image', '图片'),
        ('voice', '语音'),
        ('video', '视频'),
        ('music', '音乐'),
        ('news', '图文'),
    ], string='回复类型')
    reply_content = fields.Text(string='回复内容')
    reply_media_id = fields.Char(string='回复媒体ID', size=256)
    raw_xml = fields.Text(string='原始XML', help='原始的XML数据')
    processed = fields.Boolean(string='已处理', default=False, index=True)


class WechatMessageCleanupCron(models.AbstractModel):
    _name = 'wechat.message.cron'
    _description = 'WeChat Message Cleanup Cron'

    @api.model
    def run_cleanup(self):
        # Logs live in their own table (prototype inheritance), so cleanup
        # must run on the log model, not on the abstract base
        return self.env['wechat.message.log']._cleanup_old_messages()
