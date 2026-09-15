"""自助注册后的读者初始化（R9.5 / R9.6 / ADR-011）。

``auth_signup`` 通过复制模板 portal 用户来创建新用户
（``_create_user_from_template``，见 ``auth_signup/models/res_users.py:110``），
所以新用户默认只有 ``base.group_portal``。这里在 ``_signup_create_user`` 之后
补两件事：

1. 加入 ``infohub.group_reader`` —— 否则新用户连条目都读不到
2. 按标记为「推荐订阅」的学科与信息源建立默认订阅 —— 否则首屏信息流是空的

**没有选择"把 group_reader 挂到 base.group_portal 的 implied_ids 上"**：那会让
库里所有 portal 用户（包括其他应用带来的）都变成 InfoHub 读者，作用面太宽。
在注册处显式赋予更精确，代价是既有 portal 用户需要管理员手工加组。
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _signup_create_user(self, values):
        user = super()._signup_create_user(values)
        user._infohub_init_reader()
        return user

    def _infohub_init_reader(self):
        """把用户初始化成 InfoHub 读者。幂等，可重复调用。"""
        reader_group = self.env.ref("infohub.group_reader", raise_if_not_found=False)
        if not reader_group:
            return False
        for user in self:
            # sudo：注册流程里当前用户还是 public，没有写 res.users 的权限
            user_sudo = user.sudo()
            if reader_group not in user_sudo.group_ids:
                user_sudo.write({"group_ids": [(4, reader_group.id)]})
            user_sudo._infohub_ensure_default_subscriptions()
            _logger.info(
                "InfoHub: 已把新注册用户 %s 初始化为读者", user_sudo.login
            )
        return True
