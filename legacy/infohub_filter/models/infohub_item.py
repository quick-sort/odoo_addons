"""把规则求值插进审核钩子。

核心的 ``_moderate()`` 默认直接发布（ADR-009）。这里在它之前跑规则：被终结型
动作（publish / reject）定了状态的条目不再交给核心，其余照旧走核心的默认审核。

这个 super 调用的形式是关键：``super(InfohubItem, remaining)._moderate()`` 只对
**未被规则终结**的子集调用父实现。写成 ``super()._moderate()`` 会把已经定了状态的
条目也一起发布掉，覆盖掉 reject 的结果。
"""

from odoo import models


class InfohubItem(models.Model):
    _inherit = "infohub.item"

    def _moderate(self):
        remaining = self.env["infohub.rule"]._apply(self)
        return super(InfohubItem, remaining)._moderate()
