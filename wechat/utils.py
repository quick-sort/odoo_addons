import logging

_logger = logging.getLogger(__name__)

try:
    from wechatpy import WeChatClient
    from wechatpy.exceptions import WeChatClientException
except ImportError:
    _logger.warning(
        'wechatpy is not installed. Please install it with: pip install wechatpy')
    WeChatClient = None
    WeChatClientException = Exception


def wechat_client(app_id, secret):
    if WeChatClient is None:
        from odoo.exceptions import UserError
        raise UserError('wechatpy库未安装。请运行: pip install wechatpy')
    return WeChatClient(app_id, secret)


def has_wechatpy():
    return WeChatClient is not None
