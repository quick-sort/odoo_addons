from odoo import models


class WecomUser(models.Model):
    _inherit = "wecom.user"

    def sync_to_hr(self):
        """把缓存成员映射为 hr.employee（幂等，按 wecom_userid 匹配）。"""
        HrEmployee = self.env["hr.employee"]
        HrDepartment = self.env["hr.department"]

        company_ids = list(set(self.mapped("company_id").ids))
        hr_dept = {
            (d.company_id.id, d.wecom_id): d.id
            for d in HrDepartment.search(
                [("company_id", "in", company_ids), ("wecom_id", "!=", False)]
            )
        }

        to_create = []
        for user in self:
            dept_id = False
            if user.main_department_id:
                dept_id = hr_dept.get(
                    (user.company_id.id, user.main_department_id.wecom_id), False
                )
            vals = {
                "name": user.name,
                "job_title": user.position or False,
                "mobile_phone": user.mobile or False,
                "work_email": user.email or False,
                "department_id": dept_id,
                "company_id": user.company_id.id,
                "wecom_userid": user.wecom_id,
            }
            emp = HrEmployee.search(
                [
                    ("company_id", "=", user.company_id.id),
                    ("wecom_userid", "=", user.wecom_id),
                ],
                limit=1,
            )
            if emp:
                emp.write(vals)
            else:
                to_create.append(vals)
        if to_create:
            HrEmployee.create(to_create)
        return self
