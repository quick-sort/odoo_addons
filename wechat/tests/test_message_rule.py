import psycopg2

from odoo.tests import tagged

from .common import WechatTransactionCase


@tagged('post_install', '-at_install')
class TestMessageRule(WechatTransactionCase):

    def _create_rule(self, **overrides):
        vals = {
            'name': 'rule',
            'company_id': self.company.id,
            'keyword': '价格',
            'match_type': 'exact',
            'reply_type': 'text',
            'reply_content': '请查看价格页',
            'sequence': 10,
        }
        vals.update(overrides)
        return self.env['wechat.message.rule'].create(vals)

    def test_exact_match(self):
        rule = self._create_rule()
        matched = self.env['wechat.message.rule'].match_keyword(
            self.company.id, '价格')
        self.assertEqual(matched, rule)
        self.assertEqual(matched.reply_count, 1)
        self.assertTrue(matched.last_trigger_time)

    def test_exact_no_match_on_superstring(self):
        self._create_rule(keyword='价格')
        matched = self.env['wechat.message.rule'].match_keyword(
            self.company.id, '价格多少')
        self.assertFalse(matched)

    def test_fuzzy_match(self):
        self._create_rule(keyword='价格', match_type='fuzzy')
        matched = self.env['wechat.message.rule'].match_keyword(
            self.company.id, '请问价格多少')
        self.assertTrue(matched)

    def test_regex_match_and_invalid_pattern(self):
        self._create_rule(keyword=r'^\d+$', match_type='regex')
        matched = self.env['wechat.message.rule'].match_keyword(
            self.company.id, '12345')
        self.assertTrue(matched)
        # Invalid regex must not raise, just never match
        self._create_rule(keyword='[invalid', match_type='regex', sequence=5)
        matched = self.env['wechat.message.rule'].match_keyword(
            self.company.id, '12345')
        self.assertTrue(matched)  # still matched by the valid rule
        matched = self.env['wechat.message.rule'].match_keyword(
            self.company.id, 'no-digit-text')
        self.assertFalse(matched)

    def test_sequence_priority(self):
        low = self._create_rule(keyword='帮', match_type='fuzzy', sequence=50,
                                reply_content='低优先')
        high = self._create_rule(keyword='帮助', match_type='exact',
                                 sequence=1, reply_content='高优先')
        matched = self.env['wechat.message.rule'].match_keyword(
            self.company.id, '帮助')
        self.assertEqual(matched, high)

    def test_inactive_rule_skipped(self):
        self._create_rule(active=False)
        matched = self.env['wechat.message.rule'].match_keyword(
            self.company.id, '价格')
        self.assertFalse(matched)

    def test_company_isolation(self):
        other = self.env['res.company'].create({'name': 'Other Co'})
        self._create_rule()
        matched = self.env['wechat.message.rule'].match_keyword(
            other.id, '价格')
        self.assertFalse(matched)

    def test_reply_data_types(self):
        rule = self._create_rule()
        self.assertEqual(rule.get_reply_data(),
                         {'msg_type': 'text', 'content': '请查看价格页'})

        rule = self._create_rule(
            keyword='图', reply_type='image', media_id='MEDIA1')
        self.assertEqual(rule.get_reply_data(),
                         {'msg_type': 'image', 'media_id': 'MEDIA1'})

        rule = self._create_rule(
            keyword='视频', reply_type='video', media_id='MV1',
            title='T', description='D')
        data = rule.get_reply_data()
        self.assertEqual(data['msg_type'], 'video')
        self.assertEqual(data['media_id'], 'MV1')
        self.assertEqual(data['title'], 'T')

        rule = self._create_rule(
            keyword='音', reply_type='music', title='M', url='http://mu',
            thumb_media_id='TH1')
        data = rule.get_reply_data()
        self.assertEqual(data['msg_type'], 'music')
        self.assertEqual(data['music_url'], 'http://mu')
        self.assertEqual(data['thumb_media_id'], 'TH1')

        rule = self._create_rule(
            keyword='图文', reply_type='news', title='N', url='http://n',
            media_id='PIC')
        data = rule.get_reply_data()
        self.assertEqual(data['msg_type'], 'news')
        self.assertEqual(data['articles'][0]['title'], 'N')

    def test_keyword_unique_per_company_and_match_type(self):
        self._create_rule(keyword='dup')
        with self.assertRaises(psycopg2.IntegrityError):
            self._create_rule(keyword='dup')
        # Same keyword but different match type is fine
        self._create_rule(keyword='dup', match_type='fuzzy')

    def test_default_and_subscribe_reply(self):
        Default = self.env['wechat.auto.reply.default']
        default = Default.create({
            'company_id': self.company.id,
            'reply_content': '默认回复内容',
        })
        self.assertEqual(
            default.get_reply_data(),
            {'msg_type': 'text', 'content': '默认回复内容'})

        sub = self.env['wechat.subscribe.reply'].create({
            'company_id': self.company.id,
            'reply_content': '欢迎关注',
        })
        self.assertEqual(
            sub.get_reply_data(),
            {'msg_type': 'text', 'content': '欢迎关注'})

        with self.assertRaises(psycopg2.IntegrityError):
            Default.create({'company_id': self.company.id})
        with self.assertRaises(psycopg2.IntegrityError):
            self.env['wechat.subscribe.reply'].create(
                {'company_id': self.company.id})
