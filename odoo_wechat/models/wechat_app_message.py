# -*- coding: utf-8 -*-
import base64
import logging
from odoo import fields, models, api, exceptions

_logger = logging.getLogger(__name__)


class WechatAppMessage(models.Model):
    _name = 'wechat.app.message'
    _description = '企微应用消息发布'
    _order = 'create_date desc'

    app_id = fields.Many2one('wechat.app', string="发布应用", required=True, ondelete='restrict',
                              default=lambda self: self.env['wechat.app'].search(
                                  [('company_id', '=', self.env.company.id)], limit=1))
    company_id = fields.Many2one('res.company', related='app_id.company_id', store=True, readonly=True)

    name = fields.Char(string="标题", required=True)
    msg_type = fields.Selection([
        ('textcard', '文本卡片消息（单条H5链接）'),
        ('news', '图文消息（带缩略图，跳转H5链接）'),
        ('mpnews', '图文素材消息（HTML正文，企业微信内直接阅读）'),
    ], string="消息类型", default='textcard', required=True)

    # textcard / news 用：跳转到外部H5页面
    description = fields.Text(string="描述", help="文本卡片消息/图文消息的描述文字")
    url = fields.Char(string="H5页面链接", help="点击消息后跳转打开的H5页面地址，文本卡片消息/图文消息必填")
    image_url = fields.Char(string="缩略图链接", help="图文消息(news)展示用的缩略图URL")
    btn_text = fields.Char(string="按钮文字", default="详情", help="仅文本卡片消息使用")

    # mpnews 用：正文直接是HTML，在企业微信内阅读，不跳转外部页面
    content = fields.Text(string="正文内容（HTML源码）",
                           help="图文素材消息的正文，直接粘贴/编写HTML源码即可，发布时原样发给企业微信；"
                                "正文中的图片需使用下方“正文图片上传”得到的URL，否则会被企业微信屏蔽")
    author = fields.Char(string="作者")
    digest = fields.Text(string="摘要", help="不填则企业微信自动从正文截取")
    content_source_url = fields.Char(string="阅读原文链接", help="可选，点击“阅读原文”跳转的链接")
    show_cover_pic = fields.Boolean(string="显示封面图", default=True)
    thumb_image = fields.Binary(string="封面图", attachment=True, help="图文素材消息的封面图，发布时会自动上传获取素材ID")
    thumb_image_filename = fields.Char(string="封面图文件名")
    thumb_media_id = fields.Char(string="封面图素材ID", readonly=True, copy=False,
                                  help="发布时上传封面图得到的企业微信临时素材ID，仅用于排查问题")
    content_image = fields.Binary(string="正文图片", attachment=True,
                                   help="可选。发布时自动上传该图片取得企业微信图片URL，并替换正文中的 "
                                        "{content_image_url}；正文为空时正文就是这张图片。"
                                        "主要供其他模块通过对外接口发送“整页图片”类消息使用")
    content_image_filename = fields.Char(string="正文图片文件名")

    send_to_all = fields.Boolean(string="发送给全部成员")
    user_ids = fields.Many2many('wechat.user', string="接收成员",
                                 help="从本地缓存的企微通讯录中选择，如列表为空请先到「企微应用」上点击“同步成员”")
    department_ids = fields.Many2many('wechat.department', string="接收部门")
    touser = fields.Char(string="接收成员UserId", help="直接填写企微成员UserId，多个用“|”分隔；"
                                                    "与「接收成员」同时填写时会合并发送")
    toparty = fields.Char(string="接收部门Id", help="直接填写企微部门Id，多个用“|”分隔；"
                                                 "与「接收部门」同时填写时会合并发送")
    totag = fields.Char(string="接收标签Id", help="企业微信标签Id，多个用“|”分隔（标签暂不支持从列表选择）")

    source = fields.Selection([
        ('manual', '手工创建'),
        ('external', '外部模块调用'),
    ], string="来源", default='manual', readonly=True, copy=False,
        help="“外部模块调用”表示该记录由其他模块调用企微对外发送接口时自动创建")
    source_ref = fields.Char(string="来源记录", readonly=True, copy=False,
                              help="调用方传入的来源标识，如 newsletter.digest.post,12")

    state = fields.Selection([
        ('draft', '草稿'),
        ('sent', '已发送'),
        ('failed', '发送失败'),
    ], string="状态", default='draft', copy=False, tracking=False)
    send_date = fields.Datetime(string="发送时间", readonly=True, copy=False)
    invalid_user = fields.Char(string="无效成员", readonly=True, copy=False)
    invalid_party = fields.Char(string="无效部门", readonly=True, copy=False)
    invalid_tag = fields.Char(string="无效标签", readonly=True, copy=False)
    result = fields.Text(string="发送结果/错误信息", readonly=True, copy=False)

    @api.constrains('send_to_all', 'user_ids', 'department_ids', 'touser', 'toparty', 'totag')
    def _check_receivers(self):
        for rec in self:
            if not rec.send_to_all and not (rec.user_ids or rec.department_ids or
                                            rec.touser or rec.toparty or rec.totag):
                raise exceptions.ValidationError("请至少指定一个接收成员/部门/标签，或者勾选“发送给全部成员”。")

    @api.constrains('msg_type', 'url', 'image_url', 'content', 'content_image', 'thumb_image')
    def _check_content_by_type(self):
        for rec in self:
            if rec.msg_type in ('textcard', 'news') and not rec.url:
                raise exceptions.ValidationError("文本卡片消息/图文消息必须填写H5页面链接。")
            if rec.msg_type == 'news' and not rec.image_url:
                raise exceptions.ValidationError("图文消息(news)必须填写缩略图链接。")
            if rec.msg_type == 'mpnews':
                if not rec.content and not rec.content_image:
                    raise exceptions.ValidationError("图文素材消息(mpnews)必须填写正文内容或上传正文图片。")
                if not rec.thumb_image:
                    raise exceptions.ValidationError("图文素材消息(mpnews)必须上传封面图。")

    def action_preview_content(self):
        """
        表单“预览正文”按钮：在新标签页打开正文HTML的近似渲染效果，方便发布前检查排版样式。
        注意：预览仅在浏览器中渲染当前HTML源码，不会模拟企业微信服务端的清洗逻辑
        （例如自动去除<script>、<style>、对图片URL来源的校验等），最终效果仍需以真实设备收到的消息为准。
        """
        self.ensure_one()
        if self.msg_type != 'mpnews':
            raise exceptions.UserError("仅“图文素材消息(mpnews)”的HTML正文支持预览。")
        if not self.content:
            raise exceptions.UserError("请先填写正文内容后再预览。")
        return {
            'type': 'ir.actions.act_url',
            'url': f'/wechat/app_message/{self.id}/preview',
            'target': 'new',
        }

    def action_publish(self):
        """
        表单“发布”按钮：发送当前消息记录，失败时只把记录标记为“发送失败”，不抛异常打断界面。
        """
        self.send(raise_exception=False)

    def send(self, raise_exception=True):
        """
        内部发送接口：发送企微模块内已存在的消息记录，并把发送结果回写到记录上。

        供本模块的界面按钮以及 wechat.app.send_message()（对外接口）调用。
        其他模块请调用 wechat.app.send_message()，它会自动创建消息记录后再走这里，
        以保证发送历史完整。

        :param raise_exception: 发送失败时是否抛出异常。True（默认）先把记录置为“发送失败”再抛出；
            False 则只记录失败状态和错误信息，继续处理后面的记录
        :return: self
        """
        for rec in self:
            try:
                result = rec._send_to_wechat()
            except Exception as e:
                _logger.error(f"企微应用消息发布失败：{e}")
                rec.write({'state': 'failed', 'result': str(e), 'send_date': fields.Datetime.now()})
                if raise_exception:
                    raise
                continue
            rec.write({
                'state': 'sent',
                'send_date': fields.Datetime.now(),
                'result': str(result),
                'invalid_user': result.get('invaliduser', '') if isinstance(result, dict) else '',
                'invalid_party': result.get('invalidparty', '') if isinstance(result, dict) else '',
                'invalid_tag': result.get('invalidtag', '') if isinstance(result, dict) else '',
            })
        return self

    def _send_to_wechat(self):
        """
        按消息类型上传素材并调用企微应用的内部发送接口，返回企业微信的原始结果。
        """
        self.ensure_one()
        touser, toparty = self._get_receivers()
        if self.msg_type == 'mpnews':
            thumb_media_id = self.app_id._upload_media(
                'image', base64.b64decode(self.thumb_image), self.thumb_image_filename)
            self.thumb_media_id = thumb_media_id
            return self.app_id._send_message(
                title=self.name,
                msg_type='mpnews',
                content=self._get_mpnews_content(),
                author=self.author,
                digest=self.digest,
                content_source_url=self.content_source_url,
                thumb_media_id=thumb_media_id,
                show_cover_pic=self.show_cover_pic,
                touser=touser,
                toparty=toparty,
                totag=self.totag,
                send_to_all=self.send_to_all,
            )
        return self.app_id._send_message(
            title=self.name,
            url=self.url,
            msg_type=self.msg_type,
            description=self.description,
            image_url=self.image_url,
            btn_text=self.btn_text,
            touser=touser,
            toparty=toparty,
            totag=self.totag,
            send_to_all=self.send_to_all,
        )

    def _get_receivers(self):
        """
        合并「接收成员/接收部门」（本地通讯录选择）与 touser/toparty（直接填写的企微Id），
        返回企业微信接口需要的 (touser, toparty) 字符串。
        """
        self.ensure_one()
        users = self.user_ids.mapped('wechat_id') + (self.touser or '').split('|')
        parties = [str(wid) for wid in self.department_ids.mapped('wechat_id')] + (self.toparty or '').split('|')
        return '|'.join(dict.fromkeys(filter(None, users))), '|'.join(dict.fromkeys(filter(None, parties)))

    def _get_mpnews_content(self):
        """
        取 mpnews 的最终正文：上传了正文图片时，先换取企业微信图片URL，
        再替换正文中的 {content_image_url} 占位符；正文为空则整篇正文就是这张图片。
        上传后的正文会回写到记录上，便于在发布历史里看到实际发送的内容。
        """
        self.ensure_one()
        if not self.content_image:
            return self.content
        image_url = self.app_id._upload_content_image(
            base64.b64decode(self.content_image), self.content_image_filename)
        if self.content and '{content_image_url}' in self.content:
            content = self.content.replace('{content_image_url}', image_url)
        elif self.content:
            content = f'{self.content}<p><img src="{image_url}" style="width:100%" /></p>'
        else:
            content = f'<p><img src="{image_url}" style="width:100%" /></p>'
        self.content = content
        return content
