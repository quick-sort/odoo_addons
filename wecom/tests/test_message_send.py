# -*- coding: utf-8 -*-
import base64
from unittest import mock

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestWecomMessageSend(TransactionCase):
    """图文消息多篇发送与按 8 篇分批，wechatpy 全部 mock，离线可跑。"""

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
        client = mock.MagicMock()
        client.message.send_articles.return_value = {'errcode': 0, 'errmsg': 'ok'}
        client.message.send_mp_articles.return_value = {'errcode': 0, 'errmsg': 'ok'}
        client.message.send_text_card.return_value = {'errcode': 0, 'errmsg': 'ok'}
        client.media.upload.return_value = {'media_id': 'mock_media'}
        client.media.upload_img.return_value = {'url': 'https://img.mock/1'}
        patcher = mock.patch.object(type(self.app), 'get_wecom_client', return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client

    def _make_message(self, msg_type, articles=None, **vals):
        base = {
            'app_id': self.app.id,
            'name': 'Digest',
            'msg_type': msg_type,
            'touser': 'user1',
        }
        base.update(vals)
        if articles is not None:
            base['article_ids'] = [(0, 0, a) for a in articles]
        return self.env['wecom.app.message'].create(base)

    # ------------------------------------------------------------------
    # 分批与发送
    # ------------------------------------------------------------------

    def test_news_batches_by_8(self):
        client = self._mock_client()
        articles = [
            {'title': f'A{i}', 'url': f'https://x/{i}', 'image_url': f'https://i/{i}'}
            for i in range(10)
        ]
        msg = self._make_message('news', articles)
        msg.send()

        self.assertEqual(client.message.send_articles.call_count, 2)
        batches = [c.args[2] for c in client.message.send_articles.call_args_list]
        self.assertEqual([len(b) for b in batches], [8, 2])
        self.assertEqual(msg.state, 'sent')

    def test_single_news_sends_once(self):
        client = self._mock_client()
        msg = self._make_message('news', [{'title': 'A', 'url': 'https://x', 'image_url': 'https://i'}])
        msg.send()
        self.assertEqual(client.message.send_articles.call_count, 1)
        self.assertEqual(msg.state, 'sent')

    def test_textcard_uses_send_text_card(self):
        client = self._mock_client()
        msg = self._make_message('textcard', url='https://x')
        msg.send()
        client.message.send_text_card.assert_called_once()
        client.message.send_articles.assert_not_called()

    def test_mpnews_uploads_thumb_and_batches(self):
        client = self._mock_client()
        thumb = base64.b64encode(b'fake').decode()
        articles = [
            {'title': 'A', 'content': '<p>1</p>', 'thumb_image': thumb},
            {'title': 'B', 'content': '<p>2</p>', 'thumb_image': thumb},
        ]
        msg = self._make_message('mpnews', articles)
        msg.send()

        self.assertEqual(client.media.upload.call_count, 2)
        self.assertEqual(client.message.send_mp_articles.call_count, 1)

    def test_news_requires_articles(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self._make_message('news', articles=[])

    def test_send_message_creates_articles(self):
        self._mock_client()
        msg = self.app.send_message(
            'Digest', msg_type='news',
            articles=[
                {'title': 'A', 'url': 'https://x/1', 'image_url': 'https://i/1'},
                {'title': 'B', 'url': 'https://x/2', 'image_url': 'https://i/2'},
            ],
            touser='user1',
        )
        self.assertEqual(len(msg.article_ids), 2)
        self.assertEqual(msg.article_ids.mapped('title'), ['A', 'B'])
        self.assertEqual(msg.state, 'sent')
