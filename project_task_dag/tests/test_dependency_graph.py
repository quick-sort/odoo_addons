from odoo import Command
from odoo.service.model import call_kw
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDagView(TransactionCase):
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

    def _get_data(self, project):
        return self.env["project.task"].get_dag_data(
            domain=[("project_id", "=", project.id)]
        )

    def test_nodes_and_edges(self):
        project = self._make_project()
        a = self._make_task(project, "A")
        b = self._make_task(project, "B", [a.id])
        c = self._make_task(project, "C", [a.id])
        d = self._make_task(project, "D", [b.id, c.id])

        data = self._get_data(project)

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
        self._make_task(other, "External")

        data = self._get_data(project)

        node_ids = {n["id"] for n in data["nodes"]}
        self.assertEqual(node_ids, {a.id, b.id})

    def test_edge_dropped_when_dependency_outside_recordset(self):
        project = self._make_project()
        other = self._make_project("Other")
        ext = self._make_task(other, "External")
        self._make_task(project, "A", [ext.id])

        data = self._get_data(project)

        self.assertEqual(data["edges"], [])

    def test_state_normalized(self):
        project = self._make_project()
        done = self._make_task(project, "Done")
        done.state = "1_done"
        canceled = self._make_task(project, "Canceled")
        canceled.state = "1_canceled"
        open_task = self._make_task(project, "Open")

        states = {n["id"]: n["state"] for n in self._get_data(project)["nodes"]}

        self.assertEqual(states[done.id], "done")
        self.assertEqual(states[canceled.id], "canceled")
        self.assertEqual(states[open_task.id], "open")

    def test_rpc_call_passes_domain_as_kwarg(self):
        """The view controller calls ``orm.call(model, 'get_dag_data', [], {domain})``;
        the method must be ``@api.model`` and accept ``domain`` as a kwarg."""
        project = self._make_project()
        self._make_task(project, "A")

        data = call_kw(
            self.env["project.task"],
            "get_dag_data",
            [],
            {"domain": [("project_id", "=", project.id)]},
        )

        self.assertEqual(len(data["nodes"]), 1)
