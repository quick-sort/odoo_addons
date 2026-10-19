import logging
from datetime import datetime, timedelta

import requests
from odoo import _, api, models
from odoo.exceptions import UserError

from ..utils import WeChatClient, WeChatClientException

_logger = logging.getLogger(__name__)

# WeChat API base - fixed host, no user-supplied parts involved
WECHAT_API_BASE = 'https://api.weixin.qq.com/cgi-bin'

TOKEN_EXPIRED_CODES = (40001, 42001)


class WechatRequest(models.AbstractModel):
    """Unified WeChat MP API access: access-token lifecycle + retry on expiry."""
    _name = 'wechat.request'
    _description = 'WeChat API Request'

    @api.model
    def _get_config_param(self, key, default=None):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    @api.model
    def _set_config_param(self, key, value):
        self.env['ir.config_parameter'].sudo().set_param(key, value)

    @api.model
    def _get_company(self, company_id):
        company_id = int(company_id)
        company = self.env['res.company'].sudo().browse(company_id)
        if not company.exists():
            raise UserError(_('公司 %s 不存在') % company_id)
        return company

    @api.model
    def _get_access_token(self, company_id):
        """Return a valid access token, fetching and caching a fresh one if needed."""
        company = self._get_company(company_id)
        if not company.wechat_app_id or not company.wechat_app_secret:
            raise UserError(
                _('公司 %s 的AppID或AppSecret未配置') % company.name)

        cache_key = f'wechat.access_token.{company.id}'
        cached_token = self._get_config_param(cache_key)
        if cached_token:
            expire_time = self._get_config_param(f'{cache_key}.expire')
            if expire_time:
                try:
                    if datetime.now() < datetime.fromisoformat(expire_time):
                        return cached_token
                except (ValueError, TypeError):
                    pass

        _logger.info('Fetching new access token for company %s', company.id)
        try:
            client = WeChatClient(
                company.wechat_app_id, company.wechat_app_secret)
            token_result = client.token.fetch_access_token()
        except UserError:
            raise
        except WeChatClientException as e:
            _logger.error('Failed to get access token: %s', e)
            raise UserError(_('获取Access Token失败: %s') % e) from e

        token = token_result.get('access_token')
        if not token:
            raise UserError(_('获取Access Token失败: 无效的响应'))

        expires_in = int(token_result.get('expires_in', 7200))
        # 5-minute safety buffer before WeChat-side expiry
        expire_dt = datetime.now() + timedelta(seconds=max(expires_in - 300, 60))

        self._set_config_param(cache_key, token)
        self._set_config_param(f'{cache_key}.expire', expire_dt.isoformat())
        company.write({
            'wechat_access_token': token,
            'wechat_token_expire': expire_dt,
        })
        return token

    @api.model
    def _invalidate_token(self, company_id):
        cache_key = f'wechat.access_token.{int(company_id)}'
        self._set_config_param(cache_key, False)
        self._set_config_param(f'{cache_key}.expire', False)
        self._get_company(company_id).write({
            'wechat_access_token': False,
            'wechat_token_expire': False,
        })

    @api.model
    def _extract_error_code(self, exception):
        if hasattr(exception, 'errcode'):
            return exception.errcode
        if hasattr(exception, 'error_code'):
            return exception.error_code
        if isinstance(exception, dict):
            return exception.get('errcode')
        return None

    @api.model
    def wechat_get(self, company_id, url, params=None, **kwargs):
        return self._wechat_request(
            company_id, 'GET', url, params=params, **kwargs)

    @api.model
    def wechat_post(self, company_id, url, data=None, json=None, **kwargs):
        return self._wechat_request(
            company_id, 'POST', url, data=data, json=json, **kwargs)

    @api.model
    def _wechat_request(self, company_id, method, url, *, params=None,
                        data=None, json=None, timeout=30, **kwargs):
        """Single implementation for all HTTP verbs, with one retry on token expiry."""
        if not url.startswith('http'):
            url = f'{WECHAT_API_BASE}/{url.lstrip("/")}'

        token = self._get_access_token(company_id)
        separator = '&' if '?' in url else '?'
        result = None
        for attempt in range(2):
            full_url = f'{url}{separator}access_token={token}'
            try:
                response = requests.request(
                    method, full_url, params=params, data=data, json=json,
                    timeout=timeout, **kwargs)
                result = response.json()
            except requests.RequestException as e:
                _logger.error('WeChat %s request failed: %s', method, e)
                raise UserError(_('请求失败: %s') % e) from e

            errcode = result.get('errcode')
            if errcode in TOKEN_EXPIRED_CODES and attempt == 0:
                _logger.warning(
                    'Token expired (code %s), refreshing and retrying', errcode)
                self._invalidate_token(company_id)
                token = self._get_access_token(company_id)
                continue
            break

        return result
