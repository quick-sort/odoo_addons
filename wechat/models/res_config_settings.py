from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    wechat_keywords_reply_enabled = fields.Boolean(
        string='启用关键字回复',
        config_parameter='wechat.keywords_reply_enabled',
        help='根据关键字匹配自动回复')
    wechat_auto_reply_enabled = fields.Boolean(
        string='启用默认自动回复',
        config_parameter='wechat.auto_reply_enabled',
        help='当用户发送消息且无关键字匹配时回复默认内容')
    wechat_menu_enabled = fields.Boolean(
        string='启用自定义菜单',
        config_parameter='wechat.menu_enabled',
        help='启用公众号自定义菜单功能')
    wechat_template_message_enabled = fields.Boolean(
        string='启用模板消息',
        config_parameter='wechat.template_message_enabled',
        help='允许发送模板消息')
    wechat_message_keep_days = fields.Integer(
        string='消息保留天数',
        config_parameter='wechat.message.keep_days',
        help='超过该天数的消息记录将被清理')
