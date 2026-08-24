# -*- coding: utf-8 -*-
import base64
import io
from datetime import timedelta
from odoo import fields, models, exceptions
from wechatpy.enterprise import WeChatClient


class WechatAppSessionStorage:
    """
    基于 wechat.app 记录持久化 access_token 的 Session 存储。
    避免每次实例化 WeChatClient 时都重新请求企业微信的 access_token 接口，
    并在多进程/多 worker/定时任务等场景下共享同一个有效 token，实现token的缓存与自动刷新。
    """

    def __init__(self, app):
        self.app = app.sudo()

    def get(self, key, default=None):
        # wechatpy 的 access_token 键名以 "_access_token" 结尾
        if key.endswith('_access_token') and self.app.wechat_access_token:
            if self.app.wechat_access_token_expires_at and \
                    self.app.wechat_access_token_expires_at > fields.Datetime.now():
                return self.app.wechat_access_token
        return default

    def set(self, key, value, ttl=None):
        if key.endswith('_access_token'):
            expires_at = fields.Datetime.now() + timedelta(seconds=int(ttl or 0))
            self.app.write({'wechat_access_token': value, 'wechat_access_token_expires_at': expires_at})

    def delete(self, key):
        if key.endswith('_access_token'):
            self.app.write({'wechat_access_token': False, 'wechat_access_token_expires_at': False})


