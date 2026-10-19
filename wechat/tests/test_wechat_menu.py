import psycopg2

import json
from unittest.mock import patch

from odoo.tests import tagged

from .common import WechatTransactionCase


@tagged('post_install', '-at_install')
class TestWechatMenu(WechatTransactionCase):

    def _create_menu(self):
        menu = self.env['wechat.menu'].create({
            'name': '主菜单',
            'company_id': self.company.id,
            'menu_buttons': [
                (0, 0, {
                    'name': '关于我们',
                    'button_type': 'view',
                    'url': 'https://example.com/about',
                    'sequence': 10,
                }),
                (0, 0, {
                    'name': '服务',
                    'sequence': 20,
                    'sub_buttons': [
                        (0, 0, {
                            'name': '联系客服',
                            'button_type': 'click',
                            'key': 'contact_cs',
                            'sequence': 1,
                        }),
                        (0, 0, {
                            'name': '小程序',
                            'button_type': 'miniprogram',
                            'appid': 'wx_mini',
                            'pagepath': 'pages/index',
                            'url': 'https://example.com/m',
                            'sequence': 2,
                        }),
                    ],
                }),
            ],
        })
        return menu

    def test_menu_json_structure(self):
        menu = self._create_menu()
        data = json.loads(menu.menu_json)
        buttons = data['button']
        self.assertEqual(len(buttons), 2)

        self.assertEqual(buttons[0]['type'], 'view')
        self.assertEqual(buttons[0]['name'], '关于我们')
        self.assertEqual(buttons[0]['url'], 'https://example.com/about')

        # Parent with sub-buttons must NOT carry a type
        parent = buttons[1]
        self.assertNotIn('type', parent)
        self.assertEqual(len(parent['sub_button']), 2)
        click_btn = parent['sub_button'][0]
        self.assertEqual(click_btn['type'], 'click')
        self.assertEqual(click_btn['key'], 'contact_cs')
        mini = parent['sub_button'][1]
        self.assertEqual(mini['type'], 'miniprogram')
        self.assertEqual(mini['appid'], 'wx_mini')

    def test_menu_unique_per_company(self):
        self._create_menu()
        with self.assertRaises(psycopg2.IntegrityError):
            self.env['wechat.menu'].create({
                'name': '另一个菜单',
                'company_id': self.company.id,
            })

    def test_action_sync_success(self):
        menu = self._create_menu()
        with patch.object(type(self.env['wechat.request']), 'wechat_post',
                          return_value={'errcode': 0}) as mock_post:
            menu.action_sync()
        self.assertEqual(menu.sync_status, 'synced')
        self.assertTrue(menu.last_sync_time)
        self.assertFalse(menu.last_error)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], self.company.id)
        self.assertIn('/menu/create', args[1])
        self.assertEqual(kwargs['json']['button'][0]['name'], '关于我们')

    def test_action_sync_failure(self):
        menu = self._create_menu()
        with patch.object(type(self.env['wechat.request']), 'wechat_post',
                          return_value={'errcode': 40018,
                                        'errmsg': 'invalid button'}):
            menu.action_sync()
        self.assertEqual(menu.sync_status, 'failed')
        self.assertEqual(menu.last_error, 'invalid button')

    def test_action_sync_usererror(self):
        from odoo.exceptions import UserError
        menu = self._create_menu()
        with patch.object(type(self.env['wechat.request']), 'wechat_post',
                          side_effect=UserError('未配置凭证')):
            menu.action_sync()
        self.assertEqual(menu.sync_status, 'failed')
        self.assertIn('凭证', menu.last_error)
