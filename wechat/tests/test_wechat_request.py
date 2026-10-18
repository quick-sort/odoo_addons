from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import WechatTransactionCase


@tagged('post_install', '-at_install')
class TestWechatRequest(WechatTransactionCase):

    def _request(self):
        return self.env['wechat.request']

    def test_missing_credentials_raises(self):
        bare = self.env['res.company'].create({'name': 'No Creds Co'})
        with self.assertRaises(UserError):
            self._request()._get_access_token(bare.id)

    def test_token_cached_in_config_parameter(self):
        with patch('odoo.addons.wechat.models.wechat_request.WeChatClient') as mock_client:
            mock_client.return_value.token.fetch_access_token.return_value = {
                'access_token': 'TOKEN-1', 'expires_in': 7200}
            token = self._request()._get_access_token(self.company.id)
        self.assertEqual(token, 'TOKEN-1')
        self.assertEqual(self.company.wechat_access_token, 'TOKEN-1')

        # Second call must hit the cache, not WeChatClient
        token2 = self._request()._get_access_token(self.company.id)
        self.assertEqual(token2, 'TOKEN-1')

    def test_invalidate_forces_refetch(self):
        with patch('odoo.addons.wechat.models.wechat_request.WeChatClient') as mock_client:
            mock_client.return_value.token.fetch_access_token.return_value = {
                'access_token': 'TOKEN-1', 'expires_in': 7200}
            self._request()._get_access_token(self.company.id)

            self._request()._invalidate_token(self.company.id)
            mock_client.return_value.token.fetch_access_token.return_value = {
                'access_token': 'TOKEN-2', 'expires_in': 7200}
            token = self._request()._get_access_token(self.company.id)
        self.assertEqual(token, 'TOKEN-2')
        self.assertEqual(mock_client.return_value.token
                         .fetch_access_token.call_count, 2)

    def test_wechat_get_retries_on_expired_token(self):
        with patch('odoo.addons.wechat.models.wechat_request.WeChatClient') as mock_client, \
                patch('odoo.addons.wechat.models.wechat_request.requests') as mock_requests:
            mock_client.return_value.token.fetch_access_token.side_effect = [
                {'access_token': 'OLD', 'expires_in': 7200},
                {'access_token': 'NEW', 'expires_in': 7200},
            ]

            resp_expired = MagicMock()
            resp_expired.json.return_value = {'errcode': 40001,
                                              'errmsg': 'expired'}
            resp_ok = MagicMock()
            resp_ok.json.return_value = {'errcode': 0, 'data': 'ok'}
            mock_requests.request.side_effect = [resp_expired, resp_ok]

            result = self._request().wechat_get(self.company.id, '/user/get')

        self.assertEqual(result, {'errcode': 0, 'data': 'ok'})
        self.assertEqual(mock_requests.request.call_count, 2)
        # Second call must carry the refreshed token
        second_url = mock_requests.request.call_args_list[1][1].get(
            'params') or str(mock_requests.request.call_args_list[1])
        self.assertIn('NEW', str(second_url) + str(
            mock_requests.request.call_args_list[1]))
