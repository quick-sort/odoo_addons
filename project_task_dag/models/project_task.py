from odoo import models


class ProjectTask(models.Model):
    _inherit = "project.task"

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
