import psycopg2

from unittest.mock import patch

from odoo.tests import tagged

from .common import WechatTransactionCase


@tagged('post_install', '-at_install')
class TestTemplateMessage(WechatTransactionCase):

    def _create_template(self):
        return self.env['wechat.template.message'].create({
            'name': '订单通知',
            'code': 'order_confirm',
            'template_id': 'TPL-001',
            'company_id': self.company.id,
            'data_schema': '{"first": {"value": "hi"}}',
        })

    def test_send_success(self):
        template = self._create_template()
        with patch.object(type(self.env['wechat.request']), 'wechat_post',
                          return_value={'errcode': 0, 'msgid': 'M1'}) as mp:
            result = template.send_template_message(
                'openid-A', {'first': {'value': 'hi'}})
        self.assertTrue(result)
        self.assertEqual(template.send_count, 1)
        self.assertTrue(template.last_send_time)
        args, kwargs = mp.call_args
        self.assertIn('/message/template/send', args[1])
        self.assertEqual(kwargs['json']['touser'], 'openid-A')
        self.assertEqual(kwargs['json']['template_id'], 'TPL-001')

    def test_send_failure_no_stat(self):
        template = self._create_template()
        with patch.object(type(self.env['wechat.request']), 'wechat_post',
                          return_value={'errcode': 40003, 'errmsg': 'bad tpl'}):
            result = template.send_template_message(
                'openid-A', {})
        self.assertFalse(result)
        self.assertEqual(template.send_count, 0)

    def test_get_data_schema_dict(self):
        template = self._create_template()
        self.assertEqual(
            template.get_data_schema_dict(), {'first': {'value': 'hi'}})
        template.data_schema = 'not-json{'
        self.assertEqual(template.get_data_schema_dict(), {})


@tagged('post_install', '-at_install')
class TestMassMessage(WechatTransactionCase):

    def _create_mass(self, **overrides):
        vals = {
            'name': '活动通知',
            'company_id': self.company.id,
            'msg_type': 'text',
            'content': '全场五折',
        }
        vals.update(overrides)
        return self.env['wechat.mass.message'].create(vals)

    def test_prepare_text_to_all(self):
        mass = self._create_mass()
        body = mass._prepare_message()
        self.assertEqual(body['msgtype'], 'text')
        self.assertEqual(body['text']['content'], '全场五折')
        self.assertEqual(body['filter'], {'is_to_all': True})

    def test_prepare_news_with_tag(self):
        tag = self.env['wechat.user.tag'].create({
            'name': 'VIP', 'company_id': self.company.id,
            'wechat_tag_id': '101'})
        mass = self._create_mass(msg_type='news', media_id='NEWS1',
                                 tag_id=tag.id)
        body = mass._prepare_message()
        self.assertEqual(body['mpnews']['media_id'], 'NEWS1')
        self.assertEqual(body['filter'],
                         {'is_to_all': False, 'tag_id': '101'})

    def test_do_send_success(self):
        mass = self._create_mass()
        with patch.object(type(self.env['wechat.request']), 'wechat_post',
                          return_value={'errcode': 0, 'msg_id': 'MASS1'}):
            mass.action_send()
        self.assertEqual(mass.state, 'sent')
        self.assertEqual(mass.msg_id, 'MASS1')
        self.assertTrue(mass.sent_date)

    def test_do_send_failure_and_retry(self):
        mass = self._create_mass()
        with patch.object(type(self.env['wechat.request']), 'wechat_post',
                          return_value={'errcode': 45009, 'errmsg': 'limit'}):
            mass.action_send()
        self.assertEqual(mass.state, 'failed')
        self.assertEqual(mass.error_msg, 'limit')

        with patch.object(type(self.env['wechat.request']), 'wechat_post',
                          return_value={'errcode': 0, 'msg_id': 'MASS2'}):
            mass.action_retry()
        self.assertEqual(mass.state, 'sent')

    def test_name_unique_per_company(self):
        self._create_mass()
        with self.assertRaises(psycopg2.IntegrityError):
            self._create_mass()
