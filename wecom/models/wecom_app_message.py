# -*- coding: utf-8 -*-
import base64
import logging
from datetime import timedelta
from odoo import fields, models, api, exceptions

_logger = logging.getLogger(__name__)


class WecomAppMessageArticle(models.Model):
    _name = 'wecom.app.message.article'
    _description = '企微应用消息文章'
    _order = 'sequence, id'

    message_id = fields.Many2one('wecom.app.message', string="消息", required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)

    title = fields.Char(string="标题", required=True)

    # news（图文消息，跳转外部链接）
    description = fields.Text(string="描述")
    url = fields.Char(string="链接")
    image_url = fields.Char(string="缩略图链接")

    # mpnews（图文素材消息，HTML 正文）
    content = fields.Text(string="正文内容（HTML源码）",
                          help="图文素材消息的正文，直接粘贴/编写HTML源码即可，发布时原样发给企业微信；"
                               "正文中的图片需使用上传得到的URL，否则会被企业微信屏蔽")
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
                                       "{content_image_url}；正文为空时正文就是这张图片。")
    content_image_filename = fields.Char(string="正文图片文件名")

    @api.constrains('url', 'image_url', 'content', 'content_image', 'thumb_image')
    def _check_by_type(self):
        for art in self:
            msg_type = art.message_id.msg_type
            if msg_type == 'news':
                if not art.url:
                    raise exceptions.ValidationError("图文消息(news)每篇文章都必须填写链接。")
                if not art.image_url:
                    raise exceptions.ValidationError("图文消息(news)每篇文章都必须填写缩略图链接。")
            elif msg_type == 'mpnews':
                if not art.content and not art.content_image:
                    raise exceptions.ValidationError("图文素材消息(mpnews)每篇文章都必须填写正文内容或上传正文图片。")
                if not art.thumb_image:
                    raise exceptions.ValidationError("图文素材消息(mpnews)每篇文章都必须上传封面图。")

    def action_preview_content(self):
        """
        子表单“预览正文”按钮：在新标签页打开正文HTML的近似渲染效果。
        注意：预览仅在浏览器中渲染当前HTML源码，不会模拟企业微信服务端的清洗逻辑。
        """
        self.ensure_one()
        if self.message_id.msg_type != 'mpnews':
            raise exceptions.UserError("仅“图文素材消息(mpnews)”的HTML正文支持预览。")
        if not self.content:
            raise exceptions.UserError("请先填写正文内容后再预览。")
        return {
            'type': 'ir.actions.act_url',
            'url': f'/wecom/app_message/article/{self.id}/preview',
            'target': 'new',
        }

    def _get_content(self):
        """
        取 mpnews 的最终正文：上传了正文图片时，先换取企业微信图片URL，
        再替换正文中的 {content_image_url} 占位符；正文为空则整篇正文就是这张图片。
        上传后的正文会回写到记录上，便于在发布历史里看到实际发送的内容。
        """
        self.ensure_one()
        if not self.content_image:
            return self.content
        image_url = self.message_id.app_id._upload_content_image(
            base64.b64decode(self.content_image), self.content_image_filename)
        if self.content and '{content_image_url}' in self.content:
            content = self.content.replace('{content_image_url}', image_url)
        elif self.content:
            content = f'{self.content}<p><img src="{image_url}" style="width:100%" /></p>'
        else:
            content = f'<p><img src="{image_url}" style="width:100%" /></p>'
        self.content = content
        return content


