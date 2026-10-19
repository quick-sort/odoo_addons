import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WechatMessageRule(models.Model):
    """Keyword-triggered auto-reply rule."""
    _name = 'wechat.message.rule'
    _description = '公众号关键字自动回复规则'
    _order = 'sequence, id'

    name = fields.Char(string='规则名称', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='公司', required=True, index=True,
        ondelete='cascade')
    keyword = fields.Char(
        string='关键字', required=True, index=True,
        help='触发自动回复的关键字')
    match_type = fields.Selection([
        ('exact', '精确匹配'),
        ('fuzzy', '模糊匹配'),
        ('regex', '正则匹配'),
    ], string='匹配方式', default='exact', required=True)
    reply_type = fields.Selection([
        ('text', '文本消息'),
        ('image', '图片消息'),
        ('voice', '语音消息'),
        ('video', '视频消息'),
        ('music', '音乐消息'),
        ('news', '图文消息'),
    ], string='回复类型', default='text', required=True)
    reply_content = fields.Text(
        string='回复内容',
        help='回复的内容。文本直接填写；图片/语音/视频填写media_id')
    media_id = fields.Char(
        string='媒体ID', size=256, help='图片、语音、视频的media_id')
    title = fields.Char(string='标题', size=256, help='图文消息的标题')
    description = fields.Text(string='描述', help='图文消息的描述')
    url = fields.Char(string='链接地址', size=512, help='图文消息的链接地址')
    thumb_media_id = fields.Char(
        string='缩略图media_id', size=256, help='图文消息的缩略图media_id')
    sequence = fields.Integer(
        string='优先级', default=0,
        help='数值越小优先级越高，匹配到后不再继续匹配')
    active = fields.Boolean(string='启用', default=True, index=True)
    reply_count = fields.Integer(
        string='回复次数', default=0, help='该规则被触发的次数')
    last_trigger_time = fields.Datetime(string='最后触发时间')

    _keyword_company_uniq = models.Constraint(
        'UNIQUE(keyword, match_type, company_id)',
        '相同公司和匹配方式下关键字不能重复',
    )

    @api.model
    def match_keyword(self, company_id, keyword):
        """Return the highest-priority active rule matching the keyword, or None."""
        rules = self.search([
            ('company_id', '=', company_id),
            ('active', '=', True),
        ], order='sequence asc')
        for rule in rules:
            if rule._match_rule(keyword):
                rule.write({
                    'reply_count': rule.reply_count + 1,
                    'last_trigger_time': fields.Datetime.now(),
                })
                return rule
        return None

    def _match_rule(self, keyword):
        self.ensure_one()
        if self.match_type == 'exact':
            return keyword == self.keyword
        if self.match_type == 'fuzzy':
            return self.keyword in keyword
        if self.match_type == 'regex':
            try:
                return re.search(self.keyword, keyword) is not None
            except re.error:
                _logger.warning('Invalid regex pattern: %s', self.keyword)
                return False
        return False

    def get_reply_data(self):
        """Build the reply payload consumed by the passive-reply XML builder."""
        self.ensure_one()
        if self.reply_type == 'text':
            return {'msg_type': 'text', 'content': self.reply_content or ''}
        if self.reply_type in ('image', 'voice'):
            return {'msg_type': self.reply_type, 'media_id': self.media_id or ''}
        if self.reply_type == 'video':
            return {
                'msg_type': 'video',
                'media_id': self.media_id or '',
                'title': self.title or '',
                'description': self.description or '',
            }
        if self.reply_type == 'music':
            return {
                'msg_type': 'music',
                'title': self.title or '',
                'description': self.description or '',
                'music_url': self.url or '',
                'hq_music_url': self.url or '',
                'thumb_media_id': self.thumb_media_id or '',
            }
        if self.reply_type == 'news':
            articles = [{
                'title': self.title or '',
                'description': self.description or '',
                'url': self.url or '',
                'picurl': self.media_id or '',
            }]
            return {'msg_type': 'news', 'articles': articles}
        return {'msg_type': 'text', 'content': ''}


def _simple_reply_data(record):
    """Shared reply payload for default / subscribe replies (text|image|news)."""
    if record.reply_type == 'text':
        return {'msg_type': 'text', 'content': record.reply_content or ''}
    if record.reply_type == 'image':
        return {'msg_type': 'image', 'media_id': record.media_id or ''}
    if record.reply_type == 'news':
        articles = [{
            'title': record.title or '',
            'description': record.description or '',
            'url': record.url or '',
            'picurl': record.media_id or '',
        }]
        return {'msg_type': 'news', 'articles': articles}
    return {'msg_type': 'text', 'content': ''}


class WechatAutoReplyDefault(models.Model):
    """Fallback reply when no keyword rule matches."""
    _name = 'wechat.auto.reply.default'
    _description = '公众号默认自动回复'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', string='公司', required=True, index=True,
        ondelete='cascade')
    reply_type = fields.Selection([
        ('text', '文本消息'),
        ('image', '图片消息'),
        ('news', '图文消息'),
    ], string='回复类型', default='text', required=True)
    reply_content = fields.Text(string='回复内容')
    media_id = fields.Char(string='媒体ID', size=256)
    title = fields.Char(string='标题', size=256)
    description = fields.Text(string='描述')
    url = fields.Char(string='链接', size=512)
    active = fields.Boolean(string='启用', default=True)

    _company_uniq = models.Constraint(
        'UNIQUE(company_id)', '每个公司只能有一个默认回复',
    )

    def get_reply_data(self):
        self.ensure_one()
        return _simple_reply_data(self)


class WechatSubscribeReply(models.Model):
    """Reply sent when a user follows the account."""
    _name = 'wechat.subscribe.reply'
    _description = '公众号关注回复'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', string='公司', required=True, index=True,
        ondelete='cascade')
    reply_type = fields.Selection([
        ('text', '文本消息'),
        ('image', '图片消息'),
        ('news', '图文消息'),
    ], string='回复类型', default='text', required=True)
    reply_content = fields.Text(string='回复内容')
    media_id = fields.Char(string='媒体ID', size=256)
    title = fields.Char(string='标题', size=256)
    description = fields.Text(string='描述')
    url = fields.Char(string='链接', size=512)
    active = fields.Boolean(string='启用', default=True)

    _company_uniq = models.Constraint(
        'UNIQUE(company_id)', '每个公司只能有一个关注回复',
    )

    def get_reply_data(self):
        self.ensure_one()
        return _simple_reply_data(self)
