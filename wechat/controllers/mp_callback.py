import logging
import time

from odoo import http
from odoo.http import Response, request

from .main import WechatWebhookController

_logger = logging.getLogger(__name__)


class WechatMpCallback(WechatWebhookController):
    """MP webhook with auto-reply: keyword rules, default reply, subscribe reply.

    Replies are passive (returned in the HTTP response body), so handler
    methods return either None or a reply payload dict which this class
    renders as the WeChat reply XML.
    """

    @http.route('/wechat/mp/webhook/<int:company_id>', type='http',
                auth='public', csrf=False, methods=['GET', 'POST'],
                sitemap=False)
    def mp_webhook(self, company_id, **kwargs):
        return self.webhook(company_id, **kwargs)

    def _process_payload(self, company_id, company, post_data):
        try:
            from wechatpy import parse_message
            msg_data = self._extract_msg_data(parse_message(post_data))
        except Exception as e:
            _logger.warning('Failed to parse message, fallback to raw XML: %s', e)
            from xml.etree import ElementTree as ET
            xml_root = ET.fromstring(post_data)
            msg_data = {child.tag: child.text for child in xml_root}

        self._store_message(company_id, msg_data)
        reply_data = self._dispatch_message(company_id, company, msg_data)
        if reply_data:
            return self._render_reply_xml(msg_data, reply_data)
        return Response('success', content_type='text/plain')

    def _store_message(self, company_id, msg_data):
        try:
            msg_type = msg_data.get('MsgType', 'text')
            event_type = msg_data.get('Event', '') or ''
            if msg_type == 'event':
                msg_type = f'event_{event_type}' if event_type else 'event'

            vals = {
                'company_id': company_id,
                'msgid': str(msg_data.get('MsgId', '') or ''),
                'from_user': msg_data.get('FromUserName', ''),
                'to_user': msg_data.get('ToUserName', ''),
                'msg_type': msg_type if msg_data in
                self.env_fields_selection() else 'event',
                'content': msg_data.get('Content', ''),
                'direction': 'inbound',
                'event_type': event_type,
                'event_key': msg_data.get('EventKey', ''),
                'media_id': msg_data.get('MediaId', ''),
                'pic_url': msg_data.get('PicUrl', ''),
                'location_x': float(msg_data.get('Location_X', 0) or 0),
                'location_y': float(msg_data.get('Location_Y', 0) or 0),
                'scale': int(float(msg_data.get('Scale', 0) or 0)),
                'label': msg_data.get('Label', ''),
                'title': msg_data.get('Title', ''),
                'description': msg_data.get('Description', ''),
                'url': msg_data.get('Url', ''),
                'format': msg_data.get('Format', ''),
                'recognition': msg_data.get('Recognition', ''),
                'state': 'done',
            }

            openid = msg_data.get('FromUserName', '')
            if openid:
                user = request.env['wechat.user'].sudo().search([
                    ('wechat_openid', '=', openid),
                    ('company_id', '=', company_id),
                ], limit=1)
                if user:
                    vals['user_id'] = user.id

            request.env['wechat.message.log'].sudo().create(vals)
        except Exception as e:
            _logger.error('Failed to store message: %s', e)

    def env_fields_selection(self):
        """Valid msg_type values for wechat.message.log storage."""
        field = request.env['wechat.message.log']._fields['msg_type']
        return {key for key, _label in field.selection}

    def _dispatch_message(self, company_id, company, msg_data):
        """Route to a handler; the first non-None return is the passive reply."""
        msg_type = msg_data.get('MsgType')
        event_type = msg_data.get('Event', '')

        if msg_type == 'event':
            handlers = {
                'subscribe': self._on_subscribe,
                'unsubscribe': self._on_unsubscribe,
                'CLICK': self._on_menu_click,
                'VIEW': self._on_view,
                'scancode_push': self._on_scan,
                'scancode_waitmsg': self._on_scan,
                'LOCATION': self._on_location_event,
            }
            handler = handlers.get(event_type, self._on_event)
            return handler(company_id, company, msg_data)

        handlers = {
            'text': self._on_text,
            'image': self._on_image,
            'voice': self._on_voice,
            'video': self._on_video,
            'shortvideo': self._on_shortvideo,
            'location': self._on_location,
            'link': self._on_link,
        }
        handler = handlers.get(msg_type)
        if handler:
            return handler(company_id, company, msg_data)
        _logger.warning('Unknown message type: %s', msg_type)
        return None

    def _get_reply_config(self, param, default='True'):
        return request.env['ir.config_parameter'].sudo().get_param(
            param, default).lower() == 'true'

    def _on_text(self, company_id, company, msg_data):
        content = (msg_data.get('Content') or '').strip()
        if not content:
            return None

        Rule = request.env['wechat.message.rule'].sudo()
        matched_rule = Rule.match_keyword(company_id, content)
        if matched_rule:
            return matched_rule.get_reply_data()

        if self._get_reply_config('wechat.auto_reply_enabled'):
            default_reply = request.env[
                'wechat.auto.reply.default'].sudo().search([
                    ('company_id', '=', company_id),
                    ('active', '=', True),
                ], limit=1)
            if default_reply:
                return default_reply.get_reply_data()
        return None

    def _on_subscribe(self, company_id, company, msg_data):
        request.env['wechat.user'].sudo().create_from_subscribe(
            company_id, msg_data)
        if self._get_reply_config('wechat.auto_reply_enabled'):
            reply = request.env['wechat.subscribe.reply'].sudo().search([
                ('company_id', '=', company_id),
                ('active', '=', True),
            ], limit=1)
            if reply:
                return reply.get_reply_data()
        return None

    def _on_unsubscribe(self, company_id, company, msg_data):
        openid = msg_data.get('FromUserName', '')
        if openid:
            user = request.env['wechat.user'].sudo().search([
                ('wechat_openid', '=', openid),
                ('company_id', '=', company_id),
            ], limit=1)
            if user:
                user.update_from_unsubscribe()
        return None

    def _on_menu_click(self, company_id, company, msg_data):
        event_key = msg_data.get('EventKey', '')
        rule = request.env['wechat.message.rule'].sudo().search([
            ('keyword', '=', event_key),
            ('company_id', '=', company_id),
            ('active', '=', True),
        ], limit=1)
        if rule:
            return rule.get_reply_data()
        return None

    def _on_scan(self, company_id, company, msg_data):
        event_key = msg_data.get('EventKey', '')
        openid = msg_data.get('FromUserName', '')
        if openid and event_key:
            user = request.env['wechat.user'].sudo().search([
                ('wechat_openid', '=', openid),
                ('company_id', '=', company_id),
            ], limit=1)
            if user:
                field = 'qr_scene' if event_key.isdigit() else 'qr_scene_str'
                user.write({field: event_key})
        return None

    def _on_image(self, company_id, company, msg_data):
        return None

    def _on_voice(self, company_id, company, msg_data):
        return None

    def _on_video(self, company_id, company, msg_data):
        return None

    def _on_shortvideo(self, company_id, company, msg_data):
        return None

    def _on_location(self, company_id, company, msg_data):
        return None

    def _on_link(self, company_id, company, msg_data):
        return None

    def _on_view(self, company_id, company, msg_data):
        return None

    def _on_location_event(self, company_id, company, msg_data):
        return None

    def _on_event(self, company_id, company, msg_data):
        _logger.info('Unhandled MP event: %s', msg_data.get('Event'))
        return None

    def _render_reply_xml(self, msg_data, reply_data):
        """Render a passive-reply XML envelope for the given payload."""
        to_user = msg_data.get('FromUserName', '')
        from_user = msg_data.get('ToUserName', '')
        now = str(int(time.time()))
        msg_type = reply_data.get('msg_type', 'text')

        header = (
            f'<xml><ToUserName><![CDATA[{to_user}]]></ToUserName>'
            f'<FromUserName><![CDATA[{from_user}]]></FromUserName>'
            f'<CreateTime>{now}</CreateTime>'
        )
        footer = '</xml>'

        if msg_type == 'text':
            content = reply_data.get('content', '')
            body = (f'<MsgType><![CDATA[text]]></MsgType>'
                    f'<Content><![CDATA[{content}]]></Content>')
        elif msg_type == 'image':
            body = (f'<MsgType><![CDATA[image]]></MsgType><Image>'
                    f'<MediaId><![CDATA[{reply_data.get("media_id", "")}]]>'
                    f'</MediaId></Image>')
        elif msg_type == 'voice':
            body = (f'<MsgType><![CDATA[voice]]></MsgType><Voice>'
                    f'<MediaId><![CDATA[{reply_data.get("media_id", "")}]]>'
                    f'</MediaId></Voice>')
        elif msg_type == 'video':
            body = (f'<MsgType><![CDATA[video]]></MsgType><Video>'
                    f'<MediaId><![CDATA[{reply_data.get("media_id", "")}]]></MediaId>'
                    f'<Title><![CDATA[{reply_data.get("title", "")}]]></Title>'
                    f'<Description><![CDATA[{reply_data.get("description", "")}]]>'
                    f'</Description></Video>')
        elif msg_type == 'music':
            body = (f'<MsgType><![CDATA[music]]></MsgType><Music>'
                    f'<Title><![CDATA[{reply_data.get("title", "")}]]></Title>'
                    f'<Description><![CDATA[{reply_data.get("description", "")}]]></Description>'
                    f'<MusicUrl><![CDATA[{reply_data.get("music_url", "")}]]></MusicUrl>'
                    f'<HQMusicUrl><![CDATA[{reply_data.get("hq_music_url", "")}]]></HQMusicUrl>'
                    f'<ThumbMediaId><![CDATA[{reply_data.get("thumb_media_id", "")}]]></ThumbMediaId>'
                    f'</Music>')
        elif msg_type == 'news':
            articles = reply_data.get('articles', [])
            if not articles:
                return Response('success', content_type='text/plain')
            article = articles[0]
            body = (f'<MsgType><![CDATA[news]]></MsgType>'
                    f'<ArticleCount>1</ArticleCount><Articles><item>'
                    f'<Title><![CDATA[{article.get("title", "")}]]></Title>'
                    f'<Description><![CDATA[{article.get("description", "")}]]></Description>'
                    f'<PicUrl><![CDATA[{article.get("picurl", "")}]]></PicUrl>'
                    f'<Url><![CDATA[{article.get("url", "")}]]></Url>'
                    f'</item></Articles>')
        else:
            return Response('success', content_type='text/plain')

        xml = f'{header}{body}{footer}'
        return Response(xml, content_type='application/xml')