class WecomAppMessage(models.Model):
    _name = 'wecom.app.message'
    _description = '企微应用消息发布'
    _order = 'create_date desc'

    app_id = fields.Many2one('wecom.app', string="发布应用", required=True, ondelete='restrict',
                              default=lambda self: self.env['wecom.app'].search(
                                  [('company_id', '=', self.env.company.id)], limit=1))
    company_id = fields.Many2one('res.company', related='app_id.company_id', store=True, readonly=True)

    name = fields.Char(string="标题", required=True)
    msg_type = fields.Selection([
        ('textcard', '文本卡片消息（单条H5链接）'),
        ('news', '图文消息（带缩略图，跳转H5链接）'),
        ('mpnews', '图文素材消息（HTML正文，企业微信内直接阅读）'),
    ], string="消息类型", default='textcard', required=True)

    # textcard 用：跳转到外部H5页面
    description = fields.Text(string="描述", help="文本卡片消息的描述文字")
    url = fields.Char(string="H5页面链接", help="点击消息后跳转打开的H5页面地址，文本卡片消息必填")
    btn_text = fields.Char(string="按钮文字", default="详情", help="仅文本卡片消息使用")

    article_ids = fields.One2many('wecom.app.message.article', 'message_id', string="文章")

    send_to_all = fields.Boolean(string="发送给全部成员")
    user_ids = fields.Many2many('wecom.user', string="接收成员",
                                 help="从本地缓存的企微通讯录中选择，如列表为空请先到「企微应用」上点击“同步成员”")
    department_ids = fields.Many2many('wecom.department', string="接收部门")
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
        ('recalled', '已撤回'),
    ], string="状态", default='draft', copy=False)
    send_date = fields.Datetime(string="发送时间", readonly=True, copy=False)
    invalid_user = fields.Char(string="无效成员", readonly=True, copy=False)
    invalid_party = fields.Char(string="无效部门", readonly=True, copy=False)
    invalid_tag = fields.Char(string="无效标签", readonly=True, copy=False)
    result = fields.Text(string="发送结果/错误信息", readonly=True, copy=False)
    msgid = fields.Text(string="MsgId", readonly=True, copy=False,
                        help="企业微信返回的消息ID，每行一个（图文超过8篇分批发送时每批各一个），"
                             "用于撤回消息；仅能撤回发送后24小时内的消息")
    recall_date = fields.Datetime(string="撤回时间", readonly=True, copy=False)

    @api.constrains('send_to_all', 'user_ids', 'department_ids', 'touser', 'toparty', 'totag')
    def _check_receivers(self):
        for rec in self:
            if not rec.send_to_all and not (rec.user_ids or rec.department_ids or
                                            rec.touser or rec.toparty or rec.totag):
                raise exceptions.ValidationError("请至少指定一个接收成员/部门/标签，或者勾选“发送给全部成员”。")

    @api.constrains('msg_type', 'url', 'article_ids')
    def _check_content_by_type(self):
        for rec in self:
            if rec.msg_type == 'textcard' and not rec.url:
                raise exceptions.ValidationError("文本卡片消息必须填写H5页面链接。")
            if rec.msg_type in ('news', 'mpnews') and not rec.article_ids:
                raise exceptions.ValidationError("图文消息/图文素材消息必须至少添加一篇文章。")

    def action_publish(self):
        """
        表单“发布”按钮：发送当前消息记录，失败时只把记录标记为“发送失败”，不抛异常打断界面。
        """
        self.send(raise_exception=False)

    def send(self, raise_exception=True):
        """
        内部发送接口：发送企微模块内已存在的消息记录，并把发送结果回写到记录上。

        供本模块的界面按钮以及 wecom.app.send_message()（对外接口）调用。
        其他模块请调用 wecom.app.send_message()，它会自动创建消息记录后再走这里，
        以保证发送历史完整。

        发送成功时会把企业微信返回的 msgid 记录到 msgid 字段（多篇分批发送时每批一个，
        每行一个），供 24 小时内撤回消息使用。

        :param raise_exception: 发送失败时是否抛出异常。True（默认）先把记录置为“发送失败”再抛出；
            False 则只记录失败状态和错误信息，继续处理后面的记录
        :return: self
        """
        for rec in self:
            try:
                result = rec._send_to_wecom()
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
                'msgid': result.get('msgid', '') if isinstance(result, dict) else '',
                'invalid_user': result.get('invaliduser', '') if isinstance(result, dict) else '',
                'invalid_party': result.get('invalidparty', '') if isinstance(result, dict) else '',
                'invalid_tag': result.get('invalidtag', '') if isinstance(result, dict) else '',
            })
        return self

    def action_recall(self):
        """
        表单“撤回”按钮：撤回已发送的消息，企业微信会在接收人客户端删除该消息。

        企业微信的限制：仅能撤回发送后 24 小时内的消息（服务端最终裁决，这里先做
        客户端预检给出友好提示）；“微信插件端”收到的消息不支持撤回。
        多篇分批发送时逐个 msgid 撤回；全部成功才置为“已撤回”，任一失败则保持
        “已发送”，错误写入 result 并以警告通知返回，可直接重试（已撤回成功的
        批次服务端会自行处理）。

        注意：撤回失败**不抛异常**。抛 UserError 会让 Odoo 回滚整个请求事务，把
        当前事务里已写入的失败信息一并吞掉（用户永远看不到失败原因），所以这里
        与「同步部门/成员」按钮一样用通知反馈结果，而不是异常对话框。
        """
        self.ensure_one()
        if self.state != 'sent':
            raise exceptions.UserError("只有“已发送”状态的消息才能撤回。")
        msgids = self._msgid_list()
        if not msgids:
            raise exceptions.UserError("该消息没有记录MsgId，无法撤回（可能是撤回功能上线前发送的记录）。")
        if not self.send_date or self.send_date < fields.Datetime.now() - timedelta(hours=24):
            raise exceptions.UserError("企业微信只允许撤回 24 小时内发送的消息，该消息已超过时限。")

        errors = []
        for msgid in msgids:
            try:
                self.app_id._recall_message(msgid)
            except Exception as e:
                _logger.error(f"企微应用消息撤回失败（{msgid}）：{e}")
                errors.append(f"{msgid}: {e}")

        if errors:
            self.write({'result': f"{self.result or ''}\n撤回失败：\n" + '\n'.join(errors)})
            return {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'warning', 'title': "撤回失败", 'sticky': True,
                           'message': '\n'.join(errors)},
            }

        self.write({
            'state': 'recalled',
            'recall_date': fields.Datetime.now(),
            'result': f"{self.result or ''}\n撤回成功：{len(msgids)} 条消息已于企业微信撤回。",
        })
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'title': "撤回成功", 'sticky': False,
                       'message': f"已在企业微信撤回 {len(msgids)} 条消息。"},
        }

    def _msgid_list(self):
        """把 msgid 字段拆成列表（每行一个），供撤回时逐条使用。"""
        self.ensure_one()
        return [m.strip() for m in (self.msgid or '').splitlines() if m.strip()]

    def _send_to_wecom(self):
        """
        按消息类型上传素材并调用企微应用的发送接口，返回企业微信的原始结果（多篇时合并）。
        """
        self.ensure_one()
        touser, toparty = self._get_receivers()
        if self.msg_type == 'textcard':
            return self.app_id._send_message(
                title=self.name,
                url=self.url,
                description=self.description,
                btn_text=self.btn_text,
                touser=touser,
                toparty=toparty,
                totag=self.totag,
                send_to_all=self.send_to_all,
            )
        return self.app_id._send_articles(
            self.msg_type,
            self._prepare_articles(),
            touser=touser,
            toparty=toparty,
            totag=self.totag,
            send_to_all=self.send_to_all,
        )

    def _prepare_articles(self):
        """
        把 article_ids 组装成 wechatpy 需要的文章 dict 列表。
        mpnews 需先逐篇上传封面图换取 thumb_media_id。
        """
        self.ensure_one()
        if self.msg_type == 'news':
            return [{
                'title': art.title,
                'description': art.description or '',
                'url': art.url,
                'image': art.image_url,
            } for art in self.article_ids]

        articles = []
        for art in self.article_ids:
            thumb_media_id = self.app_id._upload_media(
                'image', base64.b64decode(art.thumb_image), art.thumb_image_filename)
            art.thumb_media_id = thumb_media_id
            articles.append({
                'thumb_media_id': thumb_media_id,
                'author': art.author or '',
                'title': art.title,
                'content': art._get_content(),
                'content_source_url': art.content_source_url or '',
                'digest': art.digest or '',
                'show_cover_pic': 1 if art.show_cover_pic else 0,
            })
        return articles

    def _get_receivers(self):
        """
        合并「接收成员/接收部门」（本地通讯录选择）与 touser/toparty（直接填写的企微Id），
        返回企业微信接口需要的 (touser, toparty) 字符串。
        """
        self.ensure_one()
        users = self.user_ids.mapped('wecom_id') + (self.touser or '').split('|')
        parties = [str(wid) for wid in self.department_ids.mapped('wecom_id')] + (self.toparty or '').split('|')
        return '|'.join(dict.fromkeys(filter(None, users))), '|'.join(dict.fromkeys(filter(None, parties)))
