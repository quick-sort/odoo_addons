from odoo import api, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    def action_open_task_dependency_graph(self):
        """Return the client action with ``active_id`` bound to this project.

        A ``type="action"`` button does not reliably propagate ``active_id``
        into a client action's context, so the button is ``type="object"`` and
        binds the id here instead (same pattern as ``stock_forecasted``).
        """
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "project_task_dag.action_task_dependency_graph"
        )
        action["context"] = {"active_id": self.id, "active_model": "project.project"}
        return action


class ProjectTask(models.Model):
    _inherit = "project.task"

    @api.model
    def get_dependency_graph_data(self, project_id):
        """Return the dependency DAG of a project's tasks as ``{nodes, edges}``.

        ``edges`` run from a predecessor (``depend_on_ids``, "Blocked By") to the
        task it blocks, so an arrow ``A -> B`` means "A blocks B". Read-only; the
        search below is already constrained by the caller's access rights.
        """
        tasks = self.env["project.task"].search([("project_id", "=", project_id)])
        nodes = [
            {"id": task.id, "name": task.name, "state": task.state}
            for task in tasks
        ]
        edges = [
            {"source": dep.id, "target": task.id}
            for task in tasks
            for dep in task.depend_on_ids
            if dep.project_id.id == project_id
        ]
        return {"nodes": nodes, "edges": edges}
