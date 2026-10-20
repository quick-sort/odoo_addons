from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProjectTaskDocuments(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create({"name": "Documents Project"})
        cls.task = cls.env["project.task"].create(
            {"name": "Documented Task", "project_id": cls.project.id}
        )
        cls.attachment = cls.env["ir.attachment"].create(
            {
                "name": "spec.txt",
                "raw": b"hello",
                "res_model": "project.task",
                "res_id": cls.task.id,
            }
        )

    def test_count_includes_task_attachments(self):
        self.assertEqual(self.project.task_attachment_count, 1)

    def test_count_excludes_other_projects(self):
        other_project = self.env["project.project"].create({"name": "Other Project"})
        other_task = self.env["project.task"].create(
            {"name": "Other Task", "project_id": other_project.id}
        )
        self.env["ir.attachment"].create(
            {
                "name": "other.txt",
                "raw": b"other",
                "res_model": "project.task",
                "res_id": other_task.id,
            }
        )
        self.assertEqual(self.project.task_attachment_count, 1)
        self.assertEqual(other_project.task_attachment_count, 1)

    def test_count_includes_message_attachments(self):
        self.task.message_post(body="Please review", attachments=[("notes.txt", b"data")])
        self.assertEqual(self.project.task_attachment_count, 2)

    def test_action_domain_is_scoped_to_project_tasks(self):
        other_project = self.env["project.project"].create({"name": "Other Project"})
        other_task = self.env["project.task"].create(
            {"name": "Other Task", "project_id": other_project.id}
        )
        self.env["ir.attachment"].create(
            {
                "name": "other.txt",
                "raw": b"other",
                "res_model": "project.task",
                "res_id": other_task.id,
            }
        )
        action = self.project.action_view_task_attachments()
        self.assertEqual(action["res_model"], "ir.attachment")
        self.assertIn(("res_model", "=", "project.task"), action["domain"])
        res_id_filter = next(item for item in action["domain"] if item[0] == "res_id")
        self.assertEqual(res_id_filter, ("res_id", "in", self.task.ids))
        self.assertNotIn(other_task.id, res_id_filter[2])
