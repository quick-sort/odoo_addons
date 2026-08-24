# -*- coding: utf-8 -*-
import base64
from werkzeug.exceptions import NotFound
from odoo.http import request, route, Controller


class WechatApi(Controller):

    @route('/<string:filename>.txt', type='http', auth="public", methods=['GET'])
    def wechat_verify_jsdk_file_content(self, filename=None, **kw):
        """
        读取企微应用的JS-SDK域名校验文件内容，供企业微信核对域名归属。
        :return: wechat_js_sdk_file 的文件内容
        """
        app = request.env['wechat.app'].sudo().search(
            [('wechat_js_sdk_file_name', '=', f'{filename}.txt')], limit=1)
        if not app or not app.wechat_js_sdk_file:
            raise NotFound()
        return base64.b64decode(app.wechat_js_sdk_file.decode('utf-8'))

    @route('/wechat/app_message/<int:message_id>/preview', type='http', auth="user", methods=['GET'])
    def wechat_app_message_preview(self, message_id, **kw):
        """
        预览「图文素材消息(mpnews)」正文的HTML渲染效果。
        仅做浏览器近似渲染，不会模拟企业微信服务端的清洗/过滤逻辑（如自动去除JS等），
        发布前的最终效果仍以真实设备收到的消息为准。
        """
        message = request.env['wechat.app.message'].browse(message_id)
        if not message.exists():
            raise NotFound()
        message.check_access('read')
        html = request.env['ir.qweb']._render('odoo_wechat.wechat_app_message_preview_page', {
            'message': message,
        })
        return request.make_response(
            "<!DOCTYPE html>\n" + html,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
        )
