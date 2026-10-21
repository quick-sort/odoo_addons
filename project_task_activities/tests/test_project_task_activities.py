from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProjectTaskActivities(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create({"name": "Activities Project"})
        cls.task = cls.env["project.task"].create(
            {"name": "Active Task", "project_id": cls.project.id}
        )
        cls.task_model_id = cls.env["ir.model"]._get_id("project.task")
        cls.activity_type = cls.env.ref("mail.mail_activity_data_todo")
        cls.activity = cls.env["mail.activity"].create(
            {
                "activity_type_id": cls.activity_type.id,
                "summary": "Review",
                "date_deadline": "2026-10-21",
                "res_model_id": cls.task_model_id,
                "res_id": cls.task.id,
            }
        )

    def test_count_includes_task_activities(self):
        self.assertEqual(self.project.task_activity_count, 1)

    def test_count_excludes_other_projects(self):
        other_project = self.env["project.project"].create({"name": "Other Project"})
        other_task = self.env["project.task"].create(
            {"name": "Other Task", "project_id": other_project.id}
        )
        self.env["mail.activity"].create(
            {
                "activity_type_id": self.activity_type.id,
                "summary": "Other",
                "date_deadline": "2026-10-22",
                "res_model_id": self.task_model_id,
                "res_id": other_task.id,
            }
        )
        self.assertEqual(self.project.task_activity_count, 1)
        self.assertEqual(other_project.task_activity_count, 1)

    def test_count_excludes_activities_linked_to_other_models(self):
        self.env["mail.activity"].create(
            {
                "activity_type_id": self.activity_type.id,
                "summary": "Not a task activity",
                "date_deadline": "2026-10-23",
                "res_model_id": self.env["ir.model"]._get_id("res.partner"),
                "res_id": self.env.ref("base.main_partner").id,
            }
        )
        self.assertEqual(self.project.task_activity_count, 1)

    def test_embedded_action_in_project_task_action(self):
        embedded_action = self.env.ref(
            "project_task_activities.embedded_action_project_task_activities"
        )
        parent_action = self.env.ref("project.act_project_project_2_project_task_all")
        self.assertEqual(embedded_action.parent_action_id, parent_action)
        self.assertEqual(embedded_action.parent_res_model, "project.project")
        # is_visible is a non-stored compute read from env.context; force it to
        # evaluate instead of relying on the record cache.
        embedded_action._compute_is_visible()
        self.assertFalse(embedded_action.is_visible)
        embedded_action.with_context(active_id=self.project.id)._compute_is_visible()
        self.assertTrue(embedded_action.is_visible)
        self.assertIn(
            embedded_action,
            parent_action.with_context(active_id=self.project.id).embedded_action_ids,
        )

    def test_action_domain_is_scoped_to_project_tasks(self):
        other_project = self.env["project.project"].create({"name": "Other Project"})
        other_task = self.env["project.task"].create(
            {"name": "Other Task", "project_id": other_project.id}
        )
        self.env["mail.activity"].create(
            {
                "activity_type_id": self.activity_type.id,
                "summary": "Other",
                "date_deadline": "2026-10-24",
                "res_model_id": self.task_model_id,
                "res_id": other_task.id,
            }
        )
        action = self.project.action_view_task_activities()
        self.assertEqual(action["res_model"], "mail.activity")
        self.assertIn(("res_model", "=", "project.task"), action["domain"])
        res_id_filter = next(item for item in action["domain"] if item[0] == "res_id")
        self.assertEqual(res_id_filter, ("res_id", "in", self.task.ids))
        self.assertNotIn(other_task.id, res_id_filter[2])
