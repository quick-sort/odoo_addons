import base64
import io
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WechatMpApi(http.Controller):
    """JSON-RPC endpoints for external integrations (send, users, menu, QR, media).

    All WeChat HTTP traffic goes through wechat.request so tokens stay fresh.
    """

    def _get_request_mixin(self):
        return request.env['wechat.request'].sudo()

    def _get_company_or_error(self, company_id):
        if not company_id:
            return None, {'success': False, 'error': 'company_id is required'}
        company = request.env['res.company'].sudo().browse(int(company_id))
        if not company.exists():
            return None, {'success': False, 'error': 'Company not found'}
        return company, None

    @http.route('/api/wechat/mp/send', type='json', auth='user', methods=['POST'])
    def send_template_message(self, **kwargs):
        params = request.jsonrequest
        company_id = params.get('company_id')
        openid = params.get('openid')
        template_id = params.get('template_id')
        data = params.get('data', {})
        url = params.get('url', '')

        if not all([company_id, openid, template_id]):
            return {'success': False, 'error': 'Missing required parameters'}

        company, error = self._get_company_or_error(company_id)
        if error:
            return error

        msg_data = {
            'touser': openid,
            'template_id': template_id,
            'data': data,
        }
        if url:
            msg_data['url'] = url

        try:
            result = self._get_request_mixin().wechat_post(
                company.id, '/message/template/send', json=msg_data)
        except Exception as e:
            _logger.error('Template message send error: %s', e)
            return {'success': False, 'error': str(e)}

        if result and result.get('errcode', 0) == 0:
            return {'success': True, 'msgid': result.get('msgid')}
        return {
            'success': False,
            'error': (result or {}).get('errmsg', 'Unknown error'),
            'errcode': (result or {}).get('errcode'),
        }

    @http.route('/api/wechat/mp/users', type='json', auth='user', methods=['POST'])
    def list_users(self, **kwargs):
        params = request.jsonrequest
        company_id = params.get('company_id')
        offset = int(params.get('offset', 0))
        limit = int(params.get('limit', 100))

        company, error = self._get_company_or_error(company_id)
        if error:
            return error

        try:
            result = self._get_request_mixin().wechat_get(
                company.id, '/user/get', params={'next_openid': ''})
        except Exception as e:
            return {'success': False, 'error': str(e)}

        if 'errcode' in result and result['errcode'] != 0:
            return {'success': False, 'error': result.get('errmsg')}

        openids = result.get('data', {}).get('openid', [])
        return {
            'success': True,
            'total': result.get('total', 0),
            'openids': openids[offset:offset + limit],
        }

    @http.route('/api/wechat/mp/menu/push', type='json', auth='user', methods=['POST'])
    def push_menu(self, **kwargs):
        params = request.jsonrequest
        company_id = params.get('company_id')
        menu_json = params.get('menu_json')

        company, error = self._get_company_or_error(company_id)
        if error:
            return error

        menu = None
        if menu_json is None:
            menu = request.env['wechat.menu'].sudo().search([
                ('company_id', '=', company.id),
                ('active', '=', True),
            ], limit=1)
            if not menu:
                return {'success': False, 'error': 'No active menu found'}
            menu_json = menu.menu_json

        if isinstance(menu_json, str):
            try:
                menu_json = json.loads(menu_json)
            except json.JSONDecodeError:
                return {'success': False, 'error': 'Invalid menu JSON'}

        try:
            result = self._get_request_mixin().wechat_post(
                company.id, '/menu/create', json=menu_json)
        except Exception as e:
            return {'success': False, 'error': str(e)}

        if result and result.get('errcode', 0) == 0:
            if menu:
                menu.write({'sync_status': 'synced'})
            return {'success': True}
        return {
            'success': False,
            'error': (result or {}).get('errmsg', 'Unknown error'),
            'errcode': (result or {}).get('errcode'),
        }

    @http.route('/api/wechat/mp/qrcode', type='json', auth='user', methods=['POST'])
    def create_qrcode(self, **kwargs):
        params = request.jsonrequest
        company_id = params.get('company_id')
        scene_str = params.get('scene_str')
        expire_seconds = int(params.get('expire_seconds', 2592000))

        if not scene_str:
            return {'success': False, 'error': 'scene_str is required'}

        company, error = self._get_company_or_error(company_id)
        if error:
            return error

        payload = {
            'expire_seconds': expire_seconds,
            'action_name': 'QR_STR_SCENE',
            'action_info': {'scene': {'scene_str': scene_str}},
        }
        try:
            result = self._get_request_mixin().wechat_post(
                company.id, '/qrcode/create', json=payload)
        except Exception as e:
            return {'success': False, 'error': str(e)}

        if 'ticket' in result:
            return {
                'success': True,
                'ticket': result['ticket'],
                'url': result.get('url'),
                'qrcode_url': (
                    'https://mp.weixin.qq.com/cgi-bin/showqrcode'
                    f'?ticket={result["ticket"]}'),
                'expire_seconds': result.get('expire_seconds'),
            }
        return {'success': False, 'error': result.get('errmsg', 'Unknown error')}

    @http.route('/api/wechat/mp/media/upload', type='json', auth='user', methods=['POST'])
    def upload_media(self, **kwargs):
        params = request.jsonrequest
        company_id = params.get('company_id')
        media_type = params.get('media_type', 'image')
        file_data = params.get('file_data')
        filename = params.get('filename')

        if not file_data:
            return {'success': False, 'error': 'file_data is required'}

        company, error = self._get_company_or_error(company_id)
        if error:
            return error

        try:
            file_bytes = base64.b64decode(file_data)
        except Exception:
            return {'success': False, 'error': 'Invalid base64 data'}

        import requests
        try:
            token = self._get_request_mixin()._get_access_token(company.id)
            response = requests.post(
                f'https://api.weixin.qq.com/cgi-bin/media/upload'
                f'?access_token={token}&type={media_type}',
                files={'media': (filename or 'file', io.BytesIO(file_bytes))},
                timeout=30,
            )
            result = response.json()
        except Exception as e:
            _logger.error('Upload media error: %s', e)
            return {'success': False, 'error': str(e)}

        if result.get('media_id'):
            return {
                'success': True,
                'media_id': result['media_id'],
                'created_at': result.get('created_at'),
            }
        return {'success': False, 'error': result.get('errmsg', 'Unknown error')}