class WechatApp(models.Model):
    _name = 'wechat.app'
    _description = '企微应用'
    _order = 'company_id, name'

    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="公司", required=True, default=lambda self: self.env.company)
    name = fields.Char(string="应用名称", required=True)
    wechat_corp_id = fields.Char(string="CorpId", required=True)
    wechat_agent_id = fields.Char(string="AgentId", required=True)
    wechat_secret = fields.Char(string="Secret", required=True)
    description = fields.Text(string="备注")

    # 网页授权及JS-SDK：可信域名归属校验文件（企微App内H5页面调用JS-SDK前需要先完成域名校验）
    wechat_js_sdk_file_name = fields.Char(string='JS-SDK域名校验文件名', help="即企业微信后台上传的域名校验文件名，"
                                                                          "如 WW_verify_xxxxxxxxxx.txt")
    wechat_js_sdk_file = fields.Binary(string='JS-SDK域名校验文件', attachment=True)

    # access_token 缓存，用于跨请求/跨进程复用，避免频繁调用企业微信token接口
    wechat_access_token = fields.Char(string="AccessToken缓存", readonly=True, copy=False, groups="base.group_no_one")
    wechat_access_token_expires_at = fields.Datetime(string="AccessToken过期时间", readonly=True, copy=False,
                                                       groups="base.group_no_one")

    _sql_constraints = [
        ('wechat_js_sdk_file_name_uniq', 'unique(wechat_js_sdk_file_name)',
         '该JS-SDK域名校验文件名已被其他企微应用使用，请检查。'),
    ]

    def get_wechat_client(self):
        """
        返回配置好token缓存/自动刷新的 WeChatClient 实例。
        """
        self.ensure_one()
        session = WechatAppSessionStorage(self)
        return WeChatClient(self.wechat_corp_id, self.wechat_secret, session=session)

    def get_departments(self):
        """
        获取企业微信通讯录中的部门列表（原始数据，需要该应用有“通讯录管理”读取权限）。
        """
        self.ensure_one()
        return self.get_wechat_client().department.get()

    def get_users(self, department_id=1, fetch_child=True):
        """
        获取企业微信通讯录中的成员列表（原始数据，需要该应用有“通讯录管理”读取权限）。
        """
        self.ensure_one()
        return self.get_wechat_client().user.list(department_id=department_id, fetch_child=fetch_child)

    def sync_departments(self):
        """
        拉取部门数据并更新本地缓存(wechat.department)。
        """
        self.ensure_one()
        return self.env['wechat.department'].sync_from_app(self)

    def sync_users(self, department_id=1, fetch_child=True):
        """
        拉取成员数据并更新本地缓存(wechat.user)。会先确保部门缓存存在，以便成员能正确关联部门。
        """
        self.ensure_one()
        if not self.env['wechat.department'].search_count([('company_id', '=', self.company_id.id)]):
            self.sync_departments()
        return self.env['wechat.user'].sync_from_app(self, department_id=department_id, fetch_child=fetch_child)

    def action_sync_departments(self):
        """
        表单“同步部门”按钮
        """
        for app in self:
            app.sync_departments()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'title': '同步完成', 'message': "企微部门数据已同步。", 'sticky': False}
        }

    def action_sync_users(self):
        """
        表单“同步成员”按钮
        """
        for app in self:
            app.sync_users()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'title': '同步完成', 'message': "企微成员数据已同步。", 'sticky': False}
        }

    def _upload_media(self, media_type, file_content, filename=None):
        """
        上传临时素材（3天有效），返回 media_id。
        主要用于 mpnews（图文素材消息）的封面图 thumb_media_id。

        内部接口，由消息记录发送时自动调用；其他模块请通过 send_message() 直接传封面图内容。

        :param media_type: image / voice / video / file
        :param file_content: 文件二进制内容(bytes)
        :param filename: 文件名，用于帮助企业微信识别文件类型（如 .png/.jpg）
        """
        self.ensure_one()
        client = self.get_wechat_client()
        media_file = io.BytesIO(file_content)
        media_file.name = filename or 'file'
        result = client.media.upload(media_type, media_file)
        return result.get('media_id') if isinstance(result, dict) else result

    def _upload_content_image(self, file_content, filename=None):
        """
        上传图文消息(mpnews)正文内的图片，返回永久有效的图片URL。
        该URL只能用于 mpnews 正文中的 <img> 标签，不能用于其他场景。

        内部接口，由消息记录发送时自动调用；其他模块请通过 send_message() 的 content_image 参数传图片内容。
        """
        self.ensure_one()
        client = self.get_wechat_client()
        media_file = io.BytesIO(file_content)
        media_file.name = filename or 'file'
        result = client.media.upload_img(media_file)
        return result.get('url') if isinstance(result, dict) else result

    # ------------------------------------------------------------------
    # 消息发送
    #
    # 对外接口（其他模块唯一入口）：send_message()
    #     先在企微模块内自动创建一条消息记录(wechat.app.message)作为发送历史，再发送，
    #     保证每一次发送都能在「发布历史」里查到内容、接收范围、发送时间和发送结果。
    #     素材上传（封面图/正文图片）也由该接口内部完成，调用方只需传图片内容。
    # 内部接口：_send_message()
    #     直接调用企业微信服务端接口，不产生任何历史记录，
    #     仅供 wechat.app.message 记录发送时使用，其他模块不要直接调用。
    # ------------------------------------------------------------------

    def send_message(self, title, msg_type='textcard', url=None, description='', image_url=None,
                      btn_text='详情', touser=None, toparty=None, totag=None, send_to_all=False,
                      user_ids=None, department_ids=None, content=None, author='', digest='',
                      content_source_url='', show_cover_pic=True, thumb_image=None,
                      thumb_image_filename=None, content_image=None, content_image_filename=None,
                      source_ref=None, raise_exception=True):
        """
        对外消息发送接口：自动创建消息历史记录(wechat.app.message)后发送。

        其他模块要通过企微应用发消息，一律调用本方法，不要自行拼装消息或调用内部接口，
        这样每次发送都会在企微模块的「发布历史」里留下记录，便于查看和排查。

        :param title: 标题
        :param msg_type: 'textcard'（文本卡片消息，单条链接，默认）/ 'news'（图文消息，带缩略图，跳转外部链接）/
            'mpnews'（图文素材消息，正文可以是HTML，直接在企业微信内阅读，不需要跳转外部页面）
        :param url: 点击消息后打开的链接，msg_type='textcard'/'news' 时必填
        :param description: 描述文字，msg_type='textcard'/'news' 时使用
        :param image_url: 缩略图链接，msg_type='news' 时必填
        :param btn_text: 按钮文字，仅 msg_type='textcard' 时使用
        :param touser: 接收成员UserId，多个用“|”分隔
        :param toparty: 接收部门Id，多个用“|”分隔
        :param totag: 接收标签Id，多个用“|”分隔
        :param send_to_all: True 时发送给企业全部成员，忽略 touser/toparty/totag
        :param user_ids: 接收成员，wechat.user 的 id 列表，可与 touser 同时使用
        :param department_ids: 接收部门，wechat.department 的 id 列表，可与 toparty 同时使用
        :param content: 正文内容(支持HTML标签)，msg_type='mpnews' 时必填。
            若同时传了 content_image，正文中的 {content_image_url} 会被替换为上传后的图片URL
        :param author: 作者，msg_type='mpnews' 时使用
        :param digest: 摘要，msg_type='mpnews' 时使用，不填则企业微信自动截取正文
        :param content_source_url: “阅读原文”跳转链接，msg_type='mpnews' 时使用，可留空
        :param show_cover_pic: 是否显示封面图，msg_type='mpnews' 时使用
        :param thumb_image: 封面图内容（bytes 或 base64 字符串），msg_type='mpnews' 时必填，
            发送时自动上传为临时素材取得 thumb_media_id
        :param thumb_image_filename: 封面图文件名，帮助企业微信识别文件类型，如 cover.png
        :param content_image: mpnews 正文图片内容（bytes 或 base64 字符串），可选。
            企业微信要求正文图片必须是其“上传图文消息内的图片”接口返回的URL，
            传本参数即可由本接口自动上传并回填到正文；content 为空时正文就是这张图片
        :param content_image_filename: 正文图片文件名，如 digest.jpg
        :param source_ref: 来源标识，建议传调用方的模型与记录，如 'newsletter.digest.post,12'，便于追溯
        :param raise_exception: 发送失败时是否抛出异常。True（默认）抛出异常；
            False 则只把消息记录置为“发送失败”并把错误写入 result 字段，由调用方检查 state
        :return: 创建的 wechat.app.message 记录，可通过 state / result / invalid_user 等字段查看发送结果
        """
        self.ensure_one()
        message = self.env['wechat.app.message'].sudo().create({
            'app_id': self.id,
            'name': title,
            'msg_type': msg_type,
            'url': url or False,
            'description': description or False,
            'image_url': image_url or False,
            'btn_text': btn_text or False,
            'content': content or False,
            'author': author or False,
            'digest': digest or False,
            'content_source_url': content_source_url or False,
            'show_cover_pic': show_cover_pic,
            'thumb_image': self._to_base64(thumb_image),
            'thumb_image_filename': thumb_image_filename or False,
            'content_image': self._to_base64(content_image),
            'content_image_filename': content_image_filename or False,
            'send_to_all': send_to_all,
            'touser': touser or False,
            'toparty': toparty or False,
            'totag': totag or False,
            'user_ids': [(6, 0, user_ids)] if user_ids else False,
            'department_ids': [(6, 0, department_ids)] if department_ids else False,
            'source': 'external',
            'source_ref': source_ref or False,
        })
        message.send(raise_exception=raise_exception)
        return message

    @staticmethod
    def _to_base64(content):
        """
        把 bytes 形式的图片内容转成 Binary 字段需要的 base64；已是 base64 字符串则原样返回。
        """
        if not content:
            return False
        return base64.b64encode(content) if isinstance(content, bytes) else content

    def _send_message(self, title, url=None, msg_type='textcard', description='', image_url=None,
                       btn_text='详情', touser=None, toparty=None, totag=None, send_to_all=False,
                       content=None, author='', digest='', content_source_url='', thumb_media_id=None,
                       show_cover_pic=True):
        """
        内部发送接口：以该企微应用的身份直接调用企业微信接口发送一条应用消息，不产生历史记录。

        仅供企微模块内部（wechat.app.message 记录发送时）调用，
        其他模块请调用 send_message()，以便自动创建消息历史记录。

        :param title: 标题
        :param url: 点击消息后打开的链接，msg_type='textcard'/'news' 时必填
        :param msg_type: 'textcard'（文本卡片消息，单条链接，默认）/ 'news'（图文消息，带缩略图，跳转外部链接）/
            'mpnews'（图文素材消息，正文可以是HTML，直接在企业微信内阅读，不需要跳转外部页面）
        :param description: 描述文字，msg_type='textcard'/'news' 时使用
        :param image_url: 缩略图链接，msg_type='news' 时必填
        :param btn_text: 按钮文字，仅 msg_type='textcard' 时使用
        :param touser: 接收成员UserId，多个用“|”分隔
        :param toparty: 接收部门Id，多个用“|”分隔
        :param totag: 接收标签Id，多个用“|”分隔
        :param send_to_all: True 时发送给企业全部成员，忽略 touser/toparty/totag
        :param content: 正文内容(支持HTML标签)，msg_type='mpnews' 时必填。正文中的图片URL必须是企业微信
            “上传图文消息内的图片”接口返回的URL（可通过 _upload_content_image 获取），否则图片会被屏蔽
        :param author: 作者，msg_type='mpnews' 时使用
        :param digest: 摘要，msg_type='mpnews' 时使用，不填则企业微信自动截取正文
        :param content_source_url: “阅读原文”跳转链接，msg_type='mpnews' 时使用，可留空
        :param thumb_media_id: 封面图素材ID，msg_type='mpnews' 时必填，通过 _upload_media('image', ...) 获取
        :param show_cover_pic: 是否显示封面图，msg_type='mpnews' 时使用
        :return: 企业微信接口返回的原始结果(dict)
        """
        self.ensure_one()
        if not send_to_all and not (touser or toparty or totag):
            raise exceptions.ValidationError("请至少指定一个接收成员/部门/标签，或者设置 send_to_all=True。")

        client = self.get_wechat_client()
        user_ids = '@all' if send_to_all else (touser or '')
        party_ids = '' if send_to_all else (toparty or '')
        tag_ids = '' if send_to_all else (totag or '')

        if msg_type == 'mpnews':
            if not content:
                raise exceptions.ValidationError("图文素材消息(mpnews)必须提供正文内容(content)。")
            if not thumb_media_id:
                raise exceptions.ValidationError("图文素材消息(mpnews)必须提供封面图素材ID(thumb_media_id)。")
            return client.message.send_mp_articles(self.wechat_agent_id, user_ids, [{
                'thumb_media_id': thumb_media_id,
                'author': author or '',
                'title': title,
                'content': content,
                'content_source_url': content_source_url or '',
                'digest': digest or '',
                'show_cover_pic': 1 if show_cover_pic else 0,
            }], party_ids=party_ids, tag_ids=tag_ids)

        if not url:
            raise exceptions.ValidationError("文本卡片消息(textcard)/图文消息(news)必须提供链接(url)。")
        if msg_type == 'news':
            if not image_url:
                raise exceptions.ValidationError("图文消息(news)必须提供缩略图链接(image_url)。")
            return client.message.send_articles(self.wechat_agent_id, user_ids, [{
                'title': title,
                'description': description or '',
                'url': url,
                'image': image_url,
            }], party_ids=party_ids, tag_ids=tag_ids)
        return client.message.send_text_card(
            self.wechat_agent_id, user_ids, title, description or '', url,
            btntxt=btn_text or '详情', party_ids=party_ids, tag_ids=tag_ids)
