"""注册限流（R9.5）。

接在 ``do_signup`` 上：它抛出的 ``UserError`` 会被 ``web_auth_signup`` 捕获并
写进 ``qcontext['error']`` 显示给用户（见
``auth_signup/controllers/main.py:66-68``），所以限流提示能自然地出现在注册表单上，
不需要自己渲染页面。

关于邮箱验证：Odoo 的自助注册**不是**"先验证邮箱再激活"，它会立即创建账号，
然后发一封账号创建确认邮件
（``auth_signup.mail_template_user_signup_account_created``）。真正要把邮箱验证
做成准入门槛需要额外开发，当前不在范围内——已在 README 里写明。
"""

import logging

from odoo import _
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.auth_signup.controllers.main import AuthSignupHome

_logger = logging.getLogger(__name__)


class InfohubAuthSignupHome(AuthSignupHome):
    def do_signup(self, qcontext, do_login=True):
        """注册前按 IP 做滑动窗口限流。

        只在"未邀请的自助注册"上限流：带 token 的注册是管理员发出的邀请，
        不应该被拦。
        """
        if not qcontext.get("token"):
            ip = request.httprequest.remote_addr
            allowed = request.env["infohub.signup.attempt"].sudo().check_and_record(ip)
            if not allowed:
                _logger.warning("InfoHub: 注册限流拦截了来自 %s 的请求", ip)
                raise UserError(
                    _("注册请求过于频繁，请稍后再试。")
                )
        return super().do_signup(qcontext, do_login=do_login)
