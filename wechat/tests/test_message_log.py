import psycopg2

from datetime import datetime, timedelta


from odoo.tests import tagged

from .common import WechatTransactionCase


@tagged('post_install', '-at_install')
class TestMessageLog(WechatTransactionCase):

    def test_create_inbound_log(self):
        log = self.env['wechat.message.log'].create(self._log_vals())
        self.assertEqual(log.from_user, 'openid-A')
        self.assertEqual(log.msg_type, 'text')
        self.assertEqual(log.content, 'hello')
        self.assertEqual(log.direction, 'inbound')
        self.assertTrue(log.name)

    def test_msgid_unique_per_company(self):
        self.env['wechat.message.log'].create(self._log_vals(msgid='dup'))
        with self.assertRaises(psycopg2.IntegrityError):
            self.env['wechat.message.log'].create(self._log_vals(msgid='dup'))

    def test_msgid_same_in_other_company_allowed(self):
        other = self.env['res.company'].create({'name': 'Other Co'})
        self.env['wechat.message.log'].create(self._log_vals(msgid='dup'))
        log = self.env['wechat.message.log'].create(
            self._log_vals(msgid='dup', company_id=other.id))
        self.assertEqual(log.company_id, other)

    def test_user_link_on_log(self):
        user = self.env['wechat.user'].create({
            'company_id': self.company.id,
            'wechat_openid': 'openid-A',
        })
        log = self.env['wechat.message.log'].create(
            self._log_vals(user_id=user.id))
        self.assertEqual(log.user_id, user)
        self.assertEqual(user.message_count, 1)

    def test_cleanup_old_messages(self):
        old = self.env['wechat.message.log'].create(
            self._log_vals(msgid='old'))
        self.env.cr.execute(
            'UPDATE wechat_message_log SET create_date = %s WHERE id = %s',
            (datetime.now() - timedelta(days=200), old.id))

        fresh = self.env['wechat.message.log'].create(
            self._log_vals(msgid='fresh'))

        deleted = self.env['wechat.message.cron'].run_cleanup()
        self.assertEqual(deleted, 1)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
