import hashlib
import logging

from odoo import http
from odoo.http import Response, request

from ..utils import has_wechatpy

_logger = logging.getLogger(__name__)


class WechatWebhookController(http.Controller):
    """Base webhook: URL verification (GET) + message intake (POST).

    MP-specific reply behavior lives in mp_callback; this controller only
    validates, logs, and dispatches.
    """

    def _get_company(self, company_id):
        company = request.env['res.company'].sudo().browse(int(company_id))
        return company if company.exists() else None

    def _verify_signature(self, company, signature, timestamp, nonce):
        if not has_wechatpy():
            return False
        token = company.wechat_token
        if not token:
            _logger.warning('Company %s has no WeChat token configured', company.id)
            return False
        data = sorted([token, timestamp, nonce])
        return hashlib.sha1(''.join(data).encode()).hexdigest() == signature

    def _decrypt_message(self, company, encrypt, msg_signature, timestamp, nonce):
        try:
            from wechatpy.crypto import WeChatCrypto
            crypto = WeChatCrypto(
                company.wechat_token,
                company.wechat_aes_key,
                company.wechat_app_id,
            )
            return crypto.decrypt(encrypt, msg_signature, timestamp, nonce)
        except Exception as e:
            _logger.error('Message decryption error: %s', e)
            return None

    @http.route('/wechat/webhook/<int:company_id>', type='http', auth='public',
                csrf=False, methods=['GET', 'POST'], sitemap=False)
    def webhook(self, company_id, **kwargs):
        company = self._get_company(company_id)
        if not company:
            return Response('Company not found', status=404)

        if request.httprequest.method == 'GET':
            return self._handle_verification(company, kwargs)

        return self._handle_message(company_id, company, kwargs)

    def _handle_verification(self, company, kwargs):
        signature = kwargs.get('signature', '')
        timestamp = kwargs.get('timestamp', '')
        nonce = kwargs.get('nonce', '')
        echostr = kwargs.get('echostr', '')
        if self._verify_signature(company, signature, timestamp, nonce):
            return Response(echostr or 'ok', content_type='text/plain')
        _logger.warning('Signature verification failed for company %s', company.id)
        return Response('Invalid signature', status=403)

    def _handle_message(self, company_id, company, kwargs):
        """Parse the inbound XML into a flat dict. Subclasses add behavior."""
        try:
            post_data = request.httprequest.get_data(as_text=True)
            if not post_data:
                return Response('No data', status=400)

            encrypt_type = kwargs.get('encrypt_type', 'raw')
            if encrypt_type == 'aes':
                from xml.etree import ElementTree as ET
                xml_root = ET.fromstring(post_data)
                encrypt_node = xml_root.find('Encrypt')
                if encrypt_node is not None and encrypt_node.text:
                    decrypted_xml = self._decrypt_message(
                        company, encrypt_node.text,
                        kwargs.get('msg_signature', ''),
                        kwargs.get('timestamp', ''),
                        kwargs.get('nonce', ''))
                    if decrypted_xml:
                        post_data = decrypted_xml

            return self._process_payload(company_id, company, post_data)
        except Exception as e:
            _logger.error('Webhook processing error: %s', e)
            return Response('error', status=500)

    def _process_payload(self, company_id, company, post_data):
        """Parse XML payload and return a plain success response."""
        try:
            from wechatpy import parse_message
            msg = parse_message(post_data)
            msg_data = self._extract_msg_data(msg)
        except Exception as e:
            _logger.warning('Failed to parse message, fallback to raw XML: %s', e)
            from xml.etree import ElementTree as ET
            xml_root = ET.fromstring(post_data)
            msg_data = {child.tag: child.text for child in xml_root}
        return Response('success', content_type='text/plain')

    def _extract_msg_data(self, msg):
        """Flatten a wechatpy message object into a WeChat-field-named dict."""
        data = {
            'MsgType': getattr(msg, 'type', 'text'),
            'MsgId': str(getattr(msg, 'id', '') or ''),
            'FromUserName': getattr(msg, 'source', ''),
            'ToUserName': getattr(msg, 'target', ''),
        }
        msg_type = data['MsgType']
        if msg_type == 'text':
            data['Content'] = getattr(msg, 'content', '')
        elif msg_type == 'image':
            data['MediaId'] = getattr(msg, 'media_id', '')
            data['PicUrl'] = getattr(msg, 'image', '')
        elif msg_type == 'voice':
            data['MediaId'] = getattr(msg, 'media_id', '')
            data['Format'] = getattr(msg, 'format', '')
            data['Recognition'] = getattr(msg, 'recognition', '')
        elif msg_type in ('video', 'shortvideo'):
            data['MediaId'] = getattr(msg, 'media_id', '')
            data['ThumbMediaId'] = getattr(msg, 'thumb_media_id', '')
        elif msg_type == 'location':
            location = getattr(msg, 'location', (0, 0)) or (0, 0)
            data['Location_X'] = str(location[0])
            data['Location_Y'] = str(location[1])
            data['Scale'] = str(getattr(msg, 'scale', 0) or 0)
            data['Label'] = getattr(msg, 'label', '')
        elif msg_type == 'link':
            data['Title'] = getattr(msg, 'title', '')
            data['Description'] = getattr(msg, 'description', '')
            data['Url'] = getattr(msg, 'url', '')
        elif msg_type == 'event':
            data['Event'] = getattr(msg, 'event', '')
            data['EventKey'] = getattr(msg, 'key', '') or ''
        return data
