from xml.etree import ElementTree as ET

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.http import Response
from odoo.tests import tagged

from .common import WechatTransactionCase


@tagged('post_install', '-at_install')
class TestCallbackReply(WechatTransactionCase):
    """Test the passive-reply rendering and dispatch logic without HTTP."""

    def _controller(self):
        from ..controllers.mp_callback import WechatMpCallback
        return WechatMpCallback()

    def _call(self, method, *args):
        with MockRequest(self.env):
            return method(*args)

    def _msg_data(self, **overrides):
        data = {
            'MsgType': 'text',
            'MsgId': '12345',
            'FromUserName': 'openid-A',
            'ToUserName': 'gh_official',
            'Content': '价格',
        }
        data.update(overrides)
        return data

    def test_render_text_reply(self):
        controller = self._controller()
        response = controller._render_reply_xml(
            self._msg_data(), {'msg_type': 'text', 'content': '请看价格页'})
        self.assertIsInstance(response, Response)
        root = ET.fromstring(response.data.decode())
        self.assertEqual(root.find('ToUserName').text, 'openid-A')
        self.assertEqual(root.find('FromUserName').text, 'gh_official')
        self.assertEqual(root.find('MsgType').text, 'text')
        self.assertEqual(root.find('Content').text, '请看价格页')
        self.assertTrue(root.find('CreateTime').text.isdigit())

    def test_render_news_reply(self):
        controller = self._controller()
        response = controller._render_reply_xml(self._msg_data(), {
            'msg_type': 'news',
            'articles': [{'title': 'T', 'description': 'D',
                          'url': 'http://u', 'picurl': 'http://p'}],
        })
        root = ET.fromstring(response.data.decode())
        self.assertEqual(root.find('MsgType').text, 'news')
        self.assertEqual(root.find('ArticleCount').text, '1')
        self.assertEqual(root.find('Articles/item/Title').text, 'T')

    def test_render_empty_articles_returns_success(self):
        controller = self._controller()
        response = controller._render_reply_xml(
            self._msg_data(), {'msg_type': 'news', 'articles': []})
        self.assertEqual(response.data, b'success')

    def test_on_text_keyword_rule(self):
        self.env['wechat.message.rule'].create({
            'name': '价格',
            'company_id': self.company.id,
            'keyword': '价格',
            'match_type': 'exact',
            'reply_type': 'text',
            'reply_content': '价格是 99',
        })
        reply = self._call(
            self._controller()._on_text,
            self.company.id, self.company, self._msg_data())
        self.assertEqual(reply, {'msg_type': 'text', 'content': '价格是 99'})

    def test_on_text_fallback_default_reply(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'wechat.auto_reply_enabled', 'True')
        self.env['wechat.auto.reply.default'].create({
            'company_id': self.company.id,
            'reply_content': '默认回复',
        })
        reply = self._call(
            self._controller()._on_text,
            self.company.id, self.company, self._msg_data(Content='别的话'))
        self.assertEqual(reply, {'msg_type': 'text', 'content': '默认回复'})

    def test_on_text_no_match_no_default(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'wechat.auto_reply_enabled', 'False')
        reply = self._call(
            self._controller()._on_text,
            self.company.id, self.company, self._msg_data(Content='别的话'))
        self.assertIsNone(reply)

    def test_on_subscribe_creates_user_and_replies(self):
        self.env['wechat.subscribe.reply'].create({
            'company_id': self.company.id,
            'reply_content': '欢迎',
        })
        controller = self._controller()
        event = {
            'MsgType': 'event', 'Event': 'subscribe',
            'FromUserName': 'openid-New', 'ToUserName': 'gh_official',
            'EventKey': 'qrscene_9',
        }
        with self._patched_fetch_user():
            reply = self._call(
                controller._on_subscribe, self.company.id, self.company, event)
        user = self.env['wechat.user'].search([
            ('wechat_openid', '=', 'openid-New')])
        self.assertTrue(user)
        self.assertEqual(user.qr_scene, '9')
        self.assertEqual(reply, {'msg_type': 'text', 'content': '欢迎'})

    def test_on_unsubscribe(self):
        user = self.env['wechat.user'].create({
            'company_id': self.company.id,
            'wechat_openid': 'openid-A',
            'wechat_subscribe': 'subscribed',
        })
        controller = self._controller()
        self._call(controller._on_unsubscribe, self.company.id, self.company, {
            'MsgType': 'event', 'Event': 'unsubscribe',
            'FromUserName': 'openid-A',
        })
        self.assertEqual(user.wechat_subscribe, 'unsubscribed')

    def test_on_menu_click(self):
        self.env['wechat.message.rule'].create({
            'name': 'cs',
            'company_id': self.company.id,
            'keyword': 'contact_cs',
            'match_type': 'exact',
            'reply_type': 'text',
            'reply_content': '客服微信: x',
        })
        reply = self._call(self._controller()._on_menu_click, self.company.id, self.company, {
            'MsgType': 'event', 'Event': 'CLICK',
            'FromUserName': 'openid-A', 'EventKey': 'contact_cs',
        })
        self.assertEqual(reply['content'], '客服微信: x')

    def _patched_fetch_user(self):
        from unittest.mock import patch
        return patch.object(type(self.env['wechat.user']),
                            '_fetch_user_info', return_value=None)
