from unittest import mock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestWecomHrSync(TransactionCase):

    def _make_department(self, wecom_id, name, parent=None):
        return self.env["wecom.department"].create(
            {
                "wecom_id": wecom_id,
                "name": name,
                "parent_id": parent.id if parent else False,
            }
        )

    def _make_user(self, wecom_id, name, department=None, **kwargs):
        vals = {
            "wecom_id": wecom_id,
            "name": name,
            "main_department_id": department.id if department else False,
        }
        vals.update(kwargs)
        return self.env["wecom.user"].create(vals)

    def test_department_sync_creates_and_parents(self):
        parent = self._make_department(1, "总部")
        child = self._make_department(2, "研发部", parent=parent)

        (parent | child).sync_to_hr()

        hr_parent = self.env["hr.department"].search([("wecom_id", "=", 1)], limit=1)
        hr_child = self.env["hr.department"].search([("wecom_id", "=", 2)], limit=1)
        self.assertTrue(hr_parent)
        self.assertTrue(hr_child)
        self.assertEqual(hr_child.parent_id, hr_parent)
        self.assertEqual(hr_parent.company_id, parent.company_id)

    def test_department_sync_idempotent(self):
        dept = self._make_department(1, "总部")
        dept.sync_to_hr()

        dept.name = "总部（改）"
        dept.sync_to_hr()

        rows = self.env["hr.department"].search([("wecom_id", "=", 1)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.name, "总部（改）")

    def test_employee_sync_creates_and_maps_department(self):
        dept = self._make_department(10, "研发部")
        dept.sync_to_hr()

        user = self._make_user(
            "zhangsan",
            "张三",
            department=dept,
            position="工程师",
            mobile="13800000000",
            email="zhangsan@example.com",
            gender="1",
        )
        user.sync_to_hr()

        emp = self.env["hr.employee"].search([("wecom_userid", "=", "zhangsan")], limit=1)
        self.assertTrue(emp)
        self.assertEqual(emp.name, "张三")
        self.assertEqual(emp.job_title, "工程师")
        self.assertEqual(emp.mobile_phone, "13800000000")
        self.assertEqual(emp.work_email, "zhangsan@example.com")
        self.assertEqual(emp.gender, "male")
        self.assertEqual(emp.company_id, user.company_id)
        self.assertEqual(
            emp.department_id.wecom_id, 10, "department_id 应映射到对应 hr.department"
        )

    def test_employee_sync_idempotent_matches_by_wecom_userid(self):
        dept = self._make_department(10, "研发部")
        dept.sync_to_hr()
        user = self._make_user("zhangsan", "张三", department=dept, position="工程师")
        user.sync_to_hr()

        user.write({"name": "张三丰", "position": "高级工程师"})
        user.sync_to_hr()

        rows = self.env["hr.employee"].search([("wecom_userid", "=", "zhangsan")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.name, "张三丰")
        self.assertEqual(rows.job_title, "高级工程师")

    def test_sync_hr_orchestrates(self):
        app = self.env["wecom.app"].create(
            {
                "name": "测试应用",
                "wecom_corp_id": "corp",
                "wecom_agent_id": "1",
                "wecom_secret": "secret",
            }
        )
        client = mock.MagicMock()
        client.department.get.return_value = [
            {"id": 1, "name": "总部", "parentid": 0},
            {"id": 2, "name": "研发部", "parentid": 1},
        ]
        client.user.list.return_value = [
            {
                "userid": "zhangsan",
                "name": "张三",
                "position": "工程师",
                "mobile": "13800000000",
                "email": "zhangsan@example.com",
                "gender": "1",
                "department": [2],
                "main_department": 2,
                "extattr": {"attrs": []},
            }
        ]

        with mock.patch.object(type(app), "get_wecom_client", return_value=client):
            app.sync_hr()

        self.assertEqual(self.env["hr.department"].search_count([("wecom_id", "!=", False)]), 2)
        emp = self.env["hr.employee"].search([("wecom_userid", "=", "zhangsan")], limit=1)
        self.assertTrue(emp)
        self.assertEqual(emp.department_id.wecom_id, 2)
