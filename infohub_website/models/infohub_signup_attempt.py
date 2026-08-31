"""注册频率限制（R9.5 的"对注册滥用有基本防护"）。

Odoo 本身没有内置的注册限流：``auth_signup`` 只提供"是否允许未邀请用户注册"
（``auth_signup_uninvited``）这个开关。所以这里加一个按 IP 的滑动窗口计数。

**自清理，不需要 cron**：每次检查时先删掉窗口外的记录，表因此不会无限增长。

这只是基本防护。真正的抗滥用应该叠加：
* ``auth_signup_uninvited = 'b2b'``（改为仅邀请注册）——Odoo 自带的最强开关
* 反向代理层的限流（本项目部署里已有 nginx）
* reCAPTCHA：Odoo 19 的 ``@route(captcha=...)`` 参数（见 ``odoo/http.py:752``），
  需要安装并配置对应的 captcha 实现模块
"""

from odoo import fields, models

#: 默认：同一 IP 在窗口内最多注册几次
DEFAULT_MAX_ATTEMPTS = 5

#: 默认窗口（分钟）
DEFAULT_WINDOW_MINUTES = 60

PARAM_MAX = "infohub.signup_max_attempts"
PARAM_WINDOW = "infohub.signup_window_minutes"


class InfohubSignupAttempt(models.Model):
    _name = "infohub.signup.attempt"
    _description = "InfoHub 注册尝试"
    _order = "create_date desc"
    _rec_name = "ip"

    ip = fields.Char(string="来源 IP", required=True, index=True)

    _ip_date_idx = models.Index("(ip, create_date DESC)")

    @classmethod
    def _int_param(cls, env, key, default):
        raw = env["ir.config_parameter"].sudo().get_param(key)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _prune(self, window_minutes):
        """删除窗口外的记录。自清理，省掉一个 cron。"""
        cutoff = fields.Datetime.subtract(
            fields.Datetime.now(), minutes=window_minutes
        )
        self.sudo().search([("create_date", "<", cutoff)]).unlink()

    def check_and_record(self, ip):
        """检查并登记一次注册尝试。

        :return: True 表示允许，False 表示超限
        """
        if not ip:
            # 拿不到 IP 时不阻断正常注册；抗滥用交给代理层
            return True

        env = self.env
        max_attempts = self._int_param(env, PARAM_MAX, DEFAULT_MAX_ATTEMPTS)
        window = self._int_param(env, PARAM_WINDOW, DEFAULT_WINDOW_MINUTES)

        self._prune(window)

        model_sudo = self.sudo()
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=window)
        recent = model_sudo.search_count(
            [("ip", "=", ip), ("create_date", ">=", cutoff)]
        )
        if recent >= max_attempts:
            return False

        model_sudo.create({"ip": ip})
        return True
