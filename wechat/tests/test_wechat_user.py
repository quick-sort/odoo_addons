import psycopg2

from unittest.mock import patch

from odoo.tests import tagged

from .common import WechatTransactionCase


@tagged('post_install', '-at_install')
class TestWechatUser(WechatTransactionCase):

    def _subscribe_event(self, openid='openid-A', event_key=''):
        return {
            'FromUserName': openid,
            'ToUserName': 'gh_official',
            'Event': 'subscribe',
            'EventKey': event_key,
        }

    def test_subscribe_creates_user(self):
        with patch.object(
                type(self.env['wechat.user']), '_fetch_user_info',
                return_value={'nickname': '小明', 'headimgurl': 'http://img',
                              'language': 'zh_CN', 'groupid': 2}):
            user = self.env['wechat.user'].create_from_subscribe(
                self.company.id, self._subscribe_event())
        self.assertTrue(user)
        self.assertEqual(user.wechat_openid, 'openid-A')
        self.assertEqual(user.wechat_subscribe, 'subscribed')
        self.assertTrue(user.wechat_subscribe_time)
        self.assertEqual(user.wechat_nickname, '小明')
        self.assertEqual(user.group_id, '2')

    def test_subscribe_with_qr_scene(self):
        event = self._subscribe_event(event_key='qrscene_42')
        with patch.object(type(self.env['wechat.user']),
                          '_fetch_user_info', return_value=None):
            user = self.env['wechat.user'].create_from_subscribe(
                self.company.id, event)
        self.assertEqual(user.qr_scene, '42')
        self.assertFalse(user.qr_scene_str)

        event = self._subscribe_event(openid='openid-B',
                                      event_key='qrscene_store_beijing')
        with patch.object(type(self.env['wechat.user']),
                          '_fetch_user_info', return_value=None):
            user_b = self.env['wechat.user'].create_from_subscribe(
                self.company.id, event)
        self.assertEqual(user_b.qr_scene_str, 'store_beijing')

    def test_resubscribe_updates_not_duplicates(self):
        with patch.object(type(self.env['wechat.user']),
                          '_fetch_user_info', return_value=None):
            user = self.env['wechat.user'].create_from_subscribe(
                self.company.id, self._subscribe_event())
            user.update_from_unsubscribe()
            self.assertEqual(user.wechat_subscribe, 'unsubscribed')

            user2 = self.env['wechat.user'].create_from_subscribe(
                self.company.id, self._subscribe_event())
        self.assertEqual(user2, user)
        self.assertEqual(user2.wechat_subscribe, 'subscribed')
        count = self.env['wechat.user'].search_count(
            [('wechat_openid', '=', 'openid-A')])
        self.assertEqual(count, 1)

    def test_openid_unique_per_company(self):
        self.env['wechat.user'].create({
            'company_id': self.company.id,
            'wechat_openid': 'openid-A',
        })
        with self.assertRaises(psycopg2.IntegrityError):
            self.env['wechat.user'].create({
                'company_id': self.company.id,
                'wechat_openid': 'openid-A',
            })
        # Same openid in another company is fine
        other = self.env['res.company'].create({'name': 'Other Co'})
        self.env['wechat.user'].create({
            'company_id': other.id,
            'wechat_openid': 'openid-A',
        })

    def test_get_by_openid(self):
        user = self.env['wechat.user'].create({
            'company_id': self.company.id,
            'wechat_openid': 'openid-A',
            'wechat_nickname': '小明',
        })
        found = self.env['wechat.user'].get_by_openid('openid-A')
        self.assertEqual(found, user)
        self.assertFalse(self.env['wechat.user'].get_by_openid('nope'))

    def test_user_tags(self):
        self.env['wechat.user.tag'].create({
            'name': 'VIP', 'company_id': self.company.id})
        with self.assertRaises(psycopg2.IntegrityError):
            self.env['wechat.user.tag'].create({
                'name': 'VIP', 'company_id': self.company.id})

        user = self.env['wechat.user'].create({
            'company_id': self.company.id,
            'wechat_openid': 'openid-A',
            'tag_ids': [(6, 0, self.env['wechat.user.tag'].search(
                [('name', '=', 'VIP')]).ids)],
        })
        self.assertEqual(len(user.tag_ids), 1)
        self.assertEqual(user.tag_ids.user_count, 1)

    def test_sync_wechat_user_info(self):
        user = self.env['wechat.user'].create({
            'company_id': self.company.id,
            'wechat_openid': 'openid-A',
        })
        user.sync_wechat_user_info({
            'openid': 'openid-A',
            'nickname': '新昵称',
            'subscribe': 1,
            'remark': '老客户',
        })
        self.assertEqual(user.wechat_nickname, '新昵称')
        self.assertEqual(user.wechat_subscribe, 'subscribed')
        self.assertEqual(user.wechat_remark, '老客户')
