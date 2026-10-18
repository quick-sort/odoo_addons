from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDependencyGraph(TransactionCase):
    def _make_project(self, name="Graph Project"):
        return self.env["project.project"].create({
            "name": name,
            "allow_task_dependencies": True,
        })

    def _make_task(self, project, name, deps=()):
        return self.env["project.task"].create({
            "name": name,
            "project_id": project.id,
            "depend_on_ids": [Command.set(deps)],
        })

    def test_nodes_and_edges(self):
        project = self._make_project()
        a = self._make_task(project, "A")
        b = self._make_task(project, "B", [a.id])
        c = self._make_task(project, "C", [a.id])
        d = self._make_task(project, "D", [b.id, c.id])

        data = self.env["project.task"].get_dependency_graph_data(project.id)

        node_ids = {n["id"] for n in data["nodes"]}
        self.assertEqual(node_ids, {a.id, b.id, c.id, d.id})
        edges = {(e["source"], e["target"]) for e in data["edges"]}
        self.assertEqual(
            edges,
            {(a.id, b.id), (a.id, c.id), (b.id, d.id), (c.id, d.id)},
        )

    def test_excludes_other_projects(self):
        project = self._make_project()
        other = self._make_project("Other")
        a = self._make_task(project, "A")
        b = self._make_task(project, "B", [a.id])
        ext = self._make_task(other, "External")

        data = self.env["project.task"].get_dependency_graph_data(project.id)

        node_ids = {n["id"] for n in data["nodes"]}
        self.assertEqual(node_ids, {a.id, b.id})
        self.assertNotIn(ext.id, node_ids)

    def test_action_binds_active_id(self):
        project = self._make_project()

        action = project.action_open_task_dependency_graph()

        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "task_dependency_graph")
        self.assertEqual(action["context"]["active_id"], project.id)
