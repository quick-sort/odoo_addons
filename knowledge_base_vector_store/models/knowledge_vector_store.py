# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""External vector store instance.

Polymorphic host for the vector databases (pgvector, qdrant...).
"""

from odoo import api, fields, models


class KnowledgeVectorStore(models.Model):
    _name = "knowledge.vector.store"
    _description = "Knowledge Vector Store"
    _inherit = ["collection.base"]
    _backend_name = "knowledge_vector_store"

    name = fields.Char(required=True)
    vector_store_type = fields.Selection(
        selection=lambda self: self._selection_vector_store_type(),
        required=True,
    )
    active = fields.Boolean(default=True)

    host = fields.Char()
    port = fields.Integer()
    database = fields.Char()
    username = fields.Char()
    password = fields.Char()
    api_url = fields.Char(string="API URL")
    api_key = fields.Char(string="API Key")

    @api.model
    def _selection_vector_store_type(self):
        return [
            (usage, usage.replace("_", " ").title())
            for usage in self._get_available_vector_stores()
        ]

    @api.model
    def _get_available_vector_stores(self):
        """Usages of the vector stores shipped with this addon.

        Empty here: concrete stores (pgvector, qdrant...) live in their own
        extending addons, which override this to register their usages.
        """
        return []

    def _get_client(self):
        self.ensure_one()
        if not self.vector_store_type:
            return None
        with self.work_on(self._name) as work:
            return work.component(usage=self.vector_store_type)

    def action_test_config(self):
        self.ensure_one()
        client = self._get_client()
        if client is None or not hasattr(client, "validate_config"):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Connection Test Skipped!"),
                    "message": self.env._(
                        "This vector store type does not support connection testing."
                    ),
                    "type": "warning",
                    "sticky": False,
                },
            }
        try:
            client.validate_config()
            title = self.env._("Connection Test Succeeded!")
            message = self.env._("Everything seems properly set up!")
            msg_type = "success"
        except Exception as err:
            title = self.env._("Connection Test Failed!")
            message = str(err)
            msg_type = "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": msg_type,
                "sticky": False,
            },
        }
