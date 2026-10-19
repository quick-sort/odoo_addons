from odoo.tests.common import TransactionCase


class WechatTransactionCase(TransactionCase):
    """Base: a company with WeChat credentials on record (no API calls)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Test WeChat Co',
            'wechat_app_id': 'wx_test_appid',
            'wechat_app_secret': 'test-secret',
            'wechat_token': 'test-token',
        })

    @classmethod
    def _log_vals(cls, **overrides):
        vals = {
            'company_id': cls.company.id,
            'msgid': 'msg-1',
            'from_user': 'openid-A',
            'to_user': 'gh_official',
            'msg_type': 'text',
            'content': 'hello',
            'direction': 'inbound',
            'state': 'done',
        }
        vals.update(overrides)
        return vals
