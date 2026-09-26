# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest import mock

from odoo import api, fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from wechatpy.exceptions import WeChatClientException


@tagged('post_install', '-at_install')
class TestWecomMessageRecall(TransactionCase):
    """msgid 记录与消息撤回：AC2/AC3，wechatpy 全 mock，离线可跑。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = cls.env['wecom.app'].create({
            'name': 'Test App',
            'wecom_corp_id': 'corp',
            'wecom_agent_id': '1000001',
            'wecom_secret': 'secret',
        })

    def _mock_client(self):
        """
        mock wechatpy client：发送类接口带 msgid（每批一个），media 上传桩，
        client.post 模拟撤回接口成功。
        """
        client = mock.MagicMock()
        client.message.send_text_card.return_value = {'errcode': 0, 'errmsg': 'ok', 'msgid': 'MSG_CARD'}
        client.message.send_articles.side_effect = [
            {'errcode': 0, 'errmsg': 'ok', 'msgid': 'MSG_1'},
            {'errcode': 0, 'errmsg': 'ok', 'msgid': 'MSG_2'},
        ]
        client.message.send_mp_articles.return_value = {'errcode': 0, 'errmsg': 'ok', 'msgid': 'MSG_MP'}
        client.media.upload.return_value = {'media_id': 'mock_media'}
        client.media.upload_img.return_value = {'url': 'https://img.mock/1'}
        client.post.return_value = {'errcode': 0, 'errmsg': 'ok'}
        patcher = mock.patch.object(type(self.app), 'get_wecom_client', return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client

    def _send_textcard(self, raise_exception=True):
        msg = self.env['wecom.app.message'].create({
            'app_id': self.app.id,
            'name': 'Card',
            'msg_type': 'textcard',
            'url': 'https://x',
            'touser': 'user1',
        })
        msg.send(raise_exception=raise_exception)
        return msg

    def _send_news_10(self):
        msg = self.env['wecom.app.message'].create({
            'app_id': self.app.id,
            'name': 'News',
            'msg_type': 'news',
            'touser': 'user1',
            'article_ids': [(0, 0, {
                'title': f'A{i}', 'url': f'https://x/{i}', 'image_url': f'https://i/{i}',
            }) for i in range(10)],
        })
        msg.send()
        return msg

    # ------------------------------------------------------------------
    # AC2 msgid 记录
    # ------------------------------------------------------------------

    def test_textcard_records_msgid(self):
        """AC2.1 单条发送后 msgid 字段等于响应里的 msgid。"""
        self._mock_client()
        msg = self._send_textcard()
        self.assertEqual(msg.state, 'sent')
        self.assertEqual(msg.msgid, 'MSG_CARD')

    def test_multi_batch_records_all_msgids(self):
        """AC2.2 多批发送记录每一批的 msgid（每行一个）。"""
        self._mock_client()
        msg = self._send_news_10()
        self.assertEqual(msg.msgid, 'MSG_1\nMSG_2')

    def test_send_failure_leaves_msgid_empty(self):
        """AC2.3 发送失败时 msgid 为空。"""
        client = self._mock_client()
        client.message.send_text_card.side_effect = WeChatClientException(81013, 'all invalid')
        msg = self._send_textcard(raise_exception=False)
        self.assertEqual(msg.state, 'failed')
        self.assertFalse(msg.msgid)

    # ------------------------------------------------------------------
    # AC3 消息撤回
    # ------------------------------------------------------------------

    def test_recall_sent_message(self):
        """AC3.1 已发送且24h内：逐 msgid 调 message/recall，状态变为已撤回。"""
        client = self._mock_client()
        msg = self._send_textcard()
        msg.action_recall()

        client.post.assert_called_once_with('message/recall', data={'msgid': 'MSG_CARD'})
        self.assertEqual(msg.state, 'recalled')
        self.assertTrue(msg.recall_date)
        self.assertIn('撤回成功', msg.result)

    def test_recall_multi_batch_calls_per_msgid(self):
        """AC3.1（多批）：10 篇分两批，两个 msgid 各撤回一次。"""
        client = self._mock_client()
        msg = self._send_news_10()
        msg.action_recall()

        self.assertEqual(client.post.call_count, 2)
        recalled = [c.kwargs['data']['msgid'] for c in client.post.call_args_list]
        self.assertEqual(recalled, ['MSG_1', 'MSG_2'])
        self.assertEqual(msg.state, 'recalled')

    def test_recall_rejects_after_24h(self):
        """AC3.2 超过 24 小时：报错且不调撤回接口。"""
        client = self._mock_client()
        msg = self._send_textcard()
        msg.write({'send_date': fields.Datetime.now() - timedelta(hours=25)})

        with self.assertRaises(UserError):
            msg.action_recall()
        client.post.assert_not_called()
        self.assertEqual(msg.state, 'sent')

    def test_recall_rejects_draft(self):
        """AC3.4 草稿点撤回：报错且不调接口。"""
        client = self._mock_client()
        msg = self.env['wecom.app.message'].create({
            'app_id': self.app.id,
            'name': 'Draft',
            'msg_type': 'textcard',
            'url': 'https://x',
            'touser': 'user1',
        })

        with self.assertRaises(UserError):
            msg.action_recall()
        client.post.assert_not_called()


@tagged('post_install', '-at_install')
class TestWecomRecallFailureBookkeeping(TransactionCase):
    """
    AC3.3 撤回接口报错：失败信息经独立游标落库，在 UserError 触发的事务回滚
    之后仍然可见（生产语义：Odoo 请求异常即回滚，当前事务里的写入留不下来；
    Odoo 测试的 assertRaises 以同样方式回滚）。

    TransactionCase 的类级数据也不提交，测试事务里的行对独立游标不可见，
    因此这里用独立游标创建并发送消息（真实提交，等价于生产中已落库的记录）；
    独立游标的写入是真实提交，结束时同样经独立游标清理，避免泄漏到其他用例。
    """

    def test_recall_api_error_keeps_state_and_result(self):
        client = mock.MagicMock()
        client.message.send_text_card.return_value = {
            'errcode': 0, 'errmsg': 'ok', 'msgid': 'MSG_CARD'}
        client.post.side_effect = WeChatClientException(45009, 'api limited')
        patcher = mock.patch.object(
            type(self.env['wecom.app']), 'get_wecom_client', return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)

        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, self.env.context)
            app = env['wecom.app'].create({
                'name': 'Recall App',
                'wecom_corp_id': 'corp',
                'wecom_agent_id': '1000001',
                'wecom_secret': 'secret',
            })
            message = env['wecom.app.message'].create({
                'app_id': app.id,
                'name': 'Card',
                'msg_type': 'textcard',
                'url': 'https://x',
                'touser': 'user1',
            })
            message.send()
            app_id, message_id = app.id, message.id

        message = self.env['wecom.app.message'].browse(message_id)
        with self.assertRaises(UserError):
            message.action_recall()

        self.assertEqual(message.state, 'sent')
        self.assertIn('45009', message.result)
        self.assertIn('撤回失败', message.result)

        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, self.env.context)
            message = env['wecom.app.message'].browse(message_id)
            if message.exists():
                message.unlink()
            app = env['wecom.app'].browse(app_id)
            if app.exists():
                app.unlink()
