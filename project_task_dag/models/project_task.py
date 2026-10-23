from odoo import api, models

_STATE_BUCKETS = {
    "1_done": "done",
    "1_canceled": "canceled",
}


class ProjectTask(models.Model):
    _inherit = "project.task"

    @api.model
    def get_dag_data(self, domain=None):
        """Return a recordset's dependency DAG as ``{nodes, edges}``.

        ``edges`` run from a predecessor (``depend_on_ids``, "Blocked By") to the
        task it blocks, so an arrow ``A -> B`` means "A blocks B". Only edges whose
        both endpoints are inside the searched recordset are returned, and node
        ``state`` is normalized to ``done``/``canceled``/``open`` so the generic
        view stays unaware of ``project.task``'s concrete state values. Read-only;
        the search is already constrained by the caller's access rights.
        """
        tasks = self.search(domain or [])
        ids = set(tasks.ids)
        nodes = [
            {
                "id": task.id,
                "name": task.name,
                "state": _STATE_BUCKETS.get(task.state, "open"),
            }
            for task in tasks
        ]
        edges = [
            {"source": dep.id, "target": task.id}
            for task in tasks
            for dep in task.depend_on_ids
            if dep.id in ids
        ]
        return {"nodes": nodes, "edges": edges}
