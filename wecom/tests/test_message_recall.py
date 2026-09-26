# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest import mock

from odoo import fields
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

    def _mock_client(self, recall_error=None):
        """
        mock wechatpy client：发送类接口带 msgid（每批一个），media 上传桩，
        client.post 模拟撤回接口（默认成功，可注入异常）。
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
        if recall_error is not None:
            client.post.side_effect = recall_error
        else:
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

    def test_recall_reports_api_error(self):
        """AC3.3 撤回接口报错：状态不变，错误写入 result。"""
        self._mock_client(recall_error=WeChatClientException(45009, 'api limited'))
        msg = self._send_textcard()

        with self.assertRaises(UserError):
            msg.action_recall()
        self.assertEqual(msg.state, 'sent')
        self.assertIn('45009', msg.result)

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
