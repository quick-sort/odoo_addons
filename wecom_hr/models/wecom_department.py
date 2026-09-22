from odoo import models


class WecomDepartment(models.Model):
    _inherit = "wecom.department"

    def sync_to_hr(self):
        """把缓存部门映射为 hr.department（幂等，含二遍父级关系）。"""
        HrDepartment = self.env["hr.department"]
        existing = {}
        to_create = []
        for dep in self:
            key = (dep.company_id.id, dep.wecom_id)
            hr = HrDepartment.search(
                [("company_id", "=", dep.company_id.id), ("wecom_id", "=", dep.wecom_id)],
                limit=1,
            )
            if hr:
                hr.write({"name": dep.name})
                existing[key] = hr
            else:
                to_create.append(
                    {
                        "company_id": dep.company_id.id,
                        "wecom_id": dep.wecom_id,
                        "name": dep.name,
                    }
                )
        if to_create:
            for rec in HrDepartment.create(to_create):
                existing[(rec.company_id.id, rec.wecom_id)] = rec
        for dep in self:
            child = existing.get((dep.company_id.id, dep.wecom_id))
            parent = dep.parent_id
            if child and parent:
                parent_hr = existing.get((parent.company_id.id, parent.wecom_id))
                if parent_hr and child.parent_id != parent_hr:
                    child.write({"parent_id": parent_hr.id})
        return self
