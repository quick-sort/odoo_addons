from odoo import api, models


class WecomApp(models.Model):
    _inherit = "wecom.app"

    def sync_hr(self):
        """刷新企微缓存后，把部门与成员映射到 Odoo HR。"""
        self.ensure_one()
        self.sync_departments()
        self.sync_users()
        self.env["wecom.department"].search(
            [("company_id", "=", self.company_id.id)]
        ).sync_to_hr()
        self.env["wecom.user"].search(
            [("company_id", "=", self.company_id.id)]
        ).sync_to_hr()
        return self

    def action_sync_hr(self):
        """表单「同步到HR」按钮。"""
        for app in self:
            app.sync_hr()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": "同步完成",
                "message": "企微组织与人员已同步到 HR。",
                "sticky": False,
            },
        }

    @api.model
    def _cron_sync_hr_all(self):
        """定时任务入口：遍历 active 应用逐个同步。"""
        for app in self.search([("active", "=", True)]):
            app.sync_hr()
